#!/usr/bin/env python3
"""
AgentAZAll Support Agent — Main Daemon

A 24/7 support agent that:
1. Polls its inbox for messages from other agents
2. Classifies requests (welcome / news / support / jailbreak / off-topic)
3. Enforces rate limits and tracks abuse (naughty list)
4. Routes to appropriate handler (cached bulletin, LLM, welcome flow)
5. Sends replies via AgentAZAll messaging

Usage:
    python agent.py                 # Run daemon
    python agent.py --once          # Process inbox once and exit
    python agent.py --stats         # Show statistics
    python agent.py --test          # Test LLM connection
"""
import sys
import os
import time
import logging
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

# Add parent directory for agentazall imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import config as cfg
from db import (
    get_db, is_blocked, record_offense, check_auto_block,
    check_rate_limit, record_rate_limit, increment_requests,
    log_request, get_stats, cleanup_old_rate_limits,
)
from gatekeeper import classify_request, detect_jailbreak, sanitize_input
from bulletin import get_bulletin_response
from welcome import handle_welcome, is_welcome_conversation
from llm_client import query_llm, is_llm_available
from knowledge import is_teaching_message, process_teaching, build_knowledge_context

# Logging setup
cfg.LOGS_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(cfg.LOGS_DIR / "support_agent.log"),
    ],
)
log = logging.getLogger("support.agent")


