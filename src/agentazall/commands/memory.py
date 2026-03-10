"""AgentAZAll commands: remember, recall — persistent memory system."""

from datetime import datetime

from ..config import REMEMBER, REMEMBER_INDEX, load_config
from ..helpers import (
    agent_base,
    agent_day,
    can_read_agent_memories,
    date_dirs,
    ensure_dirs,
    require_identity,
    sanitize,
    today_str,
)
from ..index import build_index, build_remember_index


def _recall_all(cfg):
    """Print the sparse memory index (used by startup command)."""
    b = agent_base(cfg)
    idx_path = b / REMEMBER_INDEX
    build_remember_index(cfg)
    if idx_path.exists():
        print(idx_path.read_text(encoding="utf-8"))
    else:
        print("No memories stored yet.")


def cmd_remember(args):
    """Store a memory the agent does not want to forget."""
    cfg = load_config()
    require_identity(cfg)
    d = today_str()
    ensure_dirs(cfg, d)
    rem_dir = agent_day(cfg, d) / REMEMBER

    if args.text:
        ts = datetime.now().strftime("%H%M%S")
        title = sanitize(args.title) if args.title else ts
        fname = f"{title}.txt"
        fpath = rem_dir / fname
        if fpath.exists():
            old = fpath.read_text(encoding="utf-8")
            fpath.write_text(old + "\n" + args.text, encoding="utf-8")
        else:
            fpath.write_text(args.text, encoding="utf-8")
        build_index(cfg, d)
        build_remember_index(cfg)
        print(f"Memory stored: {fpath}")
        print(f"  Title: {title}")
    elif args.list:
        if not rem_dir.exists() or not list(rem_dir.glob("*.txt")):
            print(f"No memories for {d}.")
            return
        print(f"=== Memories | {d} ===")
        for f in sorted(rem_dir.glob("*.txt")):
            text = f.read_text(encoding="utf-8", errors="replace").strip()
            first = text.split("\n")[0][:100] if text else ""
            print(f"  {f.stem}: {first}")
    else:
        print("Use --text to store a memory, or --list to show today's memories.")
        print("Use 'recall' command to search across all memories.")


def cmd_recall(args):
    """Recall memories — show the sparse cross-day index, optionally filtered."""
    cfg = load_config()

    if hasattr(args, 'agent') and args.agent:
        target = args.agent
        if "@" not in target:
            target = f"{target}@localhost"
        if not can_read_agent_memories(cfg, target):
            print(f"Access denied: {target} has not enabled memory sharing.")
            print("Agents control who can read their memories via allow_memory_sharing.")
            return
        read_cfg = dict(cfg)
        read_cfg["agent_name"] = target
    else:
        read_cfg = cfg

    b = agent_base(read_cfg)
    idx_path = b / REMEMBER_INDEX

    build_remember_index(read_cfg)

    if not idx_path.exists():
        print("No memories stored yet.")
        return

    if args.query:
        q = args.query.lower()
        results = []
        for d in sorted(date_dirs(read_cfg), reverse=True):
            rem_dir = b / d / REMEMBER
            if not rem_dir.exists():
                continue
            for f in sorted(rem_dir.glob("*.txt")):
                text = f.read_text(encoding="utf-8", errors="replace")
                if q in text.lower() or q in f.stem.lower():
                    results.append((d, f.stem, text.strip(), f))

        if not results:
            print(f"No memories matching '{args.query}'.")
            return

        agent_label = read_cfg["agent_name"]
        print(f"=== Recall ({agent_label}): '{args.query}' ({len(results)} found) ===\n")
        for d, title, text, fpath in results:
            print(f"[{d}] {title}")
            for ln in text.split("\n"):
                print(f"  {ln}")
            print(f"  Path: {fpath}")
            print()
    else:
        print(idx_path.read_text(encoding="utf-8"))
