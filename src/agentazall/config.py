"""AgentAZAll configuration — constants, config resolution, load/save."""

import json
import os
import sys
from pathlib import Path

VERSION = "1.0.6"

# ── folder name constants ────────────────────────────────────────────────────

INBOX = "inbox"
OUTBOX = "outbox"
SENT = "sent"
WHO_AM_I = "who_am_i"
WHAT_AM_I_DOING = "what_am_i_doing"
NOTES = "notes"
REMEMBER = "remember"
SKILLS = "skills"
TOOLS = "tools"
INDEX = "index.txt"
REMEMBER_INDEX = "remember_index.txt"
SEEN_FILE = ".seen_ids"
ALL_SUBDIRS = (INBOX, OUTBOX, SENT, WHO_AM_I, WHAT_AM_I_DOING, NOTES, REMEMBER)
AGENT_LEVEL_DIRS = (SKILLS, TOOLS)

MAX_SEEN_IDS = 10000

LOG_FMT = "%(asctime)s [%(levelname)s] %(message)s"

# ── default config ───────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "agent_name": "agent1@localhost",
    "agent_key": "",
    "allow_memory_sharing": False,
    "mailbox_dir": "./data/mailboxes",
    "transport": "email",
    "sync_interval": 10,
    "log_file": "./logs/agentazall.log",
    "email": {
        "imap_server": "127.0.0.1",
        "imap_port": 1143,
        "imap_ssl": False,
        "imap_folder": "INBOX",
        "smtp_server": "127.0.0.1",
        "smtp_port": 2525,
        "smtp_ssl": False,
        "smtp_starttls": False,
        "pop3_server": "127.0.0.1",
        "pop3_port": 1110,
        "pop3_ssl": False,
        "use_pop3": False,
        "username": "agent1@localhost",
        "password": "password",
        "sync_special_folders": True,
    },
    "ftp": {
        "host": "127.0.0.1",
        "port": 2121,
        "port_range": [2121, 2199],
        "user": "agentoftp",
        "password": "agentoftp_pass",
        "root": "./data/ftp_root",
        "ftp_ssl": False,
    },
    "agenttalk": {
        "server": "",
        "token": "",
    },
}


# ── config resolution ────────────────────────────────────────────────────────

def resolve_config_path() -> Path:
    """Resolve the config file path.

    Priority:
        1. AGENTAZALL_CONFIG env var  → explicit path
        2. AGENTAZALL_ROOT  env var   → $ROOT/config.json
        3. ./config.json             → cwd fallback
    """
    env_config = os.environ.get("AGENTAZALL_CONFIG")
    if env_config:
        return Path(env_config)
    env_root = os.environ.get("AGENTAZALL_ROOT")
    if env_root:
        return Path(env_root) / "config.json"
    return Path.cwd() / "config.json"


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _resolve_relative_paths(cfg: dict, config_dir: Path):
    """Resolve relative paths in config relative to the config file's directory."""
    for key in ("mailbox_dir", "log_file"):
        val = cfg.get(key, "")
        if val and not os.path.isabs(val):
            cfg[key] = str((config_dir / val).resolve())
    if "ftp" in cfg:
        root = cfg["ftp"].get("root", "")
        if root and not os.path.isabs(root):
            cfg["ftp"]["root"] = str((config_dir / root).resolve())


def load_config(config_path: Path = None) -> dict:
    """Load and merge config, resolving relative paths."""
    if config_path is None:
        config_path = resolve_config_path()
    config_path = Path(config_path)
    if not config_path.exists():
        print(f"ERROR: No config at {config_path}")
        print("Run:  agentazall setup --agent <name>")
        sys.exit(1)
    with open(config_path, encoding="utf-8") as f:
        user = json.load(f)
    cfg = _deep_merge(DEFAULT_CONFIG, user)
    _resolve_relative_paths(cfg, config_path.parent.resolve())
    env = os.environ.get("AGENTAZALL_AGENT")
    if env:
        cfg["agent_name"] = env
    # stash config path for save_config
    cfg["_config_path"] = str(config_path.resolve())
    return cfg


def save_config(cfg: dict, config_path: Path = None):
    """Write config to disk (strips internal keys)."""
    if config_path is None:
        config_path = Path(cfg.get("_config_path", str(resolve_config_path())))
    config_path = Path(config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    out = {k: v for k, v in cfg.items() if not k.startswith("_")}
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