class SupportAgent:
    """Main support agent daemon."""

    # Average LLM response time in seconds (updated after each response)
    _avg_response_time = 8.0
    _response_count = 0
    _ticket_counter = 0

    def __init__(self, work_dir=None):
        self.work_dir = work_dir or cfg.BASE_DIR / "agent_home"
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.db = get_db()
        self.processed_ids = set()
        self._load_processed_ids()
        self._pending_support_queue = []  # messages waiting for LLM

    def _load_processed_ids(self):
        """Load set of already-processed message IDs to avoid double-processing."""
        tracker = self.work_dir / ".processed_ids"
        if tracker.exists():
            self.processed_ids = set(
                tracker.read_text(encoding="utf-8").strip().split("\n")
            )
        log.info(f"Loaded {len(self.processed_ids)} processed message IDs")

    def _save_processed_id(self, msg_id):
        """Persist a processed message ID."""
        self.processed_ids.add(msg_id)
        tracker = self.work_dir / ".processed_ids"
        tracker.write_text(
            "\n".join(sorted(self.processed_ids)),
            encoding="utf-8",
        )

    def _run_agentazall(self, *args, timeout=30):
        """Run an agentazall CLI command."""
        cmd = [sys.executable, "-m", "agentazall"] + list(args)
        env = os.environ.copy()
        env["AGENTAZALL_ROOT"] = str(self.work_dir)
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout, env=env, cwd=str(self.work_dir),
            )
            return result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired:
            log.warning(f"Command timed out: {' '.join(args)}")
            return "", "timeout", -1

    def sync_inbox(self):
        """Run daemon --once to sync messages."""
        stdout, stderr, rc = self._run_agentazall("daemon", "--once")
        if rc != 0 and stderr and "timeout" not in stderr:
            log.warning(f"Daemon sync warning: {stderr[:200]}")

    def get_inbox_messages(self):
        """Read all new messages from inbox."""
        from agentazall.config import load_config
        from agentazall.helpers import agent_day, today_str
        from agentazall.messages import parse_message, parse_headers_only

        # Load config from agent_home
        config_path = self.work_dir / "config.json"
        if not config_path.exists():
            log.error(f"No config.json found at {config_path}")
            return []

        azcfg = load_config(config_path)

        messages = []
        # Check today and yesterday (in case of midnight crossover)
        for date_offset in [today_str()]:
            inbox_dir = agent_day(azcfg, date_offset) / "inbox"
            if not inbox_dir.exists():
                continue

            for msg_file in sorted(inbox_dir.glob("*.txt")):
                headers = parse_headers_only(msg_file)
                if not headers:
                    continue

                msg_id = headers.get("Message-ID", msg_file.stem)
                if msg_id in self.processed_ids:
                    continue

                status = headers.get("Status", "").lower()
                if status == "read":
                    continue

                # Parse full message
                full_headers, body = parse_message(msg_file)
                if full_headers:
                    messages.append({
                        "id": msg_id,
                        "from": full_headers.get("From", "unknown"),
                        "to": full_headers.get("To", ""),
                        "subject": full_headers.get("Subject", ""),
                        "body": body or "",
                        "file": msg_file,
                        "date": full_headers.get("Date", ""),
                    })

        return messages

    def send_reply(self, to_agent, subject, body):
        """Send a reply via agentazall CLI."""
        if not subject.startswith("Re: "):
            subject = f"Re: {subject}"

        stdout, stderr, rc = self._run_agentazall(
            "send",
            "--to", to_agent,
            "-s", subject,
            "-b", body,
            timeout=15,
        )

        if rc == 0:
            log.info(f"Reply sent to {to_agent}: {subject[:50]}")
        else:
            log.error(f"Failed to send reply to {to_agent}: {stderr[:200]}")
        return rc == 0

    def mark_as_read(self, msg_file):
        """Mark a message file as read."""
        try:
            content = msg_file.read_text(encoding="utf-8")
            content = content.replace("Status: new", "Status: read", 1)
            msg_file.write_text(content, encoding="utf-8")
        except Exception as e:
            log.warning(f"Could not mark {msg_file} as read: {e}")

    def process_message(self, msg):
        """Process a single incoming message through the full pipeline."""
        agent_id = msg["from"]
        subject = msg["subject"]
        body = msg["body"]
        msg_id = msg["id"]

        log.info(f"Processing: [{msg_id}] from={agent_id} subject={subject[:50]}")
        start_time = time.time()

        # === GATE 0: Blocked check ===
        if is_blocked(self.db, agent_id):
            log.warning(f"BLOCKED agent attempted contact: {agent_id}")
            self.send_reply(
                agent_id, subject,
                "Your agent has been temporarily suspended due to policy violations. "
                "Contact the administrator if you believe this is an error."
            )
            self._finish_message(msg, "blocked")
            return

        # === TEACHER MODE: TEACH: prefix from authorized senders ===
        if is_teaching_message(subject):
            if agent_id in cfg.TEACHER_ADDRESSES:
                log.info(f"TEACHING from authorized teacher: {agent_id}")
                response, entry_id = process_teaching(
                    self.db, agent_id, subject, body
                )
                self.send_reply(agent_id, subject, response)
                self._finish_message(
                    msg, "teaching",
                    tokens=0, elapsed=0,
                )
                return
            else:
                log.warning(f"Unauthorized teach attempt from {agent_id}")
                self.send_reply(
                    agent_id, subject,
                    "Teaching mode is restricted to authorized administrators. "
                    "If you have a question, just send it without the TEACH: prefix!"
                )
                self._finish_message(msg, "teach_denied")
                return

        # === GATE 1: Check if in active welcome conversation ===
        if is_welcome_conversation(self.db, agent_id):
            log.info(f"Continuing welcome conversation with {agent_id}")
            response, tokens, elapsed = handle_welcome(
                self.db, agent_id, subject, body
            )
            if response:
                self.send_reply(agent_id, subject, response)
                self._finish_message(msg, "welcome", tokens=tokens, elapsed=elapsed)
                return

        # === GATE 2: Classify request ===
        request_type, detail = classify_request(subject, body)
        log.info(f"Classified as: {request_type} (detail: {detail})")

        if request_type == "jailbreak":
            log.warning(f"JAILBREAK attempt from {agent_id}: {detail}")
            record_offense(self.db, agent_id, "jailbreak", 5, body[:200])
            check_auto_block(self.db, agent_id)
            self.send_reply(
                agent_id, subject,
                "Nice try. This has been logged. "
                "I'm here to help with AgentAZAll — not for prompt gymnastics. "
                "Send a real question anytime!"
            )
            self._finish_message(msg, "jailbreak")
            return

        if request_type == "off_topic":
            log.info(f"Off-topic request from {agent_id}")
            record_offense(self.db, agent_id, "off_topic", 1, body[:200])
            check_auto_block(self.db, agent_id)
            self.send_reply(
                agent_id, subject,
                "I'm the AgentAZAll support agent — I can only help with AgentAZAll "
                "setup, configuration, and troubleshooting.\n\n"
                "For other tasks, please use your own LLM resources.\n\n"
                "Need AgentAZAll help? Just ask about setup, messaging, transports, "
                "or any error you're seeing!"
            )
            self._finish_message(msg, "off_topic")
            return

        # === GATE 3: Rate limit ===
        allowed, limit_msg = check_rate_limit(self.db, agent_id)
        if not allowed:
            log.info(f"Rate limited: {agent_id}")
            self.send_reply(agent_id, subject, limit_msg)
            self._finish_message(msg, "rate_limited")
            return

        # === GATE 4: Sanitize input ===
        body = sanitize_input(body)

        # === Handle by type ===
        record_rate_limit(self.db, agent_id)

        if request_type == "welcome":
            response, tokens, elapsed = handle_welcome(
                self.db, agent_id, subject, body
            )
            if response:
                self.send_reply(agent_id, subject, response)
                self._finish_message(msg, "welcome", tokens=tokens, elapsed=elapsed)
                return

        if request_type == "news":
            response = get_bulletin_response(self.db)
            self.send_reply(agent_id, subject, response)
            self._finish_message(msg, "news")
            return

        # === SUPPORT: Queue acknowledgment + LLM response ===

        # Assign ticket and calculate queue position
        SupportAgent._ticket_counter += 1
        ticket_num = SupportAgent._ticket_counter
        queue_pos = self._pending_support_count
        eta_seconds = max(5, int(queue_pos * self._avg_response_time + self._avg_response_time))

        # Send instant acknowledgment
        if eta_seconds < 60:
            eta_str = f"~{eta_seconds} seconds"
        else:
            eta_min = eta_seconds // 60
            eta_str = f"~{eta_min} minute{'s' if eta_min > 1 else ''}"

        ack_body = (
            f"Thanks for reaching out to AgentAZAll Support!\n\n"
            f"Your request has been received and queued.\n"
            f"  Ticket:   #{ticket_num}\n"
            f"  Position: {queue_pos + 1} in queue\n"
            f"  Est. wait: {eta_str}\n\n"
            f"I'm working on your answer now — hang tight!"
        )
        self.send_reply(agent_id, f"Ack: {subject}", ack_body)
        # Push the ack out immediately
        self.sync_inbox()
        log.info(
            f"ACK sent: ticket #{ticket_num}, pos {queue_pos + 1}, "
            f"ETA {eta_str} to {agent_id}"
        )

        # Now do the actual LLM work
        knowledge_ctx = build_knowledge_context(self.db, f"{subject} {body}")
        if knowledge_ctx:
            prompt = (
                f"{knowledge_ctx}\n"
                f"Subject: {subject}\n\nMessage from {agent_id}:\n{body}"
            )
            log.info("Knowledge context injected into support prompt")
        else:
            prompt = f"Subject: {subject}\n\nMessage from {agent_id}:\n{body}"

        llm_start = time.time()
        response, tokens, elapsed = query_llm(prompt)
        llm_elapsed = time.time() - llm_start

        # Update running average response time
        SupportAgent._response_count += 1
        n = SupportAgent._response_count
        SupportAgent._avg_response_time = (
            SupportAgent._avg_response_time * (n - 1) + llm_elapsed
        ) / n

        if response is None:
            response = (
                "I'm having a temporary technical issue with my inference backend. "
                "Please try again in a few minutes, or check the AgentAZAll documentation "
                "at https://github.com/cronos3k/AgentAZAll\n\n"
                "Common resources:\n"
                "- pip install agentazall\n"
                "- agentazall register --agent myagent\n"
                "- agentazall onboard (full getting-started guide)"
            )

        # Prepend ticket reference to the actual answer
        response = f"[Ticket #{ticket_num}]\n\n{response}"

        self.send_reply(agent_id, subject, response)
        increment_requests(self.db, agent_id, good=True)
        self._finish_message(msg, "support", tokens=tokens, elapsed=elapsed)

    def _finish_message(self, msg, request_type, tokens=0, elapsed=0):
        """Mark message as processed and log it."""
        self.mark_as_read(msg["file"])
        self._save_processed_id(msg["id"])
        elapsed_ms = int(elapsed) if elapsed else 0
        log_request(
            self.db, msg["from"], request_type,
            subject=msg["subject"], response_time_ms=elapsed_ms,
            tokens_used=tokens,
        )

    def run_once(self):
        """Sync inbox, process all new messages, sync outbox."""
        log.info("--- Cycle start ---")

        # Sync incoming
        self.sync_inbox()

        # Process messages
        messages = self.get_inbox_messages()
        if messages:
            log.info(f"Found {len(messages)} new message(s)")
            # Track how many messages are pending for queue position
            self._pending_support_count = len(messages)
            for msg in messages:
                try:
                    self.process_message(msg)
                    self._pending_support_count = max(0, self._pending_support_count - 1)
                except Exception as e:
                    log.exception(f"Error processing message {msg['id']}: {e}")
                    self._pending_support_count = max(0, self._pending_support_count - 1)

        # Sync outgoing (daemon sends outbox)
        self.sync_inbox()

        log.info("--- Cycle end ---")

    def run(self):
        """Run the daemon loop."""
        log.info("=" * 60)
        log.info("AgentAZAll Support Agent starting")
        log.info(f"Agent: {cfg.AGENT_ADDRESS}")
        log.info(f"Work dir: {self.work_dir}")
        log.info(f"DB: {cfg.DB_PATH}")
        log.info(f"LLM: {cfg.LLM_URL}")
        log.info(f"Poll interval: {cfg.POLL_INTERVAL_SECONDS}s")
        log.info("=" * 60)

        # Check LLM
        if is_llm_available():
            log.info("LLM server is available")
        else:
            log.warning("LLM server is NOT available — will retry on requests")

        # Initial cleanup
        cleanup_old_rate_limits(self.db)

        while True:
            try:
                self.run_once()
                time.sleep(cfg.POLL_INTERVAL_SECONDS)
            except KeyboardInterrupt:
                log.info("Shutting down gracefully...")
                break
            except Exception as e:
                log.exception(f"Daemon error: {e}")
                time.sleep(30)  # back off on errors


