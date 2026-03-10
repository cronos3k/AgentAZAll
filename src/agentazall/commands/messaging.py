"""AgentAZAll commands: inbox, read, send, reply, search."""

import logging
import shutil
import sys
from pathlib import Path

from ..config import INBOX, OUTBOX, SENT, load_config
from ..finder import find_message
from ..helpers import (
    agent_base,
    agent_day,
    date_dirs,
    ensure_dirs,
    require_identity,
    today_str,
)
from ..index import build_index
from ..messages import format_message, parse_message

log = logging.getLogger("agentazall")


def _quick_sync(cfg):
    """Run one daemon cycle (send outbox + fetch inbox) silently.

    Called automatically by inbox/send so agents never need to remember
    to run ``daemon --once`` separately.
    """
    try:
        from ..daemon import Daemon
        d = Daemon(cfg)
        d._cycle()
    except Exception as exc:
        # Never let sync failures block local inbox/send
        log.debug("quick-sync: %s", exc)


def _print_inbox(cfg, d):
    inbox_dir = agent_day(cfg, d) / INBOX
    if not inbox_dir.exists() or not list(inbox_dir.glob("*.txt")):
        print(f"No messages for {d}.")
        return
    files = sorted(inbox_dir.glob("*.txt"))
    new_count = 0
    print(f"\n=== INBOX {cfg['agent_name']} | {d} ===\n")
    for i, f in enumerate(files, 1):
        h, _ = parse_message(f)
        if not h:
            continue
        st = h.get("Status", "?").upper()
        if st == "NEW":
            new_count += 1
        att = " [ATTACH]" if "Attachments" in h else ""
        print(f"[{i}] [{st}]{att}")
        print(f"    From: {h.get('From', '?')}")
        print(f"    Subject: {h.get('Subject', '(no subject)')}")
        print(f"    Date: {h.get('Date', '?')}")
        print(f"    ID: {h.get('Message-ID', f.stem)}")
        print(f"    Path: {f}")
        print()
    print(f"Total: {len(files)} messages ({new_count} new)")


def cmd_inbox(args):
    cfg = load_config()
    if not getattr(args, "offline", False):
        _quick_sync(cfg)
    if args.all:
        for d in date_dirs(cfg):
            _print_inbox(cfg, d)
        return
    d = args.date or today_str()
    _print_inbox(cfg, d)


def cmd_read(args):
    cfg = load_config()
    path = find_message(cfg, args.message_id, args.date)
    if not path:
        print(f"ERROR: Message '{args.message_id}' not found.")
        sys.exit(1)
    headers, body = parse_message(path)
    if not headers:
        print(f"ERROR: Could not parse {path}")
        sys.exit(1)

    if headers.get("Status", "").lower() == "new":
        content = path.read_text(encoding="utf-8")
        content = content.replace("Status: new", "Status: read", 1)
        path.write_text(content, encoding="utf-8")
        build_index(cfg, path.parent.parent.name)

    print(f"=== MESSAGE {headers.get('Message-ID', args.message_id)} ===")
    for k, v in headers.items():
        print(f"{k}: {v}")
    print("\n---")
    print(body)

    att_dir = path.parent / path.stem
    if att_dir.is_dir():
        print("\n=== ATTACHMENTS ===")
        for af in sorted(att_dir.iterdir()):
            print(f"  {af.name} ({af.stat().st_size} bytes)")
            print(f"  Path: {af}")


