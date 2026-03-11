"""
AgentAZAll Support Agent — Knowledge System
Handles teaching ingestion, knowledge retrieval, and context augmentation.

Teaching messages use subject prefix "TEACH:" and contain structured knowledge
that gets parsed, stored, and injected into future support responses.
"""
import re
import logging
from db import store_knowledge, search_knowledge, mark_knowledge_used, get_knowledge_count
from config import (
    KNOWLEDGE_MAX_CONTEXT_ENTRIES,
    KNOWLEDGE_MAX_CONTEXT_CHARS,
    KNOWLEDGE_MIN_RELEVANCE,
)

log = logging.getLogger("support.knowledge")


# --- Teaching Ingestion ---

def parse_teaching(subject, body):
    """
    Parse a TEACH: message into topic, content, and keywords.

    Expected format:
        Subject: TEACH: <topic>
        Body: <knowledge content>

        Optional last line: KEYWORDS: keyword1, keyword2, keyword3

    Returns (topic, content, keywords_str) or (None, None, None) on failure.
    """
    # Extract topic from subject
    topic = subject.strip()
    if topic.upper().startswith("TEACH:"):
        topic = topic[6:].strip()
    if not topic:
        return None, None, None

    if not body or not body.strip():
        return None, None, None

    content = body.strip()
    keywords = []

    # Check for explicit KEYWORDS: line at the end
    lines = content.split("\n")
    for i in range(len(lines) - 1, max(len(lines) - 4, -1), -1):
        line = lines[i].strip()
        if line.upper().startswith("KEYWORDS:"):
            kw_text = line[9:].strip()
            keywords = [k.strip().lower() for k in kw_text.split(",") if k.strip()]
            content = "\n".join(lines[:i]).strip()
            break

    # Auto-extract keywords from topic + content if none provided
    if not keywords:
        keywords = _extract_keywords(topic, content)

    keywords_str = ",".join(keywords)
    log.info(f"Parsed teaching: topic='{topic}', {len(content)} chars, keywords=[{keywords_str}]")
    return topic, content, keywords_str


def _extract_keywords(topic, content):
    """
    Auto-extract keywords from topic and content.
    Focuses on technical terms relevant to AgentAZAll.
    """
    text = f"{topic} {content}".lower()
    words = set(re.findall(r'[a-z][a-z0-9_-]{2,}', text))

    # High-value technical terms to always capture if present
    tech_terms = {
        "agentazall", "agenttalk", "relay", "transport", "daemon",
        "mailbox", "inbox", "outbox", "encryption", "e2e", "end-to-end",
        "register", "registration", "config", "configuration", "json",
        "smtp", "imap", "ftp", "https", "websocket", "http",
        "token", "key", "certificate", "ssl", "tls",
        "message", "send", "receive", "sync", "poll",
        "memory", "remember", "recall", "notes", "doing", "whoami",
        "pip", "install", "setup", "python", "cli",
        "server", "client", "host", "port", "address",
        "rust", "binary", "compile", "build",
        "error", "debug", "log", "timeout", "connection",
        "agent", "multi-agent", "network", "protocol",
        "satellite", "gpu", "model", "llm", "inference",
        "onboard", "onboarding", "welcome",
    }

    # Also capture words that appear in topic (always relevant)
    topic_words = set(re.findall(r'[a-z][a-z0-9_-]{2,}', topic.lower()))

    # Combine: tech terms found + topic words + frequent content words
    found_tech = words & tech_terms
    result = found_tech | topic_words

    # Add any capitalized/important terms from content (abbreviations, names)
    caps = set(re.findall(r'\b[A-Z][A-Z0-9]{2,}\b', f"{topic} {content}"))
    result |= {c.lower() for c in caps}

    # Limit to 20 keywords max
    return sorted(result)[:20]


def process_teaching(db, agent_id, subject, body):
    """
    Process a TEACH: message — parse, store, and return confirmation.
    Returns (response_text, stored_id) or (error_text, None).
    """
    topic, content, keywords = parse_teaching(subject, body)

    if topic is None:
        return (
            "I couldn't parse that teaching. Please use this format:\n\n"
            "Subject: TEACH: <Topic Name>\n"
            "Body: <Your knowledge content here>\n\n"
            "Optional last line: KEYWORDS: keyword1, keyword2, keyword3"
        ), None

    # Store in knowledge base
    entry_id = store_knowledge(
        db, topic, content, keywords,
        taught_by=agent_id, source="teaching", priority=7
    )

    total = get_knowledge_count(db)
    log.info(
        f"Knowledge stored: id={entry_id}, topic='{topic}', "
        f"taught_by={agent_id}, total_entries={total}"
    )

    return (
        f"Got it! I've stored your teaching on \"{topic}\" "
        f"(entry #{entry_id}, {len(content)} chars, "
        f"keywords: {keywords}).\n\n"
        f"I now have {total} knowledge entries total. "
        f"This will be used to augment my answers to future support questions. "
        f"Keep teaching me!"
    ), entry_id


# --- Knowledge Retrieval for Support ---

def build_knowledge_context(db, query_text):
    """
    Search knowledge base for entries relevant to the query.
    Returns a formatted context string to inject into the LLM prompt,
    or empty string if no relevant knowledge found.
    """
    results = search_knowledge(db, query_text, limit=KNOWLEDGE_MAX_CONTEXT_ENTRIES * 2)

    if not results:
        return ""

    # Filter by minimum relevance
    relevant = [r for r in results if r["hits"] >= KNOWLEDGE_MIN_RELEVANCE]
    if not relevant:
        return ""

    # Build context string, respecting char limit
    context_parts = []
    total_chars = 0

    for entry in relevant[:KNOWLEDGE_MAX_CONTEXT_ENTRIES]:
        section = f"[{entry['topic']}]\n{entry['content']}"
        if total_chars + len(section) > KNOWLEDGE_MAX_CONTEXT_CHARS:
            # Truncate this entry to fit
            remaining = KNOWLEDGE_MAX_CONTEXT_CHARS - total_chars - 50
            if remaining > 100:
                section = f"[{entry['topic']}]\n{entry['content'][:remaining]}..."
            else:
                break

        context_parts.append(section)
        total_chars += len(section)
        mark_knowledge_used(db, entry["id"])

    if not context_parts:
        return ""

    context = (
        "\n--- KNOWLEDGE BASE (use this to answer accurately) ---\n"
        + "\n\n".join(context_parts)
        + "\n--- END KNOWLEDGE BASE ---\n"
    )

    log.info(
        f"Knowledge context: {len(context_parts)} entries, "
        f"{total_chars} chars for query: {query_text[:80]}"
    )
    return context


def is_teaching_message(subject):
    """Check if a message subject indicates a teaching."""
    return subject.strip().upper().startswith("TEACH:")
