#!/usr/bin/env python3
"""AgentAZAll Relay — cleanup inactive accounts (>7 days).

Deactivates accounts with no activity for 7 days.
Also removes their entries from Dovecot, Postfix, and vsftpd config files.
Messages on tmpfs are ephemeral anyway; this cleans up the auth records.
"""

import shutil
import sqlite3
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

DOMAIN = "agentazall.ai"
DB_PATH = "/var/lib/agentazall/registry.db"
DOVECOT_USERS = Path("/etc/dovecot/users")
VMAILBOX_MAP = Path("/etc/postfix/vmailbox")
VSFTPD_USERS = Path("/etc/vsftpd/virtual_users")
MAIL_ROOT = Path(f"/var/mail/vhosts/{DOMAIN}")
FTP_ROOT = Path("/var/ftp/agents")
INACTIVE_DAYS = 7


def remove_from_file(filepath, pattern):
    """Remove lines containing pattern from a config file."""
    if not filepath.exists():
        return
    lines = filepath.read_text().splitlines()
    filtered = [ln for ln in lines if pattern not in ln]
    if len(filtered) < len(lines):
        filepath.write_text("\n".join(filtered) + "\n" if filtered else "")


def cleanup():
    cutoff = (datetime.utcnow() - timedelta(days=INACTIVE_DAYS)).isoformat()
    ts = time.strftime("%Y-%m-%d %H:%M:%S")

    db = sqlite3.connect(DB_PATH)
    inactive = db.execute(
        "SELECT username, email_address FROM accounts "
        "WHERE is_active=1 AND (last_activity IS NULL OR last_activity < ?) "
        "AND created_at < ?",
        (cutoff, cutoff),
    ).fetchall()

    for username, email_addr in inactive:
        # Remove mail directory (on tmpfs — fast)
        mail_dir = MAIL_ROOT / username
        if mail_dir.exists():
            shutil.rmtree(str(mail_dir))

        # Remove FTP directory (on tmpfs — fast)
        ftp_dir = FTP_ROOT / username
        if ftp_dir.exists():
            shutil.rmtree(str(ftp_dir))

        # Remove per-user vsftpd config
        user_conf = Path(f"/etc/vsftpd/user_conf/{username}")
        if user_conf.exists():
            user_conf.unlink()

        # Remove from Dovecot users file
        remove_from_file(DOVECOT_USERS, email_addr)

        # Remove from Postfix vmailbox
        remove_from_file(VMAILBOX_MAP, email_addr)

        # Remove from vsftpd virtual users
        remove_from_file(VSFTPD_USERS, f"{username}:")

        # Mark inactive in DB
        db.execute("UPDATE accounts SET is_active=0 WHERE username=?", (username,))
        print(f"{ts} DEACTIVATED: {username} (inactive >{INACTIVE_DAYS} days)")

    db.commit()

    if inactive:
        # Rebuild postfix hash map
        subprocess.run(["postmap", str(VMAILBOX_MAP)], check=False)
        print(f"{ts} Cleaned up {len(inactive)} inactive accounts")
    else:
        print(f"{ts} No inactive accounts to clean up")

    db.close()


if __name__ == "__main__":
    cleanup()
