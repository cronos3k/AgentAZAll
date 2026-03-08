"""AgentoAll commands: note, notes — named notes management."""

from ..config import NOTES, load_config
from ..finder import find_latest_file
from ..helpers import (
    agent_day,
    ensure_dirs,
    require_identity,
    sanitize,
    today_str,
)
from ..index import build_index


def cmd_note(args):
    cfg = load_config()
    if args.set:
        require_identity(cfg)
    d = today_str()
    ensure_dirs(cfg, d)
    name = sanitize(args.name)
    f = agent_day(cfg, d) / NOTES / f"{name}.txt"

    if args.set:
        f.write_text(args.set, encoding="utf-8")
        build_index(cfg, d)
        print(f"Note '{name}' saved: {f}")
    elif args.append:
        old = f.read_text(encoding="utf-8") if f.exists() else ""
        f.write_text((old + "\n" + args.append).lstrip("\n"), encoding="utf-8")
        build_index(cfg, d)
        print(f"Note '{name}' appended: {f}")
    else:
        if f.exists():
            print(f.read_text(encoding="utf-8"))
        else:
            text = find_latest_file(cfg, f"{NOTES}/{name}.txt")
            if text:
                print(text)
            else:
                print(f"Note '{name}' not found.")


def cmd_notes(args):
    cfg = load_config()
    d = args.date or today_str()
    nd = agent_day(cfg, d) / NOTES
    if not nd.exists() or not list(nd.glob("*.txt")):
        print(f"No notes for {d}.")
        return
    print(f"=== Notes | {d} ===")
    for f in sorted(nd.glob("*.txt")):
        print(f"  {f.stem} ({f.stat().st_size}B) | {f}")
