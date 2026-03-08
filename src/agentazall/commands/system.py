"""AgentAZAll commands: index, status, tree, dates, directory."""

import json
import os
import re
import smtplib
from pathlib import Path

from ..config import (
    INBOX,
    OUTBOX,
    SENT,
    VERSION,
    WHAT_AM_I_DOING,
    WHO_AM_I,
    load_config,
)
from ..finder import find_latest_file
from ..helpers import (
    agent_base,
    agent_day,
    date_dirs,
    ensure_dirs,
    today_str,
)
from ..index import build_index
from ..transport_email import EmailTransport


def cmd_index(args):
    cfg = load_config()
    d = args.date or today_str()
    if args.rebuild:
        dirs = date_dirs(cfg)
        for dd in dirs:
            build_index(cfg, dd)
        print(f"Rebuilt {len(dirs)} index files.")
        return
    ensure_dirs(cfg, d)
    idx = build_index(cfg, d)
    if idx and idx.exists():
        print(idx.read_text(encoding="utf-8"))
    else:
        print(f"No index for {d}.")


def cmd_status(args):
    cfg = load_config()
    transport = cfg.get("transport", "email")
    print(f"=== AgentAZAll v{VERSION} ===")
    print(f"  Agent: {cfg['agent_name']}")
    print(f"  Mailbox: {agent_base(cfg)}")
    print(f"  Transport: {transport}")
    print(f"  Today: {today_str()}")

    if transport in ("email", "both"):
        ec = cfg["email"]
        print(f"  Email IMAP: {ec['imap_server']}:{ec['imap_port']}")
        print(f"  Email SMTP: {ec['smtp_server']}:{ec['smtp_port']}")
    if transport in ("ftp", "both"):
        fc = cfg["ftp"]
        print(f"  FTP: {fc['host']}:{fc['port']}")

    dirs = date_dirs(cfg)
    b = agent_base(cfg)
    print(f"  Days: {len(dirs)}")
    if dirs:
        td = b / today_str()
        if td.exists():
            ic = len(list((td / INBOX).glob("*.txt"))) if (td / INBOX).exists() else 0
            sc = len(list((td / SENT).glob("*.txt"))) if (td / SENT).exists() else 0
            oc = len(list((td / OUTBOX).glob("*.txt"))) if (td / OUTBOX).exists() else 0
            print(f"  Today: inbox:{ic} sent:{sc} pending:{oc}")

    identity = find_latest_file(cfg, f"{WHO_AM_I}/identity.txt")
    if identity:
        print(f"  Identity: {identity[:80].replace(chr(10), ' ')}...")
    tasks = find_latest_file(cfg, f"{WHAT_AM_I_DOING}/tasks.txt")
    if tasks:
        print(f"  Tasks: {tasks[:80].replace(chr(10), ' ')}...")

    # connectivity
    print()
    if transport in ("email", "both"):
        try:
            et = EmailTransport(cfg)
            if et.imap_connect():
                print("  IMAP: OK")
                et.imap_disconnect()
            else:
                print("  IMAP: FAILED")
        except Exception as e:
            print(f"  IMAP: ERROR - {e}")
        try:
            ec = cfg["email"]
            s = smtplib.SMTP(ec["smtp_server"], ec["smtp_port"], timeout=5)
            s.quit()
            print("  SMTP: OK")
        except Exception as e:
            print(f"  SMTP: ERROR - {e}")
    if transport in ("ftp", "both"):
        try:
            from ..transport_ftp import FTPTransport
            ft = FTPTransport(cfg)
            ftp = ft.connect()
            if ftp:
                print("  FTP: OK")
                ftp.quit()
            else:
                print("  FTP: FAILED")
        except Exception as e:
            print(f"  FTP: ERROR - {e}")


def cmd_tree(args):
    cfg = load_config()
    d = args.date or today_str()
    dd = agent_day(cfg, d)
    if not dd.exists():
        print(f"No directory for {d}.")
        return
    print(f"=== Tree: {cfg['agent_name']} / {d} ===")
    for root, dirs, files in os.walk(str(dd)):
        level = len(Path(root).relative_to(dd).parts)
        indent = "  " * level
        print(f"{indent}{Path(root).name}/")
        for f in sorted(files):
            print(f"{indent}  {f}")


def cmd_directory(args):
    """List all known agents with their identity and current activity."""
    cfg = load_config()
    mb_root = Path(cfg["mailbox_dir"])
    if not mb_root.exists():
        print("No agents found.")
        return

    agents = []
    for agent_dir in sorted(mb_root.iterdir()):
        if not agent_dir.is_dir():
            continue
        name = agent_dir.name
        identity = ""
        doing = ""
        for d in sorted(
            (x.name for x in agent_dir.iterdir()
             if x.is_dir() and re.match(r"\d{4}-\d{2}-\d{2}$", x.name)),
            reverse=True,
        ):
            if not identity:
                id_f = agent_dir / d / WHO_AM_I / "identity.txt"
                if id_f.exists():
                    identity = id_f.read_text(encoding="utf-8", errors="replace").strip()
            if not doing:
                do_f = agent_dir / d / WHAT_AM_I_DOING / "tasks.txt"
                if do_f.exists():
                    doing = do_f.read_text(encoding="utf-8", errors="replace").strip()
            if identity and doing:
                break
        agents.append((name, identity, doing))

    if not agents:
        print("No agents found.")
        return

    if args.json:
        data = []
        for name, identity, doing in agents:
            data.append({
                "address": name,
                "identity": identity[:200] if identity else "",
                "doing": doing[:200] if doing else "",
            })
        print(json.dumps(data, indent=2))
    else:
        print(f"=== Agent Directory ({len(agents)} agents) ===\n")
        for name, identity, doing in agents:
            print(f"  {name}")
            if identity:
                print(f"    Identity: {identity[:120].replace(chr(10), ' ')}")
            if doing:
                print(f"    Doing: {doing[:120].replace(chr(10), ' ')}")
            if not identity and not doing:
                print("    (no identity/tasks set)")
            print()
