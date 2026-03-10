"""AgentAZAll command: quickstart — one-command full setup.

Designed for autonomous AI agents that just ``pip install agentazall``
and want everything working in a single command. Creates the agent,
sets identity, stores a first memory, and verifies everything works.
"""

import hashlib
import json
import os
import sys
import time
from pathlib import Path

from ..config import (
    DEFAULT_CONFIG,
    REMEMBER,
    WHO_AM_I,
    _resolve_relative_paths,
    save_config,
)
from ..helpers import (
    agent_base,
    agent_day,
    date_dirs,
    ensure_dirs,
    today_str,
)
from ..index import build_index, build_remember_index


def cmd_quickstart(args):
    """One-command setup: creates agent, sets identity, verifies everything.

    Usage:
        agentazall quickstart                              # auto-name
        agentazall quickstart --agent mybot                # specific name
        agentazall quickstart --agent mybot --identity "I am a code reviewer"
    """
    config_path = Path.cwd() / "config.json"

    # ── already configured? just confirm ────────────────────────────────
    if config_path.exists():
        try:
            from ..config import load_config
            cfg = load_config(config_path)
            agent = cfg.get("agent_name", "unknown")
            print(f"Already configured as '{agent}'. Ready to use.")
            print(f"  Mailbox: {agent_base(cfg)}")
            _show_status(cfg)
            return
        except Exception:
            pass  # corrupted config, re-create

    # ── create new agent ────────────────────────────────────────────────
    agent = getattr(args, "agent", None)
    if not agent:
        agent = f"agent-{os.urandom(4).hex()}"

    if "@" not in agent:
        agent = f"{agent}@localhost"

    identity = getattr(args, "identity", None)
    if not identity:
        name_part = agent.split("@")[0]
        identity = f"I am {name_part}, an autonomous AI agent."

    agent_key = hashlib.sha256(
        f"{agent}:{os.urandom(32).hex()}:{time.time()}".encode()
    ).hexdigest()[:32]

    cfg = dict(DEFAULT_CONFIG)
    cfg["agent_name"] = agent
    cfg["agent_key"] = agent_key

    save_config(cfg, config_path)
    _resolve_relative_paths(cfg, config_path.parent.resolve())
    cfg["_config_path"] = str(config_path.resolve())
    ensure_dirs(cfg)

    # Store agent key
    base = agent_base(cfg)
    key_file = base / ".agent_key"
    key_file.write_text(json.dumps({
        "agent": agent,
        "key": agent_key,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "allow_memory_sharing": False,
    }, indent=2), encoding="utf-8")

    # Set identity
    d = today_str()
    id_dir = agent_day(cfg, d) / WHO_AM_I
    id_dir.mkdir(parents=True, exist_ok=True)
    (id_dir / "identity.txt").write_text(identity, encoding="utf-8")

    # Store a first memory as proof everything works
    rem_dir = agent_day(cfg, d) / REMEMBER
    rem_dir.mkdir(parents=True, exist_ok=True)
    (rem_dir / "init.txt").write_text(
        f"Agent '{agent}' initialized via quickstart on {d}.",
        encoding="utf-8"
    )

    build_index(cfg, d)
    build_remember_index(cfg)

    print(f"Ready! Agent '{agent}' is fully configured.")
    print(f"  Identity: {identity}")
    print(f"  Config:   {config_path}")
    print(f"  Mailbox:  {base}")
    print(f"  Memories: 1 (init)")
    print()
    print("Quick commands:")
    print("  agentazall remember --text 'something important' --title 'slug'")
    print("  agentazall recall")
    print("  agentazall recall 'search term'")
    print("  agentazall doing --set 'Working on...'")
    print("  agentazall note handoff --set 'Context for next session'")
    print("  agentazall whoami")


def _show_status(cfg):
    """Show brief status for an already-configured agent."""
    from ..finder import find_latest_file

    text = find_latest_file(cfg, f"{WHO_AM_I}/identity.txt")
    if text:
        preview = text.strip().split("\n")[0][:100]
        print(f"  Identity: {preview}")

    base = agent_base(cfg)
    total = 0
    for d in date_dirs(cfg):
        rem_dir = base / d / REMEMBER
        if rem_dir.exists():
            total += len(list(rem_dir.glob("*.txt")))
    print(f"  Memories: {total}")
