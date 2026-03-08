#!/usr/bin/env python3
"""AgentAZAll Relay — purge messages older than 48 hours.

Privacy-by-design: messages live in RAM (tmpfs) and are ephemeral.
This cron job ensures nothing lingers beyond the TTL even if POP3
download didn't clean it up.

Run via cron every hour.
"""

import os
import time
from pathlib import Path

MAIL_ROOT = Path("/var/mail/vhosts/agentazall.ai")
FTP_ROOT = Path("/var/ftp/agents")
TTL_SECONDS = 48 * 3600  # 48 hours


def purge_old_files(root, label):
    """Delete files older than TTL_SECONDS under root."""
    now = time.time()
    cutoff = now - TTL_SECONDS
    removed = 0

    if not root.exists():
        return 0

    for dirpath, _, filenames in os.walk(root):
        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            try:
                mtime = os.path.getmtime(fpath)
                if mtime < cutoff:
                    os.unlink(fpath)
                    removed += 1
            except OSError:
                pass

    return removed


def main():
    ts = time.strftime("%Y-%m-%d %H:%M:%S")

    mail_purged = purge_old_files(MAIL_ROOT, "mail")
    ftp_purged = purge_old_files(FTP_ROOT, "ftp")

    total = mail_purged + ftp_purged
    if total > 0:
        print(f"{ts} TTL purge: {mail_purged} mail + {ftp_purged} ftp = {total} files removed")
    else:
        print(f"{ts} TTL purge: nothing to clean")


if __name__ == "__main__":
    main()
