"""AgentoAll helpers — date utils, path helpers, identity validation."""

import hashlib
import json
import os
import re
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import List

from .config import (
    AGENT_LEVEL_DIRS,
    ALL_SUBDIRS,
)

# ── date/time ────────────────────────────────────────────────────────────────

def today_str() -> str:
    return date.today().isoformat()


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── path helpers ─────────────────────────────────────────────────────────────

def agent_base(cfg) -> Path:
    return Path(cfg["mailbox_dir"]) / cfg["agent_name"]


def agent_day(cfg, d=None) -> Path:
    return agent_base(cfg) / (d or today_str())


def shared_dir(cfg) -> Path:
    """Return the shared tools/skills root: data/shared/"""
    return Path(cfg["mailbox_dir"]).parent / "shared"


def ensure_dirs(cfg, d=None) -> Path:
    root = agent_day(cfg, d)
    for sub in ALL_SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    base = agent_base(cfg)
    for sub in AGENT_LEVEL_DIRS:
        (base / sub).mkdir(parents=True, exist_ok=True)
    return root


def date_dirs(cfg) -> List[str]:
    b = agent_base(cfg)
    if not b.exists():
        return []
    return sorted(
        d.name for d in b.iterdir()
        if d.is_dir() and re.match(r"\d{4}-\d{2}-\d{2}$", d.name)
    )


# ── id / sanitization ───────────────────────────────────────────────────────

def generate_id(from_a, to_a, subject) -> str:
    raw = f"{from_a}|{to_a}|{subject}|{datetime.now().isoformat()}|{os.urandom(8).hex()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def sanitize(name: str) -> str:
    return re.sub(r'[^\w\-.]', '_', name)


def safe_move(src: str, dst: str):
    """Move file safely on Windows (copy+remove fallback)."""
    try:
        shutil.move(src, dst)
    except (PermissionError, OSError):
        shutil.copy2(src, dst)
        os.remove(src)


# ── identity validation ─────────────────────────────────────────────────────

def validate_agent_key(cfg: dict) -> bool:
    """Verify that the config's agent_key matches the key stored in the mailbox."""
    key_file = agent_base(cfg) / ".agent_key"
    if not key_file.exists():
        return True  # legacy agent without key
    try:
        stored = json.loads(key_file.read_text(encoding="utf-8"))
        config_key = cfg.get("agent_key", "")
        if not config_key:
            return True  # legacy config without key
        return stored.get("key") == config_key
    except Exception:
        return True  # don't block on corrupted key files


def require_identity(cfg: dict):
    """Validate agent key before any write operation. Exit if invalid."""
    import sys
    if not validate_agent_key(cfg):
        agent = cfg.get("agent_name", "unknown")
        print(f"ERROR: Identity verification failed for '{agent}'.")
        print("Your config key does not match the agent's registered key.")
        print("You cannot write to another agent's space.")
        sys.exit(1)


def can_read_agent_memories(cfg: dict, target_agent: str) -> bool:
    """Check if current agent is allowed to read target agent's memories."""
    if cfg["agent_name"] == target_agent:
        return True
    target_base = Path(cfg["mailbox_dir"]) / target_agent
    key_file = target_base / ".agent_key"
    if key_file.exists():
        try:
            stored = json.loads(key_file.read_text(encoding="utf-8"))
            return stored.get("allow_memory_sharing", False)
        except Exception:
            pass
    return False
