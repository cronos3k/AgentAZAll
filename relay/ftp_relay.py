#!/usr/bin/env python3
"""AgentAZAll FTP Relay — move messages from outbox/ to recipient inbox/.

Run via cron every minute. Parses To: header from message files to determine
recipient, then copies the message to the recipient's inbox.
"""

import os
import re
import shutil
import time
from pathlib import Path

AGENTS_ROOT = Path("/var/ftp/agents")
LOG_PATH = Path("/var/log/agentazall-ftp-relay.log")


def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_PATH, "a") as f:
        f.write(f"{ts} {msg}\n")


def relay_messages():
    if not AGENTS_ROOT.exists():
        return

    moved = 0
    for agent_dir in AGENTS_ROOT.iterdir():
        if not agent_dir.is_dir():
            continue

        outbox = agent_dir / "outbox"
        if not outbox.exists():
            continue

        for msg_file in outbox.glob("*.txt"):
            try:
                text = msg_file.read_text(encoding="utf-8")
                to_match = re.search(r"^To:\s*(.+)$", text, re.MULTILINE)
                if not to_match:
                    continue

                recipients = [r.strip() for r in to_match.group(1).split(",")]
                delivered = False

                for rcpt in recipients:
                    # Extract username part (before @)
                    rcpt_name = rcpt.split("@")[0] if "@" in rcpt else rcpt
                    rcpt_inbox = AGENTS_ROOT / rcpt_name / "inbox"

                    if rcpt_inbox.exists():
                        shutil.copy2(str(msg_file), str(rcpt_inbox / msg_file.name))
                        delivered = True
                        log(f"RELAY {agent_dir.name} -> {rcpt_name}: {msg_file.name}")

                if delivered:
                    # Move to sent
                    sent = agent_dir / "sent"
                    sent.mkdir(exist_ok=True)
                    shutil.move(str(msg_file), str(sent / msg_file.name))
                    moved += 1

            except Exception as e:
                log(f"ERROR {agent_dir.name}/{msg_file.name}: {e}")

    if moved > 0:
        log(f"Relayed {moved} messages")


if __name__ == "__main__":
    relay_messages()