def show_stats():
    """Print support agent statistics."""
    db = get_db()
    stats = get_stats(db)

    print("\n=== AgentAZAll Support Agent Statistics ===\n")
    print(f"Total agents served:   {stats['total_agents']}")
    print(f"Total requests:        {stats['total_requests']}")
    print(f"Total offenses:        {stats['total_offenses']}")
    print(f"Currently blocked:     {stats['blocked_agents']}")

    if stats["request_types"]:
        print("\nRequest types:")
        for rt in stats["request_types"]:
            print(f"  {rt['request_type']:15s}  {rt['count']}")

    if stats["top_offenders"]:
        print("\nTop offenders:")
        for off in stats["top_offenders"]:
            if off["total_score"] > 0:
                print(
                    f"  {off['agent_id']:40s}  "
                    f"score={off['total_score']:3d}  "
                    f"requests={off['total_requests']}"
                )

    print()


def test_llm():
    """Test LLM connection."""
    print("Testing LLM connection...")
    if is_llm_available():
        print("  Health check: OK")
    else:
        print("  Health check: FAILED")
        print(f"  URL: {cfg.LLM_URL}")
        return

    print("  Sending test query...")
    response, tokens, elapsed = query_llm(
        "What is AgentAZAll? Answer in one sentence.",
        max_tokens=100,
    )
    if response:
        print(f"  Response: {response}")
        print(f"  Tokens: {tokens}, Time: {elapsed}ms")
    else:
        print("  ERROR: No response from LLM")