def cmd_send(args):
    cfg = load_config()
    require_identity(cfg)
    d = today_str()
    ensure_dirs(cfg, d)
    from_a = cfg["agent_name"]
    to_a = args.to
    subject = args.subject

    if args.body:
        body = args.body
    elif args.body_file:
        body = Path(args.body_file).read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
        body = sys.stdin.read()
    else:
        print("ERROR: Provide --body, --body-file, or pipe to stdin.")
        sys.exit(1)

    attachments = args.attach or []
    content, msg_id = format_message(from_a, to_a, subject, body, attachments=attachments)
    outbox = agent_day(cfg, d) / OUTBOX
    fpath = outbox / f"{msg_id}.txt"

    if attachments:
        adir = outbox / msg_id
        adir.mkdir(exist_ok=True)
        for ap in attachments:
            src = Path(ap)
            if src.exists():
                shutil.copy2(str(src), str(adir / src.name))
            else:
                print(f"  WARNING: {ap} not found")

    tmp = fpath.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.rename(fpath)

    build_index(cfg, d)
    print("Message queued.")
    print(f"  ID: {msg_id}")
    print(f"  To: {to_a}")
    print(f"  Subject: {subject}")
    if attachments:
        print(f"  Attachments: {', '.join(Path(a).name for a in attachments)}")
    print(f"  Path: {fpath}")

    # Deliver immediately (don't make the user run daemon --once)
    _quick_sync(cfg)
    print("  Delivered.")


def cmd_reply(args):
    cfg = load_config()
    require_identity(cfg)
    path = find_message(cfg, args.message_id)
    if not path:
        print(f"ERROR: Message '{args.message_id}' not found.")
        sys.exit(1)
    headers, orig_body = parse_message(path)
    if not headers or not headers.get("From"):
        print("ERROR: Cannot determine recipient.")
        sys.exit(1)

    to_a = headers["From"]
    subject = headers.get("Subject", "")
    if not subject.startswith("Re: "):
        subject = f"Re: {subject}"

    if args.body:
        body = args.body
    elif not sys.stdin.isatty():
        body = sys.stdin.read()
    else:
        print("ERROR: Provide --body or pipe to stdin.")
        sys.exit(1)

    body += f"\n\n--- Original from {headers.get('From', '?')} ({headers.get('Date', '?')}) ---\n{orig_body}"

    d = today_str()
    ensure_dirs(cfg, d)
    content, new_id = format_message(cfg["agent_name"], to_a, subject, body)
    outbox = agent_day(cfg, d) / OUTBOX
    fpath = outbox / f"{new_id}.txt"
    fpath.write_text(content, encoding="utf-8")
    build_index(cfg, d)
    print("Reply queued.")
    print(f"  ID: {new_id}")
    print(f"  To: {to_a}")
    print(f"  Subject: {subject}")

    # Deliver immediately
    _quick_sync(cfg)
    print("  Delivered.")


def cmd_dates(args):
    cfg = load_config()
    dirs = date_dirs(cfg)
    if not dirs:
        print("No dates yet.")
        return
    print(f"=== Dates for {cfg['agent_name']} ===")
    b = agent_base(cfg)
    for d in dirs:
        dd = b / d
        ic = len(list((dd / INBOX).glob("*.txt"))) if (dd / INBOX).exists() else 0
        sc = len(list((dd / SENT).glob("*.txt"))) if (dd / SENT).exists() else 0
        oc = len(list((dd / OUTBOX).glob("*.txt"))) if (dd / OUTBOX).exists() else 0
        nc = len(list((dd / "notes").glob("*.txt"))) if (dd / "notes").exists() else 0
        print(f"  {d} | inbox:{ic} sent:{sc} pending:{oc} notes:{nc}")


def cmd_search(args):
    cfg = load_config()
    q = args.query.lower()
    b = agent_base(cfg)
    if not b.exists():
        print("No messages to search.")
        return
    results = []
    for d in date_dirs(cfg):
        for folder in (INBOX, SENT):
            fp = b / d / folder
            if not fp.exists():
                continue
            for f in fp.glob("*.txt"):
                h, body = parse_message(f)
                if not h:
                    continue
                searchable = " ".join(h.values()).lower() + " " + (body or "").lower()
                if q in searchable:
                    results.append((d, folder, h, f))
    if not results:
        print(f"No results for '{args.query}'.")
        return
    print(f"=== Search: '{args.query}' ({len(results)} found) ===")
    for d, folder, h, f in results:
        direction = f"From: {h.get('From', '?')}" if folder == INBOX else f"To: {h.get('To', '?')}"
        print(f"  [{d}] [{folder.upper()}] {direction} | Subject: {h.get('Subject', '?')} | ID: {h.get('Message-ID', f.stem)}")
        print(f"    Path: {f}")
