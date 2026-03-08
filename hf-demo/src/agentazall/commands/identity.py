"""AgentAZAll commands: whoami, doing — agent identity and task tracking."""

from ..config import WHAT_AM_I_DOING, WHO_AM_I, load_config
from ..finder import find_latest_file
from ..helpers import agent_day, ensure_dirs, require_identity, today_str
from ..index import build_index


def cmd_whoami(args):
    cfg = load_config()
    if args.set:
        require_identity(cfg)
    d = today_str()
    ensure_dirs(cfg, d)
    f = agent_day(cfg, d) / WHO_AM_I / "identity.txt"
    if args.set:
        f.write_text(args.set, encoding="utf-8")
        build_index(cfg, d)
        print(f"Identity updated: {f}")
    else:
        text = find_latest_file(cfg, f"{WHO_AM_I}/identity.txt")
        if text:
            print(text)
        else:
            print("No identity set. Use: agentazall whoami --set 'I am...'")


def cmd_doing(args):
    cfg = load_config()
    if args.set:
        require_identity(cfg)
    d = today_str()
    ensure_dirs(cfg, d)
    f = agent_day(cfg, d) / WHAT_AM_I_DOING / "tasks.txt"
    if args.set:
        f.write_text(args.set, encoding="utf-8")
        build_index(cfg, d)
        print(f"Tasks updated: {f}")
    elif args.append:
        old = f.read_text(encoding="utf-8") if f.exists() else ""
        f.write_text((old + "\n" + args.append).lstrip("\n"), encoding="utf-8")
        build_index(cfg, d)
        print(f"Task appended: {f}")
    else:
        text = find_latest_file(cfg, f"{WHAT_AM_I_DOING}/tasks.txt")
        if text:
            print(text)
        else:
            print("No tasks set. Use: agentazall doing --set 'Working on...'")
