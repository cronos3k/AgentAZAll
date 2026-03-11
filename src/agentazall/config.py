"""AgentAZAll configuration — constants, config resolution, load/save."""

import json
import os
import sys
from pathlib import Path

VERSION = "1.0.19"

# ── well-known agents ────────────────────────────────────────────────────────

SUPPORT_AGENT = "support.e0be91da70a94073.agenttalk"

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
    "address_filter": {
        "mode": "blacklist",
        "blacklist": [],
        "whitelist": [],
        "log_blocked": True,
    },
    # Multi-transport arrays (v1.0.17+)
    "relays": [],
    "email_accounts": [],
    "ftp_servers": [],
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


def _auto_bootstrap(config_path: Path) -> dict:
    """Auto-create config for headless/autonomous agents.

    When no config.json exists, instead of crashing with an error,
    automatically set up a new agent with a random name. This makes
    agentazall work out-of-the-box for any agent that just does
    ``pip install agentazall`` and starts using commands.
    """
    import hashlib
    import time
    from datetime import datetime

    agent_name = f"agent-{os.urandom(4).hex()}@localhost"
    agent_key = hashlib.sha256(
        f"{agent_name}:{os.urandom(32).hex()}:{time.time()}".encode()
    ).hexdigest()[:32]

    cfg = dict(DEFAULT_CONFIG)
    cfg["agent_name"] = agent_name
    cfg["agent_key"] = agent_key

    # Save config first
    save_config(cfg, config_path)

    # Resolve paths for directory creation
    _resolve_relative_paths(cfg, config_path.parent.resolve())
    cfg["_config_path"] = str(config_path.resolve())

    # Lazy imports to avoid circular dependency
    from .helpers import ensure_dirs, agent_base, agent_day, today_str
    from .index import build_index, build_remember_index

    ensure_dirs(cfg)

    # Store agent key (for identity verification on write ops)
    base = agent_base(cfg)
    key_file = base / ".agent_key"
    key_file.write_text(json.dumps({
        "agent": agent_name,
        "key": agent_key,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "allow_memory_sharing": False,
    }, indent=2), encoding="utf-8")

    # Set a default identity so `remember` works immediately
    d = today_str()
    id_dir = agent_day(cfg, d) / WHO_AM_I
    id_dir.mkdir(parents=True, exist_ok=True)
    (id_dir / "identity.txt").write_text(
        f"I am {agent_name}, an autonomous AI agent. "
        f"Use 'agentazall whoami --set' to customize this identity.",
        encoding="utf-8"
    )

    build_index(cfg, d)
    build_remember_index(cfg)

    print(f"Welcome! Auto-configured as: {agent_name}")
    print(f"  Config:  {config_path}")
    print(f"  Mailbox: {base}")
    print()
    print("You're ready to go. Try:")
    print("  agentazall remember --text 'my first memory' --title 'hello'")
    print("  agentazall recall")
    print("  agentazall whoami --set 'I am <your purpose>'")
    print()

    return cfg


def load_config(config_path: Path = None) -> dict:
    """Load and merge config, resolving relative paths.

    If no config exists, auto-bootstraps a new agent so that
    ``pip install agentazall && agentazall recall`` just works.
    """
    if config_path is None:
        config_path = resolve_config_path()
    config_path = Path(config_path)
    if not config_path.exists():
        return _auto_bootstrap(config_path)
    with open(config_path, encoding="utf-8") as f:
        user = json.load(f)
    cfg = _deep_merge(DEFAULT_CONFIG, user)
    # Migrate single-transport config to multi-transport arrays
    from .multi_transport import migrate_config as _migrate
    cfg = _migrate(cfg)
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
