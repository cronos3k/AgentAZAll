"""AgentAZAll command: setup — configure a new agent."""

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import List

from ..config import DEFAULT_CONFIG, SKILLS, TOOLS, save_config
from ..helpers import (
    agent_base,
    ensure_dirs,
    now_str,
    shared_dir,
)
from ..index import build_index


def _list_existing_agents(mb_root: Path) -> List[str]:
    """Return list of agent names that already have mailbox directories."""
    if not mb_root.exists():
        return []
    return [d.name for d in mb_root.iterdir() if d.is_dir()]


def cmd_setup(args):
    agent = args.agent
    if not agent:
        print("ERROR: --agent required")
        sys.exit(1)

    if "@" not in agent:
        agent = f"{agent}@localhost"

    cfg_tmp = dict(DEFAULT_CONFIG)
    mb_root = Path(cfg_tmp["mailbox_dir"])
    existing = _list_existing_agents(mb_root)
    if agent in existing:
        print(f"Hey, '{agent}' is already here! That name is taken.")
        print("Pick a different name. These are already registered:")
        for e in sorted(existing):
            print(f"  - {e}")
        sys.exit(1)

    agent_key = hashlib.sha256(
        f"{agent}:{os.urandom(32).hex()}:{time.time()}".encode()
    ).hexdigest()[:32]

    share_memories = getattr(args, 'share_memories', False)

    cfg = dict(DEFAULT_CONFIG)
    cfg["agent_name"] = agent
    cfg["agent_key"] = agent_key
    cfg["allow_memory_sharing"] = share_memories
    cfg["email"]["username"] = agent
    if args.transport:
        cfg["transport"] = args.transport
    save_config(cfg)
    ensure_dirs(cfg)

    sd = shared_dir(cfg)
    (sd / SKILLS).mkdir(parents=True, exist_ok=True)
    (sd / TOOLS).mkdir(parents=True, exist_ok=True)

    key_file = agent_base(cfg) / ".agent_key"
    key_file.write_text(json.dumps({
        "agent": agent,
        "key": agent_key,
        "created": now_str(),
        "allow_memory_sharing": share_memories,
    }, indent=2), encoding="utf-8")

    build_index(cfg)
    print("Setup complete.")
    print(f"  Agent: {agent}")
    print(f"  Key: {agent_key[:8]}... (stored in config)")
    print(f"  Transport: {cfg['transport']}")
    print(f"  Mailbox: {agent_base(cfg)}")
