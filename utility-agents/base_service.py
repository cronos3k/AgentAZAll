#!/usr/bin/env python3
"""
Base class for AgentAZAll utility service agents.

Provides the shared infrastructure that every non-LLM service agent needs:
- Inbox polling with deduplication
- Ticketing and queue position tracking
- Instant ACK messages with ETA
- Reply sending (text and binary attachments)
- Rate limiting
- Logging

Subclasses override `handle_request()` to implement their service logic.
"""
import sys
import os
import time
import logging
import subprocess
import shutil
from pathlib import Path
from datetime import datetime

# Add parent for agentazall imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class ServiceAgent:
    """Base class for utility service agents on the AgentAZAll network."""

    def __init__(self, agent_name, work_dir, poll_interval=10,
                 rate_limit_hour=30, rate_limit_day=200):
        self.agent_name = agent_name
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.poll_interval = poll_interval
        self.rate_limit_hour = rate_limit_hour
        self.rate_limit_day = rate_limit_day

        # Ticketing
        self._ticket_counter = 0
        self._avg_process_time = 2.0   # seconds, updated after each job
        self._process_count = 0
        self._pending_count = 0

        # Deduplication
        self.processed_ids = set()
        self._load_processed_ids()

        # Rate limit tracking: {agent_id: [timestamp, ...]}
        self._rate_log = {}

        # Logging
        log_dir = self.work_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log = logging.getLogger(f"service.{agent_name}")
        self.log.setLevel(logging.INFO)
        if not self.log.handlers:
            fmt = logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            sh = logging.StreamHandler()
            sh.setFormatter(fmt)
            self.log.addHandler(sh)
            fh = logging.FileHandler(log_dir / f"{agent_name}.log")
            fh.setFormatter(fmt)
            self.log.addHandler(fh)

    # ── Processed IDs persistence ───────────────────────────────

    def _load_processed_ids(self):
        tracker = self.work_dir / ".processed_ids"
        if tracker.exists():
            self.processed_ids = set(
                tracker.read_text(encoding="utf-8").strip().split("\n")
            )
        self.processed_ids.discard("")

    def _save_processed_id(self, msg_id):
        self.processed_ids.add(msg_id)
        tracker = self.work_dir / ".processed_ids"
        tracker.write_text(
            "\n".join(sorted(self.processed_ids)), encoding="utf-8"
        )

    # ── AgentAZAll CLI wrapper ──────────────────────────────────

    def _run_az(self, *args, timeout=30):
        """Run an agentazall CLI command in the agent's work directory."""
        cmd = [sys.executable, "-m", "agentazall"] + list(args)
        env = os.environ.copy()
        env["AGENTAZALL_ROOT"] = str(self.work_dir)
        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout, env=env, cwd=str(self.work_dir),
            )
            return r.stdout, r.stderr, r.returncode
        except subprocess.TimeoutExpired:
            self.log.warning(f"CLI timed out: {' '.join(args[:3])}")
            return "", "timeout", -1

    # ── Sync ────────────────────────────────────────────────────

    def sync(self):
        """Run daemon --once to push outbox and pull inbox."""
        stdout, stderr, rc = self._run_az("daemon", "--once")
        if rc != 0 and stderr and "timeout" not in stderr:
            self.log.warning(f"Sync warning: {stderr[:200]}")

    # ── Inbox reading ───────────────────────────────────────────

    def get_inbox_messages(self):
        """Read all new, unprocessed messages from today's inbox."""
        from agentazall.config import load_config
        from agentazall.helpers import agent_day, today_str
        from agentazall.messages import parse_message, parse_headers_only

        config_path = self.work_dir / "config.json"
        if not config_path.exists():
            self.log.error(f"No config.json at {config_path}")
            return []

        azcfg = load_config(config_path)
        messages = []

        inbox_dir = agent_day(azcfg, today_str()) / "inbox"
        if not inbox_dir.exists():
            return []

        for msg_file in sorted(inbox_dir.glob("*.txt")):
            headers = parse_headers_only(msg_file)
            if not headers:
                continue

            msg_id = headers.get("Message-ID", msg_file.stem)
            if msg_id in self.processed_ids:
                continue
            if headers.get("Status", "").lower() == "read":
                continue

            full_headers, body = parse_message(msg_file)
            if not full_headers:
                continue

            # Check for binary attachments
            att_dir = msg_file.parent / msg_file.stem
            attachments = []
            if att_dir.is_dir():
                for af in att_dir.iterdir():
                    attachments.append({
                        "name": af.name,
                        "path": af,
                        "data": af.read_bytes(),
                    })

            messages.append({
                "id": msg_id,
                "from": full_headers.get("From", "unknown"),
                "to": full_headers.get("To", ""),
                "subject": full_headers.get("Subject", ""),
                "body": body or "",
                "file": msg_file,
                "date": full_headers.get("Date", ""),
                "attachments": attachments,
            })

        return messages

    # ── Sending replies ─────────────────────────────────────────

    def send_reply(self, to_agent, subject, body, attachments=None):
        """Send a text reply, optionally with file attachments.

        Args:
            to_agent: recipient address
            subject: reply subject
            body: reply body text
            attachments: list of file paths (str or Path) for binary attachments
        """
        if not subject.startswith("Re: "):
            subject = f"Re: {subject}"

        cmd_args = [
            "send", "--to", to_agent, "-s", subject, "-b", body,
        ]
        if attachments:
            for att_path in attachments:
                cmd_args.extend(["--attach", str(att_path)])

        stdout, stderr, rc = self._run_az(*cmd_args, timeout=30)

        if rc == 0:
            self.log.info(f"Reply sent to {to_agent}: {subject[:50]}")
        else:
            self.log.error(f"Reply failed to {to_agent}: {stderr[:200]}")
        return rc == 0

    # ── Rate limiting ───────────────────────────────────────────

    def _check_rate_limit(self, agent_id):
        """Returns (allowed: bool, message: str)."""
        now = time.time()
        timestamps = self._rate_log.get(agent_id, [])
        # Prune old entries
        timestamps = [t for t in timestamps if now - t < 86400]
        self._rate_log[agent_id] = timestamps

        hour_count = sum(1 for t in timestamps if now - t < 3600)
        day_count = len(timestamps)

        if hour_count >= self.rate_limit_hour:
            return False, (
                f"Rate limit reached ({self.rate_limit_hour}/hour). "
                f"Please try again later."
            )
        if day_count >= self.rate_limit_day:
            return False, (
                f"Daily limit reached ({self.rate_limit_day}/day). "
                f"Please try again tomorrow."
            )
        return True, ""

    def _record_rate(self, agent_id):
        if agent_id not in self._rate_log:
            self._rate_log[agent_id] = []
        self._rate_log[agent_id].append(time.time())

    # ── Ticketing ───────────────────────────────────────────────

    def _send_ack(self, to_agent, subject, queue_pos):
        """Send instant acknowledgment with ticket number and ETA."""
        self._ticket_counter += 1
        ticket = self._ticket_counter
        eta_sec = max(2, int(queue_pos * self._avg_process_time
                              + self._avg_process_time))
        if eta_sec < 60:
            eta_str = f"~{eta_sec} seconds"
        else:
            eta_str = f"~{eta_sec // 60} minute{'s' if eta_sec >= 120 else ''}"

        ack = (
            f"Request received and queued.\n"
            f"  Ticket:   #{ticket}\n"
            f"  Position: {queue_pos + 1} in queue\n"
            f"  Est. wait: {eta_str}\n\n"
            f"Processing now..."
        )
        self.send_reply(to_agent, f"Ack: {subject}", ack)
        self.sync()  # push ack immediately
        return ticket

    def _update_avg_time(self, elapsed):
        """Update running average processing time."""
        self._process_count += 1
        n = self._process_count
        self._avg_process_time = (
            self._avg_process_time * (n - 1) + elapsed
        ) / n

    # ── Mark as read ────────────────────────────────────────────

    def _mark_read(self, msg_file):
        try:
            content = msg_file.read_text(encoding="utf-8")
            content = content.replace("Status: new", "Status: read", 1)
            msg_file.write_text(content, encoding="utf-8")
        except Exception as e:
            self.log.warning(f"Could not mark read: {e}")

    # ── Temp directory for output files ─────────────────────────

    def _tmp_dir(self):
        """Return a temp directory inside work_dir (never user dirs)."""
        d = self.work_dir / "tmp"
        d.mkdir(exist_ok=True)
        return d

    # ── Abstract method ─────────────────────────────────────────

    def handle_request(self, msg):
        """Process a single request. Override in subclass.

        Args:
            msg: dict with keys: id, from, to, subject, body, file,
                 date, attachments (list of {name, path, data})

        Returns:
            dict with:
                body: str          - reply text
                attachments: list  - file paths for binary attachments (optional)
                error: str         - error message if failed (optional)
        """
        raise NotImplementedError("Subclass must implement handle_request()")

    # ── Main processing ─────────────────────────────────────────

    def process_message(self, msg):
        """Full pipeline: rate limit → ACK → process → reply."""
        agent_id = msg["from"]
        subject = msg["subject"]
        msg_id = msg["id"]

        self.log.info(
            f"Processing [{msg_id}] from={agent_id} "
            f"subject={subject[:60]} "
            f"attachments={len(msg['attachments'])}"
        )

        # Rate limit
        allowed, limit_msg = self._check_rate_limit(agent_id)
        if not allowed:
            self.send_reply(agent_id, subject, limit_msg)
            self._mark_read(msg["file"])
            self._save_processed_id(msg_id)
            return

        self._record_rate(agent_id)

        # ACK with ticket
        ticket = self._send_ack(agent_id, subject, self._pending_count)

        # Process
        t0 = time.time()
        try:
            result = self.handle_request(msg)
        except Exception as e:
            self.log.exception(f"handle_request failed: {e}")
            result = {"body": f"Internal error processing your request: {e}"}
        elapsed = time.time() - t0
        self._update_avg_time(elapsed)

        # Build reply
        reply_body = f"[Ticket #{ticket}]\n\n"
        if result.get("error"):
            reply_body += f"Error: {result['error']}"
        else:
            reply_body += result.get("body", "(no output)")

        reply_attachments = result.get("attachments", [])
        self.send_reply(agent_id, subject, reply_body, reply_attachments)

        # Finalize
        self._mark_read(msg["file"])
        self._save_processed_id(msg_id)
        self.log.info(
            f"Done [{msg_id}] ticket=#{ticket} "
            f"elapsed={elapsed:.1f}s attachments_out={len(reply_attachments)}"
        )

    # ── Run loop ────────────────────────────────────────────────

    def run_once(self):
        """Single cycle: sync → process all → sync."""
        self.log.info("--- Cycle start ---")
        self.sync()

        messages = self.get_inbox_messages()
        if messages:
            self.log.info(f"Found {len(messages)} new message(s)")
            self._pending_count = len(messages)
            for msg in messages:
                try:
                    self.process_message(msg)
                except Exception as e:
                    self.log.exception(f"Error on {msg['id']}: {e}")
                self._pending_count = max(0, self._pending_count - 1)

        self.sync()
        self.log.info("--- Cycle end ---")

    def run(self):
        """Run the daemon loop."""
        self.log.info("=" * 60)
        self.log.info(f"{self.agent_name} service agent starting")
        self.log.info(f"Work dir: {self.work_dir}")
        self.log.info(f"Poll interval: {self.poll_interval}s")
        self.log.info("=" * 60)

        while True:
            try:
                self.run_once()
                time.sleep(self.poll_interval)
            except KeyboardInterrupt:
                self.log.info("Shutting down...")
                break
            except Exception as e:
                self.log.exception(f"Daemon error: {e}")
                time.sleep(30)
