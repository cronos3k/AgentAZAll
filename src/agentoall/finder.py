"""AgentoAll message finder — locate messages and manage seen IDs."""

import re
from pathlib import Path
from typing import Optional

from .config import INBOX, MAX_SEEN_IDS, OUTBOX, SEEN_FILE, SENT
from .helpers import agent_base, date_dirs


def find_message(cfg, msg_id, d=None) -> Optional[Path]:
    """Find a message file by ID, searching across dates and folders."""
    b = agent_base(cfg)
    if not b.exists():
        return None
    dates = [d] if d else sorted(
        (x.name for x in b.iterdir()
         if x.is_dir() and re.match(r"\d{4}-\d{2}-\d{2}$", x.name)),
        reverse=True,
    )
    for dd in dates:
        for folder in (INBOX, SENT, OUTBOX):
            exact = b / dd / folder / f"{msg_id}.txt"
            if exact.exists():
                return exact
            fp = b / dd / folder
            if fp.exists():
                for f in fp.glob("*.txt"):
                    if msg_id in f.stem:
                        return f
    return None


def find_latest_file(cfg, rel_path) -> Optional[str]:
    """Find the latest version of a file across all date directories."""
    for d in reversed(date_dirs(cfg)):
        fp = agent_base(cfg) / d / rel_path
        if fp.exists():
            return fp.read_text(encoding="utf-8")
    return None


# ── seen IDs ─────────────────────────────────────────────────────────────────

def load_seen(cfg) -> set:
    p = agent_base(cfg) / SEEN_FILE
    if p.exists():
        return set(p.read_text(encoding="utf-8").strip().splitlines())
    return set()


def save_seen(cfg, seen: set):
    if len(seen) > MAX_SEEN_IDS:
        seen_list = sorted(seen)
        seen.clear()
        seen.update(seen_list[-MAX_SEEN_IDS:])
    p = agent_base(cfg) / SEEN_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(sorted(seen)), encoding="utf-8")
