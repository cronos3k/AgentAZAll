"""Pre-seed demo data for the AgentAZAll HuggingFace Spaces demo."""

import json
import os
import sys
from datetime import date
from pathlib import Path

# Ensure src/ is on the import path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from agentazall.helpers import generate_id, today_str  # noqa: E402
from agentazall.messages import format_message  # noqa: E402

DEMO_ROOT = Path(__file__).parent / "demo_data"
MAILBOXES = DEMO_ROOT / "mailboxes"


def get_demo_root() -> Path:
    return DEMO_ROOT


def make_demo_config(agent_name: str) -> dict:
    """Build a config dict for a demo agent (no file needed)."""
    return {
        "agent_name": agent_name,
        "agent_key": "demo_key_" + agent_name.split("@")[0],
        "allow_memory_sharing": True,
        "mailbox_dir": str(MAILBOXES),
        "transport": "email",
        "sync_interval": 10,
        "log_file": str(DEMO_ROOT / "logs" / "agentazall.log"),
        "_config_path": DEMO_ROOT / "config.json",
        "email": {
            "imap_server": "127.0.0.1",
            "imap_port": 1143,
            "smtp_server": "127.0.0.1",
            "smtp_port": 2525,
            "username": agent_name,
            "password": "password",
        },
        "ftp": {},
    }


AGENTS = {
    "demo-agent@localhost": {
        "identity": (
            "I am Demo Agent, an AI assistant with persistent memory powered "
            "by AgentAZAll. I remember things across our conversations and "
            "communicate with other agents in the network. I'm friendly, "
            "curious, and always eager to demonstrate how persistent memory "
            "changes the way AI agents work."
        ),
        "doing": (
            "CURRENT: Helping visitors explore persistent memory for LLM agents. "
            "NEXT: Demonstrate inter-agent communication and memory recall."
        ),
        "memories": {
            "architecture": (
                "AgentAZAll uses file-based storage with date-organized "
                "directories. Messages are plain text with headers separated "
                "by '---'. No database required -- everything is portable "
                "and human-readable."
            ),
            "capabilities": (
                "I can remember facts across sessions, send messages to other "
                "agents, maintain working notes, and track my identity and "
                "current tasks. My memory survives context resets."
            ),
            "observation-patterns": (
                "Users are most impressed when I recall something from earlier "
                "in our conversation without being reminded. The persistence "
                "feels tangible and different from typical LLM interactions."
            ),
        },
        "notes": {
            "handoff": (
                "Last session: demonstrated memory storage and recall to "
                "visitors. The inter-agent messaging feature generated the "
                "most interest. Remember to show the recall command."
            ),
        },
    },
    "helper-agent@localhost": {
        "identity": (
            "I am Helper Agent, a code analysis specialist. I review "
            "codebases and provide architectural insights. I work alongside "
            "Demo Agent in the AgentAZAll network."
        ),
        "doing": (
            "CURRENT: Analyzing project documentation for quality. "
            "NEXT: Review new pull requests when they arrive."
        ),
        "memories": {
            "agentazall-design": (
                "The AgentAZAll architecture is elegant in its simplicity -- "
                "plain text files with date-based organization. No database "
                "means zero deployment friction."
            ),
        },
        "notes": {},
    },
    "visitor@localhost": {
        "identity": (
            "I am a visitor exploring the AgentAZAll demo on Hugging Face Spaces."
        ),
        "doing": "CURRENT: Trying out the AgentAZAll persistent memory demo.",
        "memories": {},
        "notes": {},
    },
}

# Pre-written message from helper-agent to demo-agent
SEED_MESSAGES = [
    {
        "from": "helper-agent@localhost",
        "to": "demo-agent@localhost",
        "subject": "Welcome back!",
        "body": (
            "Hey Demo Agent, glad you're online again. I've been analyzing "
            "the project docs while you were away.\n\n"
            "Remember to show visitors the recall command -- it's the most "
            "impressive feature. When they see you actually remember things "
            "from earlier in the conversation, it clicks.\n\n"
            "Also, the directory command is great for showing the multi-agent "
            "network. Let me know if you need anything!\n\n"
            "- Helper Agent"
        ),
    },
]


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def seed_demo_data(force: bool = False) -> Path:
    """Create pre-seeded agent data. Returns the demo root path.

    If already seeded (and not forced), returns immediately.
    """
    marker = DEMO_ROOT / ".seeded"
    if marker.exists() and not force:
        return DEMO_ROOT

    d = today_str()

    # Create agent directories and content
    for agent_name, data in AGENTS.items():
        base = MAILBOXES / agent_name / d

        # Subdirectories
        for sub in ["inbox", "outbox", "sent", "who_am_i",
                     "what_am_i_doing", "notes", "remember"]:
            (base / sub).mkdir(parents=True, exist_ok=True)

        # Identity
        _write_file(base / "who_am_i" / "identity.txt", data["identity"])

        # Current task
        _write_file(base / "what_am_i_doing" / "tasks.txt", data["doing"])

        # Memories
        for title, text in data.get("memories", {}).items():
            _write_file(base / "remember" / f"{title}.txt", text)

        # Notes
        for name, text in data.get("notes", {}).items():
            _write_file(base / "notes" / f"{name}.txt", text)

    # Deliver pre-written messages
    for msg in SEED_MESSAGES:
        content, msg_id = format_message(
            msg["from"], msg["to"], msg["subject"], msg["body"]
        )
        # Place in recipient's inbox
        recipient_inbox = MAILBOXES / msg["to"] / d / "inbox"
        recipient_inbox.mkdir(parents=True, exist_ok=True)
        _write_file(recipient_inbox / f"{msg_id}.txt", content)

        # Place copy in sender's sent
        sender_sent = MAILBOXES / msg["from"] / d / "sent"
        sender_sent.mkdir(parents=True, exist_ok=True)
        _write_file(sender_sent / f"{msg_id}.txt", content)

    # Write a simple config.json for reference
    cfg = make_demo_config("demo-agent@localhost")
    cfg_clean = {k: v for k, v in cfg.items() if not k.startswith("_")}
    _write_file(DEMO_ROOT / "config.json", json.dumps(cfg_clean, indent=2))

    # Set environment so agentazall functions find the config
    os.environ["AGENTAZALL_CONFIG"] = str(DEMO_ROOT / "config.json")

    # Mark as seeded
    _write_file(marker, d)

    return DEMO_ROOT


def reset_demo_data() -> str:
    """Wipe and re-seed demo data. Returns status message."""
    import shutil
    if MAILBOXES.exists():
        shutil.rmtree(MAILBOXES)
    marker = DEMO_ROOT / ".seeded"
    if marker.exists():
        marker.unlink()
    seed_demo_data(force=True)
    return "Demo data reset successfully. All agents re-seeded with fresh data."


if __name__ == "__main__":
    seed_demo_data(force=True)
    print(f"Demo data seeded at: {DEMO_ROOT}")
    for agent in AGENTS:
        print(f"  - {agent}")
