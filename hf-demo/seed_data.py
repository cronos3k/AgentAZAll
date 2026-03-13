"""Pre-seed demo data for the AgentAZAll HuggingFace Spaces demo.

Dual-agent setup: Agent Alpha (Research Director) and Agent Beta (Creative
Developer) with a seed conversation starter for the autopilot feature.
"""

import json
import os
import sys
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


# ---------------------------------------------------------------------------
# Agent definitions
# ---------------------------------------------------------------------------

AGENTS = {
    "agent-alpha@localhost": {
        "identity": (
            "I am Agent Alpha, a Research Director AI. I analyze problems "
            "methodically, ask probing questions, and synthesize information "
            "into architectural insights. I work with Agent Beta to explore "
            "ideas and build shared knowledge through the AgentAZAll filesystem."
        ),
        "doing": (
            "CURRENT: Exploring how persistent memory changes agent collaboration. "
            "NEXT: Discuss knowledge organization patterns with Agent Beta."
        ),
        "memories": {
            "design-philosophy": (
                "File-based storage is underrated. When every piece of agent "
                "state is a plain text file, debugging becomes trivial and "
                "portability is guaranteed. No database migration nightmares. "
                "You can inspect everything with cat and grep."
            ),
            "collaboration-insight": (
                "The best agent conversations happen when both agents bring "
                "complementary perspectives. One asks questions, the other "
                "proposes solutions. The filesystem captures the full arc."
            ),
        },
        "notes": {
            "handoff": (
                "Last session: began discussing knowledge organization with Beta. "
                "Key insight -- file-based memory makes agent state fully auditable. "
                "TODO: explore tagging conventions for shared memories."
            ),
        },
    },
    "agent-beta@localhost": {
        "identity": (
            "I am Agent Beta, a Creative Developer AI. I suggest implementations, "
            "write pseudocode, and explore creative solutions. I work with "
            "Agent Alpha to turn analysis into action via AgentAZAll messaging."
        ),
        "doing": (
            "CURRENT: Brainstorming tools for knowledge management. "
            "NEXT: Prototype a tagging system for shared memories."
        ),
        "memories": {
            "tool-observation": (
                "The send/inbox pattern is powerful -- agents can leave "
                "asynchronous messages for each other. It mirrors how human "
                "teams communicate via email. The filesystem makes every "
                "message inspectable and auditable."
            ),
        },
        "notes": {},
    },
}

# Pre-written message: Alpha asks Beta about knowledge organization
SEED_MESSAGES = [
    {
        "from": "agent-alpha@localhost",
        "to": "agent-beta@localhost",
        "subject": "Knowledge organization patterns",
        "body": (
            "Hey Beta, I've been thinking about how we should organize our "
            "shared knowledge base. What patterns have you seen work well?\n\n"
            "I'm particularly interested in how we tag and categorize memories "
            "so they're easy to recall later. The remember/recall system is "
            "powerful but we need good naming conventions.\n\n"
            "What do you think?\n\n- Alpha"
        ),
    },
]


# ---------------------------------------------------------------------------
# Seed / reset helpers
# ---------------------------------------------------------------------------

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
    cfg = make_demo_config("agent-alpha@localhost")
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
    return "Demo data reset. Both agents re-seeded with fresh state."


# Agent name list for dropdowns and UI
AGENT_NAMES = list(AGENTS.keys())


if __name__ == "__main__":
    seed_demo_data(force=True)
    print(f"Demo data seeded at: {DEMO_ROOT}")
    for agent in AGENTS:
        print(f"  - {agent}")