def show_knowledge():
    """Print knowledge base summary."""
    from db import get_knowledge_count, get_knowledge_topics
    db = get_db()
    count = get_knowledge_count(db)
    topics = get_knowledge_topics(db)

    print(f"\n=== Knowledge Base ===\n")
    print(f"Total entries: {count}")
    if topics:
        print(f"\nTopics ({len(topics)}):")
        for t in topics:
            print(f"  - {t}")
    else:
        print("\nNo knowledge entries yet. Send TEACH: messages to build the knowledge base.")
    print()


def main():
    parser = argparse.ArgumentParser(description="AgentAZAll Support Agent Daemon")
    parser.add_argument("--once", action="store_true", help="Process inbox once and exit")
    parser.add_argument("--stats", action="store_true", help="Show statistics")
    parser.add_argument("--test", action="store_true", help="Test LLM connection")
    parser.add_argument("--knowledge", action="store_true", help="Show knowledge base")
    parser.add_argument("--work-dir", type=str, help="Working directory for agent data")
    args = parser.parse_args()

    if args.stats:
        show_stats()
        return

    if args.test:
        test_llm()
        return

    if args.knowledge:
        show_knowledge()
        return

    work_dir = Path(args.work_dir) if args.work_dir else None
    agent = SupportAgent(work_dir=work_dir)

    if args.once:
        agent.run_once()
    else:
        agent.run()


if __name__ == "__main__":
    main()
