#!/usr/bin/env python3
"""AgentAZAll Relay — enforce FTP quotas (ephemeral tmpfs storage)."""

import os
import sqlite3
import time
from pathlib import Path

FTP_ROOT = Path("/var/ftp/agents")
DB_PATH = "/var/lib/agentazall/registry.db"
DEFAULT_QUOTA = 20 * 1024 * 1024  # 20 MB (ephemeral relay)


def dir_size(path):
    total = 0
    for dirpath, _, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total


def check_quotas():
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    db = sqlite3.connect(DB_PATH)
    violations = 0

    for agent_dir in FTP_ROOT.iterdir():
        if not agent_dir.is_dir():
            continue

        usage = dir_size(agent_dir)
        quota = DEFAULT_QUOTA

        row = db.execute(
            "SELECT ftp_quota_bytes FROM accounts WHERE username=?",
            (agent_dir.name,),
        ).fetchone()
        if row:
            quota = row[0]

        outbox = agent_dir / "outbox"
        if usage > quota:
            # Make outbox read-only to prevent further uploads
            if outbox.exists():
                os.chmod(str(outbox), 0o555)
            violations += 1
            print(f"{ts} QUOTA EXCEEDED: {agent_dir.name} "
                  f"using {usage // 1024}KB / {quota // 1024}KB")
        else:
            # Ensure outbox is writable
            if outbox.exists():
                os.chmod(str(outbox), 0o775)

    if violations:
        print(f"{ts} {violations} agents over FTP quota")

    db.close()


if __name__ == "__main__":
    check_quotas()
