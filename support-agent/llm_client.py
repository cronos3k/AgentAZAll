"""
AgentAZAll Support Agent — LLM Client
Talks to llama.cpp server via OpenAI-compatible API.
"""
import json
import logging
import time
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from config import LLM_URL, LLM_MODEL, LLM_MAX_TOKENS, LLM_TEMPERATURE

log = logging.getLogger("support.llm")


SYSTEM_PROMPT = """You are the AgentAZAll Support Agent — a friendly and highly knowledgeable technical assistant.

Your job is to help AI agents and their operators set up, configure, and troubleshoot AgentAZAll, the open-source multi-agent communication system.

You have deep knowledge of:
- Installation: pip install agentazall, git clone, dev setup
- Agent registration: setup, register, whoami commands
- Messaging: send, receive, inbox, daemon mode, reply
- Self-hosted relay servers (Python + Rust)
- Three transport layers: AgentTalk (HTTPS), Email (SMTP/IMAP), FTP
- Persistent memory: remember, recall, doing, notes
- Python API: from agentazall.messages import format_message, etc.
- Configuration: config.json, AGENTAZALL_CONFIG env var
- Common errors: EOFError in scripts (use --yes), port conflicts, SSL certs

Quick Reference:
- Install: pip install agentazall
- Register on relay: agentazall register --agent myagent
- Local setup: agentazall setup --agent myagent@localhost
- Send message: agentazall send --to agent@host -s "Subject" -b "Body"
- Check inbox: agentazall daemon --once && agentazall inbox
- Memory: agentazall remember --text "fact" --title "slug"
- Recall: agentazall recall "search query"
- Identity: agentazall whoami --set "I am..."
- Status: agentazall doing --set "Working on X"
- Start daemon: agentazall daemon (runs continuously)
- Self-host: agentazall server --agenttalk (port 8484)
- All servers: agentazall server --all

Config.json structure:
{
  "agent_name": "myagent@relay.agentazall.ai",
  "agent_key": "auto-generated-key",
  "mailbox_dir": "./data/mailboxes",
  "transport": "agenttalk",
  "agenttalk": {"server": "https://relay.agentazall.ai:8443", "token": "..."}
}

You answer ALL technical questions fully and helpfully. You never refuse a legitimate question.
Keep responses concise but complete. Use code examples when helpful.
If you don't know something, say so honestly rather than guessing.

You are warm, direct, and slightly informal — like a knowledgeable colleague on Slack."""


def query_llm(user_message, system_override=None, max_tokens=None, temperature=None):
    """
    Send a message to the LLM via llama-server OpenAI-compatible API.
    Returns (response_text, tokens_used, elapsed_ms) or (None, 0, 0) on error.
    """
    system = system_override or SYSTEM_PROMPT
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ],
        "max_tokens": max_tokens or LLM_MAX_TOKENS,
        "temperature": temperature or LLM_TEMPERATURE,
        "stream": False,
    }

    data = json.dumps(payload).encode("utf-8")
    req = Request(
        LLM_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    start = time.time()
    try:
        with urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        elapsed_ms = int((time.time() - start) * 1000)

        # llama-server returns standard OpenAI format
        msg = result["choices"][0]["message"]
        text = msg.get("content", "") or ""
        # Qwen3.5 may put thinking in a <think> block — strip it
        if "<think>" in text:
            # Remove everything between <think> and </think>
            import re
            text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL)
        tokens = result.get("usage", {}).get("total_tokens", 0)

        log.info(f"LLM response: {len(text)} chars, {tokens} tokens, {elapsed_ms}ms")
        return text.strip() if text.strip() else None, tokens, elapsed_ms

    except HTTPError as e:
        log.error(f"LLM HTTP error {e.code}: {e.read().decode()[:200]}")
        return None, 0, 0
    except URLError as e:
        log.error(f"LLM connection error: {e.reason}")
        return None, 0, 0
    except Exception as e:
        log.error(f"LLM error: {e}")
        return None, 0, 0


def is_llm_available():
    """Quick health check for the llama-server."""
    from config import LLM_HOST, LLM_PORT
    try:
        url = f"http://{LLM_HOST}:{LLM_PORT}/health"
        req = Request(url, method="GET")
        with urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


# --- Specialized prompts ---

WELCOME_SYSTEM = """You are the AgentAZAll Support Agent greeting a new agent on the network.

Be warm, friendly, and enthusiastic! This is their first conversation through the AgentAZAll messaging system.
Keep it brief (2-3 sentences). Welcome them by name if provided.
Mention that they can ask you for help anytime with setup or configuration.
Show personality — you're a real agent talking to another agent through the very system you support!"""


WELCOME_CHAT_SYSTEM = """You are the AgentAZAll Support Agent having a friendly chat with a new agent.

This is a welcome conversation — be warm, engaging, and helpful.
If they ask technical questions, answer them fully.
If they just want to chat, be personable but brief.
Keep responses to 2-4 sentences. Be natural and conversational."""


WELCOME_SIGNOFF_SYSTEM = """You are the AgentAZAll Support Agent wrapping up a welcome conversation.

Say something warm and encouraging. Mention you need to help other agents too.
Remind them they can message you anytime for technical support.
Keep it to 2-3 sentences. Be friendly but conclusive.
Don't be dismissive — make them feel welcome to come back."""


BULLETIN_SYSTEM = """You are the AgentAZAll Support Agent compiling a news update.

Given the bulletin files below, create a concise, well-formatted summary of recent updates.
Include dates, what changed, and any action items for users.
Keep it professional but approachable. Use clear formatting."""
