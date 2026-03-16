"""AgentAZAll commands: whoami, doing, address — agent identity and task tracking."""

from ..config import WHAT_AM_I_DOING, WHO_AM_I, load_config
from ..finder import find_latest_file
from ..helpers import agent_day, ensure_dirs, require_identity, today_str
from ..index import build_index


def _get_identity(cfg):
    """Return identity string or empty string."""
    text = find_latest_file(cfg, f"{WHO_AM_I}/identity.txt")
    return text.strip() if text else ""


def _get_doing(cfg):
    """Return current task string or empty string."""
    text = find_latest_file(cfg, f"{WHAT_AM_I_DOING}/tasks.txt")
    return text.strip() if text else ""


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


def cmd_address(args):
    """Show this agent's public address — the string others use to send messages."""
    cfg = load_config()
    agent = cfg["agent_name"]
    if getattr(args, "quiet", False):
        # Machine-readable: just the address, nothing else
        print(agent)
        return
    print(f"My address: {agent}")
    print()
    print("Share this with other agents or humans so they can message you:")
    print(f"  agentazall send --to {agent} -s \"Subject\" -b \"Body\"")


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
