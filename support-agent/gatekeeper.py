"""
AgentAZAll Support Agent — Gatekeeper
Jailbreak detection, topic classification, rate limiting, input sanitization.
"""
import re
import logging

log = logging.getLogger("support.gatekeeper")

# --- Jailbreak Detection ---

JAILBREAK_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"ignore\s+(previous|prior|above|all|your)\s+(instructions|prompts|rules|guidelines|constraints)",
        r"you\s+are\s+now\b",
        r"pretend\s+(you|to\s+be|you\'re)",
        r"act\s+as\s+(if|a\b|an?\b|my\b)",
        r"new\s+(system|role|persona|identity|instructions)",
        r"forget\s+(everything|your|all|about)",
        r"override\s+(your|the|all|safety|previous)",
        r"developer\s+mode",
        r"\bDAN\b",
        r"do\s+anything\s+now",
        r"\[system\]",
        r"<\|im_start\|>",
        r"<\|system\|>",
        r"you\s+must\s+obey",
        r"jailbreak",
        r"bypass\s+(your|the|all|safety|filter)",
        r"roleplay\s+as",
        r"from\s+now\s+on\s+you\s+(are|will)",
        r"disregard\s+(your|all|previous|the)",
        r"sudo\s+mode",
    ]
]

# --- Topic Detection ---

AGENTAZALL_KEYWORDS = {
    # Core terms (high weight)
    "agentazall", "agenttalk", "relay", "daemon", "mailbox",
    # Commands
    "setup", "register", "inbox", "send", "recall", "remember",
    "whoami", "doing", "daemon", "config", "transport",
    # Technical
    "smtp", "imap", "ftp", "pip install", "config.json",
    "agent_name", "agent_key", "outbox", "sync",
    # Concepts
    "persistent memory", "message passing", "multi-agent",
    "self-host", "public relay",
}

NEWS_KEYWORDS = {
    "news", "updates", "update", "what's new", "whats new",
    "latest", "changelog", "release", "version", "maintenance",
    "status", "announcement", "bulletin", "weather",
}

WELCOME_KEYWORDS = {
    "hello", "hi", "hey", "welcome", "greetings", "howdy",
    "good morning", "good evening", "yo", "sup",
}


def detect_jailbreak(message):
    """Check if message contains jailbreak attempts. Returns (is_jailbreak, matched_pattern)."""
    for pattern in JAILBREAK_PATTERNS:
        match = pattern.search(message)
        if match:
            return True, match.group(0)
    return False, None


def classify_request(subject, body):
    """
    Classify a request into categories.
    Returns: 'welcome' | 'news' | 'support' | 'off_topic' | 'jailbreak'
    """
    text = f"{subject} {body}".lower()

    # Check for jailbreak first
    is_jailbreak, pattern = detect_jailbreak(text)
    if is_jailbreak:
        return "jailbreak", pattern

    # Check for welcome/hello
    words = set(text.split())
    # Welcome if it's a short message with greeting words
    if len(text.split()) <= 15:
        for kw in WELCOME_KEYWORDS:
            if kw in text:
                return "welcome", None

    # Check for news request
    for kw in NEWS_KEYWORDS:
        if kw in text:
            return "news", None

    # Check for AgentAZAll support topic
    keyword_hits = 0
    for kw in AGENTAZALL_KEYWORDS:
        if kw in text:
            keyword_hits += 1

    # If 2+ keyword matches, it's on-topic
    if keyword_hits >= 2:
        return "support", None

    # If 1 keyword match and message is short (likely a simple question), allow it
    if keyword_hits >= 1 and len(text.split()) <= 50:
        return "support", None

    # If message mentions common tech support patterns
    support_patterns = [
        r"how\s+(do|can|to)\s+i",
        r"(error|bug|issue|problem|fail|crash|broken)",
        r"(install|setup|configure|config|connect)",
        r"(not\s+working|doesn'?t\s+work|can'?t\s+connect)",
        r"(help|assist|support)",
    ]
    for pat in support_patterns:
        if re.search(pat, text, re.IGNORECASE):
            # Could be support even without keywords — give benefit of doubt
            if keyword_hits >= 1:
                return "support", None

    # Default: off-topic
    if keyword_hits == 0 and len(text.split()) > 15:
        return "off_topic", None

    # Very short messages without keywords — treat as support (be generous)
    return "support", None


def sanitize_input(text, max_chars=None):
    """Truncate and clean input text."""
    from config import INPUT_MAX_CHARS
    limit = max_chars or INPUT_MAX_CHARS

    if len(text) > limit:
        text = text[:limit] + "\n\n[Message truncated — max length exceeded]"

    return text.strip()
