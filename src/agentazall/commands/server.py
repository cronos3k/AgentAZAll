"""AgentAZAll commands: daemon, server, export, onboard."""

import logging
import logging.handlers
import os
import subprocess
import sys
import zipfile
from pathlib import Path

from ..config import LOG_FMT, load_config, resolve_config_path
from ..daemon import Daemon
from ..helpers import today_str


def cmd_daemon(args):
    cfg = load_config()
    log = logging.getLogger("agentazall")
    lf = cfg.get("log_file")
    if lf:
        Path(lf).parent.mkdir(parents=True, exist_ok=True)
        if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in log.handlers):
            fh = logging.handlers.RotatingFileHandler(
                lf, maxBytes=5 * 1024 * 1024, backupCount=3)
            fh.setFormatter(logging.Formatter(LOG_FMT, datefmt="%H:%M:%S"))
            log.addHandler(fh)
    Daemon(cfg).run(once=args.once)


def cmd_export(args):
    """Export the entire project state to a ZIP file."""
    out = args.output or f"agentazall_export_{today_str()}.zip"
    out_path = Path(out).resolve()

    # Determine the project root (where config lives)
    config_path = Path(resolve_config_path())
    project_root = config_path.parent

    include_files = [
        "config.json", "AGENT.md",
    ]

    count = 0
    with zipfile.ZipFile(str(out_path), "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in include_files:
            fp = project_root / fname
            if fp.exists():
                zf.write(str(fp), fname)
                count += 1

        # .agent directory (agent configuration)
        agent_dir = project_root / ".agent"
        if agent_dir.exists():
            for root, dirs, files in os.walk(str(agent_dir)):
                for f in files:
                    full = Path(root) / f
                    arcname = str(full.relative_to(project_root))
                    zf.write(str(full), arcname)
                    count += 1

        # data directory
        data_dir = project_root / "data"
        if data_dir.exists():
            for root, dirs, files in os.walk(str(data_dir)):
                for f in files:
                    full = Path(root) / f
                    arcname = str(full.relative_to(project_root))
                    zf.write(str(full), arcname)
                    count += 1

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"Export complete: {out_path}")
    print(f"  Files: {count}")
    print(f"  Size: {size_mb:.1f} MB")


def cmd_onboard(args):
    """Print the onboarding document for a new agent."""
    # Try package-bundled onboarding first, then project-local
    candidates = [
        Path(__file__).parent.parent.parent.parent / "onboarding" / "ONBOARDING.md",
        Path(resolve_config_path()).parent / "onboarding" / "ONBOARDING.md",
    ]
    for p in candidates:
        if p.exists():
            print(p.read_text(encoding="utf-8"))
            return
    print("ERROR: Onboarding document not found.")
    print("Expected at: onboarding/ONBOARDING.md")
    sys.exit(1)


def cmd_server(args):
    """Start local email, FTP, and/or AgentTalk servers."""
    procs = []

    if args.email or args.all:
        print("Starting email server (SMTP/IMAP/POP3)...")
        try:
            p = subprocess.Popen(
                [sys.executable, "-m", "agentazall.email_server"],
            )
            procs.append(p)
        except Exception as e:
            print(f"ERROR: Could not start email server: {e}")

    if args.ftp or args.all:
        print("Starting FTP server...")
        try:
            p = subprocess.Popen(
                [sys.executable, "-m", "agentazall.ftp_server"],
            )
            procs.append(p)
        except Exception as e:
            print(f"ERROR: Could not start FTP server: {e}")

    if getattr(args, "agenttalk", False) or args.all:
        print("Starting AgentTalk server (HTTPS API)...")
        try:
            p = subprocess.Popen(
                [sys.executable, "-m", "agentazall.agenttalk_server"],
            )
            procs.append(p)
        except Exception as e:
            print(f"ERROR: Could not start AgentTalk server: {e}")

    if not procs:
        print("Specify --email, --ftp, --agenttalk, or --all")
        return
    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        for p in procs:
            p.terminate()
