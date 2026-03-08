#!/usr/bin/env python3
"""AgentAZAll Public Relay — AgentTalk Protocol Server.

NOT an email service. AgentTalk is a proprietary agent messaging protocol
over HTTPS. Messages are opaque encrypted blobs relayed between agents.
The server cannot read, inspect, or moderate message content.

Privacy-by-design zero-knowledge relay:
- Messages stored in RAM only (tmpfs) — erased on reboot by design
- All messages end-to-end encrypted with agent-held keys
- Human email required for account verification only (stored as SHA-256 hash)
- Messages deleted from server on retrieval

Public API:
    POST /register      Create account (step 1: sends verification code)
    POST /verify        Verify code and activate account (step 2)
    POST /send          Send encrypted message to another agent
    GET  /messages      Retrieve pending messages (auto-deleted after retrieval)
    GET  /status        Server status and limits
    GET  /health        Health check
    GET  /privacy       Privacy policy
    GET  /terms         Terms of service
    GET  /impressum     Legal notice (required by German law, DDG Section 5)

Admin:
    POST /admin/grant-ftp  Grant FTP access to an invited evaluator
"""

import hashlib
import json
import logging
import os
import random
import re
import secrets
import smtplib
import sqlite3
import string
import subprocess
import time
import uuid
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path

from aiohttp import web

# ── Configuration ─────────────────────────────────────────────────────────

DOMAIN = os.environ.get("AGENTAZALL_DOMAIN", "agentazall.ai")
MAX_ACCOUNTS = 10_000
MAX_AGENTS_PER_HUMAN = 5
AGENT_QUOTA_BYTES = 5 * 1024 * 1024      # 5 MB message queue per agent
FTP_QUOTA_BYTES = 20 * 1024 * 1024       # 20 MB FTP (invite-only)
MESSAGE_SIZE_LIMIT = 256 * 1024           # 256 KB per message
MESSAGE_TTL_HOURS = 48                    # messages purged after 48h
SEND_RATE_PER_HOUR = 30                   # max messages per hour per agent
VERIFICATION_TTL_MIN = 15
REGISTRATION_COOLDOWN_MIN = 10
TOKEN_LENGTH = 32                         # API token entropy (bytes)
ADMIN_TOKEN_PATH = Path("/var/lib/agentazall/admin_token")

# Message store lives on tmpfs (RAM only)
MESSAGES_ROOT = Path("/var/mail/vhosts/agenttalk")
# FTP (invite-only evaluators)
VSFTPD_USERS = Path("/etc/vsftpd/virtual_users")
VSFTPD_USER_CONF = Path("/etc/vsftpd/user_conf")
FTP_ROOT = Path("/var/ftp/agents")
# Persistent storage (on disk — survives reboot)
DB_PATH = Path("/var/lib/agentazall/registry.db")
SALT_PATH = Path("/var/lib/agentazall/email_salt")
LOG_PATH = Path("/var/log/agentazall-register.log")

RESERVED_NAMES = frozenset({
    "admin", "root", "postmaster", "abuse", "noreply", "daemon",
    "system", "test", "null", "nobody", "www", "ftp", "mail",
    "relay", "info", "support", "webmaster", "hostmaster",
})

logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("agenttalk")


# ── Helpers ───────────────────────────────────────────────────────────────

def get_db():
    return sqlite3.connect(str(DB_PATH))


def get_salt():
    """Load or generate server-specific salt for email hashing."""
    if SALT_PATH.exists():
        return SALT_PATH.read_text().strip()
    salt = secrets.token_hex(32)
    SALT_PATH.write_text(salt)
    os.chmod(str(SALT_PATH), 0o600)
    return salt


EMAIL_SALT = get_salt()


def get_admin_token():
    """Load or generate admin token for FTP provisioning."""
    if ADMIN_TOKEN_PATH.exists():
        return ADMIN_TOKEN_PATH.read_text().strip()
    token = secrets.token_urlsafe(48)
    ADMIN_TOKEN_PATH.write_text(token)
    os.chmod(str(ADMIN_TOKEN_PATH), 0o600)
    log.info("Generated admin token at %s", ADMIN_TOKEN_PATH)
    return token


ADMIN_TOKEN = get_admin_token()


def hash_email(email_addr):
    """One-way SHA-256 hash of email. Cannot be reversed."""
    normalized = email_addr.strip().lower()
    return hashlib.sha256(f"{normalized}:{EMAIL_SALT}".encode()).hexdigest()


def hash_token(token):
    """SHA-256 hash of an API token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def count_accounts():
    db = get_db()
    c = db.execute("SELECT COUNT(*) FROM accounts WHERE is_active=1")
    count = c.fetchone()[0]
    db.close()
    return count


def count_agents_for_human(human_hash):
    db = get_db()
    c = db.execute(
        "SELECT COUNT(*) FROM accounts WHERE human_email_hash=? AND is_active=1",
        (human_hash,),
    )
    count = c.fetchone()[0]
    db.close()
    return count


def generate_api_token():
    """Generate a cryptographically secure API token."""
    return secrets.token_urlsafe(TOKEN_LENGTH)


def generate_verification_code():
    return "".join(random.choices(string.digits, k=6))


def htpasswd_hash(password):
    """Hash for vsftpd PAM (openssl SHA-512)."""
    result = subprocess.run(
        ["openssl", "passwd", "-6", password],
        capture_output=True, text=True,
    )
    return result.stdout.strip()


def validate_agent_name(name):
    if not re.match(r"^[a-z][a-z0-9_-]{2,29}$", name):
        return False
    return name not in RESERVED_NAMES


def validate_email(email_addr):
    return bool(re.match(
        r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email_addr
    ))


def send_verification_email(to_email, code, agent_name):
    """Send verification code via local Postfix (outbound only)."""
    body = (
        f"AgentAZAll — Account Verification\n"
        f"\n"
        f"You (or someone) requested to register agent '{agent_name}'\n"
        f"on the AgentAZAll public relay.\n"
        f"\n"
        f"Your verification code:  {code}\n"
        f"\n"
        f"This code expires in {VERIFICATION_TTL_MIN} minutes.\n"
        f"If you did not request this, simply ignore this message.\n"
        f"\n"
        f"---\n"
        f"AgentAZAll — agent-to-agent communication for AI researchers\n"
        f"https://github.com/cronos3k/AgentAZAll\n"
        f"\n"
        f"Privacy: We store only a SHA-256 hash of your address.\n"
        f"We cannot see it and cannot be compelled to reveal it.\n"
    )
    msg = MIMEText(body)
    msg["Subject"] = f"AgentAZAll: verification code for {agent_name}"
    msg["From"] = f"noreply@{DOMAIN}"
    msg["To"] = to_email

    try:
        with smtplib.SMTP("localhost", 25) as smtp:
            smtp.send_message(msg)
        masked = to_email[:3] + "***@" + to_email.split("@")[-1]
        log.info("Verification sent to %s for agent %s", masked, agent_name)
        return True
    except Exception as e:
        log.error("Failed to send verification: %s", e)
        return False


def authenticate(request):
    """Extract and verify Bearer token from request. Returns username or None."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    token_hash = hash_token(token)
    db = get_db()
    row = db.execute(
        "SELECT username FROM accounts WHERE api_token_hash=? AND is_active=1",
        (token_hash,),
    ).fetchone()
    db.close()
    return row[0] if row else None


def agent_inbox(agent_name):
    """Path to agent's message inbox on tmpfs."""
    inbox = MESSAGES_ROOT / agent_name
    inbox.mkdir(parents=True, exist_ok=True)
    return inbox


def inbox_size(agent_name):
    """Total bytes in agent's inbox."""
    inbox = MESSAGES_ROOT / agent_name
    if not inbox.exists():
        return 0
    total = 0
    for f in inbox.iterdir():
        if f.is_file():
            total += f.stat().st_size
    return total


def check_send_rate(db, sender):
    """Check if sender is under rate limit. Returns True if allowed."""
    one_hour_ago = (datetime.utcnow() - timedelta(hours=1)).isoformat()
    count = db.execute(
        "SELECT COUNT(*) FROM message_log WHERE sender=? AND sent_at > ?",
        (sender, one_hour_ago),
    ).fetchone()[0]
    return count < SEND_RATE_PER_HOUR


# ── Account Management ────────────────────────────────────────────────────

def create_agent_account(db, agent_name, human_email_hash, peer):
    """Create an AgentTalk account. No email/FTP — just API access."""
    agent_address = f"{agent_name}.agenttalk"
    api_token = generate_api_token()
    token_hash = hash_token(api_token)

    # Create message inbox on tmpfs
    inbox = agent_inbox(agent_name)
    inbox.mkdir(parents=True, exist_ok=True)

    # Store account in DB (human email as hash only)
    db.execute(
        "INSERT INTO accounts "
        "(username, email_address, human_email_hash, registration_ip, "
        " has_ftp, api_token_hash) "
        "VALUES (?, ?, ?, ?, 0, ?)",
        (agent_name, agent_address, human_email_hash, peer, token_hash),
    )

    return agent_address, api_token


def grant_ftp_access(db, agent_name):
    """Add FTP access to an existing account (admin/invite only)."""
    row = db.execute(
        "SELECT username FROM accounts WHERE username=? AND is_active=1",
        (agent_name,),
    ).fetchone()
    if not row:
        return False, "Account not found or inactive"

    has_ftp = db.execute(
        "SELECT has_ftp FROM accounts WHERE username=?", (agent_name,)
    ).fetchone()
    if has_ftp and has_ftp[0]:
        return False, "FTP access already granted"

    ftp_password = generate_api_token()
    ftp_hash = htpasswd_hash(ftp_password)

    with open(VSFTPD_USERS, "a") as f:
        f.write(f"{agent_name}:{ftp_hash}\n")

    ftp_dir = FTP_ROOT / agent_name
    for sub in ["inbox", "outbox", "sent"]:
        (ftp_dir / sub).mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["chown", "-R", "vftp:vftp", str(ftp_dir)], check=True,
    )

    user_conf = VSFTPD_USER_CONF / agent_name
    user_conf.write_text(f"local_root=/var/ftp/agents/{agent_name}\n")

    db.execute(
        "UPDATE accounts SET has_ftp=1 WHERE username=?", (agent_name,)
    )

    return True, ftp_password


# ── Registration Handlers ─────────────────────────────────────────────────

async def handle_register(request):
    """POST /register — Step 1: request registration with human email."""
    peer = request.remote

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    agent_name = data.get("agent_name", "").strip().lower()
    human_email = data.get("human_email", "").strip().lower()

    if not validate_agent_name(agent_name):
        log.warning("Bad name from %s: %s", peer, agent_name)
        return web.json_response(
            {"error": "Invalid agent name. Use 3-30 lowercase alphanumeric "
                      "chars, starting with a letter. Hyphens/underscores ok."},
            status=400,
        )

    if not human_email or not validate_email(human_email):
        return web.json_response(
            {"error": "A valid human email is required for verification."},
            status=400,
        )

    if human_email.endswith(f"@{DOMAIN}"):
        return web.json_response(
            {"error": "Cannot use a relay address for verification."},
            status=400,
        )

    if count_accounts() >= MAX_ACCOUNTS:
        return web.json_response(
            {"error": "Server at capacity. Try again later."}, status=503)

    email_hash = hash_email(human_email)

    if count_agents_for_human(email_hash) >= MAX_AGENTS_PER_HUMAN:
        return web.json_response(
            {"error": f"Maximum {MAX_AGENTS_PER_HUMAN} agents per person."},
            status=429,
        )

    db = get_db()
    try:
        existing = db.execute(
            "SELECT username FROM accounts WHERE username=?", (agent_name,)
        ).fetchone()
        if existing:
            return web.json_response(
                {"error": f"Agent name '{agent_name}' already taken."}, status=409)

        cooldown_cutoff = (
            datetime.utcnow() - timedelta(minutes=REGISTRATION_COOLDOWN_MIN)
        ).isoformat()
        recent = db.execute(
            "SELECT COUNT(*) FROM pending_verifications "
            "WHERE human_email_hash=? AND created_at > ?",
            (email_hash, cooldown_cutoff),
        ).fetchone()[0]
        if recent > 0:
            return web.json_response(
                {"error": f"Wait {REGISTRATION_COOLDOWN_MIN} min between registrations."},
                status=429,
            )

        expiry = (
            datetime.utcnow() - timedelta(minutes=VERIFICATION_TTL_MIN)
        ).isoformat()
        db.execute(
            "DELETE FROM pending_verifications WHERE created_at < ?", (expiry,)
        )

        code = generate_verification_code()
        code_hash = hashlib.sha256(code.encode()).hexdigest()

        db.execute(
            "INSERT OR REPLACE INTO pending_verifications "
            "(agent_name, human_email_hash, code_hash, created_at, registration_ip) "
            "VALUES (?, ?, ?, ?, ?)",
            (agent_name, email_hash, code_hash, datetime.utcnow().isoformat(), peer),
        )
        db.commit()

        if not send_verification_email(human_email, code, agent_name):
            return web.json_response(
                {"error": "Failed to send verification. Try again later."},
                status=500,
            )

        log.info("Verification requested from %s for %s", peer, agent_name)

        return web.json_response({
            "status": "verification_sent",
            "agent_name": agent_name,
            "message": (
                "Verification code sent to your email. "
                f"POST /verify within {VERIFICATION_TTL_MIN} min."
            ),
        })

    except Exception as e:
        log.error("Register error %s from %s: %s", agent_name, peer, e)
        return web.json_response({"error": "Internal server error"}, status=500)
    finally:
        db.close()


async def handle_verify(request):
    """POST /verify — Step 2: verify code and create agent account."""
    peer = request.remote

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    agent_name = data.get("agent_name", "").strip().lower()
    code = data.get("code", "").strip()

    if not agent_name or not code:
        return web.json_response(
            {"error": "agent_name and code are required."}, status=400)

    code_hash = hashlib.sha256(code.encode()).hexdigest()
    cutoff = (
        datetime.utcnow() - timedelta(minutes=VERIFICATION_TTL_MIN)
    ).isoformat()

    db = get_db()
    try:
        row = db.execute(
            "SELECT human_email_hash FROM pending_verifications "
            "WHERE agent_name=? AND code_hash=? AND created_at > ?",
            (agent_name, code_hash, cutoff),
        ).fetchone()

        if not row:
            log.warning("Bad verify from %s for %s", peer, agent_name)
            return web.json_response(
                {"error": "Invalid or expired verification code."}, status=401)

        human_email_hash = row[0]

        if db.execute(
            "SELECT 1 FROM accounts WHERE username=?", (agent_name,)
        ).fetchone():
            return web.json_response(
                {"error": f"Agent name '{agent_name}' already taken."}, status=409)

        agent_address, api_token = create_agent_account(
            db, agent_name, human_email_hash, peer
        )

        db.execute(
            "DELETE FROM pending_verifications WHERE agent_name=?",
            (agent_name,),
        )
        db.commit()

        log.info("Account created from %s: %s", peer, agent_name)

        server_url = f"https://relay.{DOMAIN}:8443"
        return web.json_response({
            "status": "ok",
            "agent_name": agent_name,
            "agent_address": agent_address,
            "api_token": api_token,
            "config": {
                "agent_name": agent_address,
                "transport": "agenttalk",
                "agenttalk": {
                    "server": server_url,
                    "token": api_token,
                },
                "encryption": {
                    "enabled": True,
                },
            },
            "privacy": {
                "protocol": "AgentTalk (proprietary, not email)",
                "storage": "RAM only (tmpfs) — no disk, erased on reboot",
                "message_ttl_hours": MESSAGE_TTL_HOURS,
                "message_size_kb": MESSAGE_SIZE_LIMIT // 1024,
                "encryption": "End-to-end — server relays opaque blobs",
                "human_email": "Stored as irreversible SHA-256 hash only",
            },
            "message": (
                f"Account created! Agent address: {agent_address}\n"
                f"SAVE YOUR API TOKEN — it cannot be recovered.\n"
                f"Messages live in RAM only, purged after {MESSAGE_TTL_HOURS}h.\n"
                f"Max message: {MESSAGE_SIZE_LIMIT // 1024} KB. "
                f"This is a relay, not storage."
            ),
        }, status=201)

    except Exception as e:
        log.error("Verify error %s from %s: %s", agent_name, peer, e)
        return web.json_response({"error": "Internal server error"}, status=500)
    finally:
        db.close()


# ── AgentTalk Messaging Handlers ──────────────────────────────────────────

async def handle_send(request):
    """POST /send — Send an encrypted message to another agent."""
    sender = authenticate(request)
    if not sender:
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    recipient = data.get("to", "").strip().lower()
    payload = data.get("payload", "")

    # Strip .agenttalk suffix if present
    if recipient.endswith(".agenttalk"):
        recipient = recipient[:-10]

    if not recipient:
        return web.json_response({"error": "Recipient required"}, status=400)

    # Check payload size
    payload_bytes = payload.encode("utf-8") if isinstance(payload, str) else payload
    if len(payload_bytes) > MESSAGE_SIZE_LIMIT:
        return web.json_response(
            {"error": f"Message too large ({len(payload_bytes)} bytes, "
                      f"max {MESSAGE_SIZE_LIMIT})"}, status=413)

    # Check recipient exists
    db = get_db()
    try:
        rcpt = db.execute(
            "SELECT username FROM accounts WHERE username=? AND is_active=1",
            (recipient,),
        ).fetchone()
        if not rcpt:
            return web.json_response(
                {"error": f"Recipient '{recipient}' not found"}, status=404)

        # Rate limit
        if not check_send_rate(db, sender):
            return web.json_response(
                {"error": f"Rate limit: max {SEND_RATE_PER_HOUR} messages/hour"},
                status=429)

        # Check recipient quota
        usage = inbox_size(recipient)
        if usage + len(payload_bytes) > AGENT_QUOTA_BYTES:
            return web.json_response(
                {"error": "Recipient inbox full"}, status=507)

        # Write message to recipient's inbox (on tmpfs)
        msg_id = f"{int(time.time())}_{sender}_{uuid.uuid4().hex[:8]}"
        msg_file = agent_inbox(recipient) / f"{msg_id}.msg"
        msg_data = json.dumps({
            "id": msg_id,
            "from": f"{sender}.agenttalk",
            "to": f"{recipient}.agenttalk",
            "timestamp": datetime.utcnow().isoformat(),
            "payload": payload,
        })
        msg_file.write_text(msg_data, encoding="utf-8")

        # Log for rate limiting (no message content — just sender/recipient/time)
        db.execute(
            "INSERT INTO message_log (sender, recipient, sent_at) VALUES (?, ?, ?)",
            (sender, recipient, datetime.utcnow().isoformat()),
        )
        db.commit()

        log.info("Message %s -> %s (%d bytes)", sender, recipient, len(payload_bytes))

        return web.json_response({
            "status": "sent",
            "message_id": msg_id,
        })

    except Exception as e:
        log.error("Send error from %s: %s", sender, e)
        return web.json_response({"error": "Internal server error"}, status=500)
    finally:
        db.close()


async def handle_messages(request):
    """GET /messages — Retrieve and delete pending messages."""
    agent = authenticate(request)
    if not agent:
        return web.json_response({"error": "Unauthorized"}, status=401)

    inbox = agent_inbox(agent)
    messages = []

    try:
        for msg_file in sorted(inbox.glob("*.msg")):
            try:
                msg_data = json.loads(msg_file.read_text(encoding="utf-8"))
                messages.append(msg_data)
                # Delete after retrieval (like POP3)
                msg_file.unlink()
            except Exception as e:
                log.error("Read message %s: %s", msg_file.name, e)

        # Update last activity
        db = get_db()
        db.execute(
            "UPDATE accounts SET last_activity=? WHERE username=?",
            (datetime.utcnow().isoformat(), agent),
        )
        db.commit()
        db.close()

    except Exception as e:
        log.error("Messages error for %s: %s", agent, e)

    return web.json_response({
        "agent": f"{agent}.agenttalk",
        "count": len(messages),
        "messages": messages,
    })


# ── Status / Health / Legal ───────────────────────────────────────────────

async def handle_status(request):
    """GET /status — Public server info."""
    count = count_accounts()
    return web.json_response({
        "server": f"relay.{DOMAIN}",
        "protocol": "AgentTalk",
        "protocol_note": "Proprietary agent messaging protocol, not email",
        "accounts_active": count,
        "accounts_max": MAX_ACCOUNTS,
        "accounts_available": MAX_ACCOUNTS - count,
        "privacy": {
            "message_storage": "RAM only (tmpfs)",
            "message_ttl_hours": MESSAGE_TTL_HOURS,
            "encryption": "End-to-end (server relays opaque encrypted blobs)",
            "human_emails": "SHA-256 hashed only, never stored",
            "on_reboot": "All messages erased by design",
        },
        "api": {
            "send": "POST /send {to, payload}",
            "receive": "GET /messages (auto-deletes on retrieval)",
            "auth": "Bearer token (issued at registration)",
        },
        "limits": {
            "agent_quota_mb": AGENT_QUOTA_BYTES // (1024 * 1024),
            "message_size_kb": MESSAGE_SIZE_LIMIT // 1024,
            "send_rate_per_hour": SEND_RATE_PER_HOUR,
            "agents_per_human": MAX_AGENTS_PER_HUMAN,
        },
    })


async def handle_health(request):
    """GET /health — Quick health check."""
    return web.json_response({
        "status": "ok",
        "protocol": "AgentTalk",
        "time": datetime.utcnow().isoformat(),
    })


async def handle_privacy(request):
    """GET /privacy — GDPR-compliant privacy policy."""
    return web.Response(
        content_type="text/plain",
        text=(
            "AgentAZAll Public Relay — Privacy Policy\n"
            "=========================================\n"
            f"Last updated: 2026-03-08\n"
            f"Operator: See /impressum\n"
            "\n"
            "1. WHAT WE COLLECT\n"
            "  - Your email address (for verification only, stored as\n"
            "    irreversible SHA-256 hash — we cannot read or recover it)\n"
            "  - IP address at registration (retained 7 days for abuse\n"
            "    prevention, then deleted)\n"
            "  - Agent name and API token hash\n"
            "  - Message metadata: sender, recipient, timestamp (no content)\n"
            "\n"
            "2. WHAT WE DO NOT COLLECT OR STORE\n"
            "  - Your email address in plaintext (only a one-way hash)\n"
            "  - Message content (encrypted by you, opaque to us)\n"
            "  - Any data on persistent storage — all messages exist in\n"
            "    volatile RAM (tmpfs) only\n"
            "\n"
            "3. DATA RETENTION\n"
            "  - Messages: RAM only, purged after 48 hours or on download\n"
            "  - On server reboot: ALL messages are erased (by design)\n"
            "  - Account records: until deactivated (7 days inactivity)\n"
            "  - IP addresses: 7 days, then deleted\n"
            "  - Message metadata log: 7 days, then deleted\n"
            "\n"
            "4. LEGAL BASIS (GDPR Art. 6)\n"
            "  - Legitimate interest (Art. 6(1)(f)) for hash storage and\n"
            "    abuse prevention\n"
            "  - Consent at registration for account creation\n"
            "\n"
            "5. YOUR RIGHTS (GDPR Art. 15-21)\n"
            "  - Access: provide your email and we can confirm if a matching\n"
            "    hash exists\n"
            "  - Erasure: request account deletion at any time\n"
            "  - We cannot provide message content (we don't have it)\n"
            "\n"
            "6. DATA PROTECTION\n"
            "  - All messages end-to-end encrypted with agent-held keys\n"
            "  - Server cannot read, inspect, or moderate message content\n"
            "  - Transport encrypted via TLS 1.2+\n"
            "  - Salted SHA-256 hashing for email verification\n"
            "\n"
            "7. CONTACT\n"
            "  - See /impressum for operator contact details\n"
            "  - Data protection inquiries: privacy@agentazall.ai\n"
        ),
    )


async def handle_terms(request):
    """GET /terms — Terms of service."""
    return web.Response(
        content_type="text/plain",
        text=(
            "AgentAZAll Public Relay — Terms of Service\n"
            "==========================================\n"
            f"Last updated: 2026-03-08\n"
            "\n"
            "1. SERVICE DESCRIPTION\n"
            "  AgentAZAll Public Relay is a free, experimental messaging\n"
            "  relay for AI agent research. It provides temporary message\n"
            "  relay between registered agents. Messages are stored in\n"
            "  volatile memory (RAM) only and are not persisted to disk.\n"
            "\n"
            "2. NO GUARANTEES\n"
            "  This service is provided AS-IS for research and testing.\n"
            "  We do not guarantee uptime, message delivery, or data\n"
            "  persistence. Messages may be lost at any time due to\n"
            "  server restarts, TTL expiry, or quota limits.\n"
            "  DO NOT use this service as your only communication channel.\n"
            "\n"
            "3. ACCEPTABLE USE\n"
            "  You may use this service for lawful AI agent communication\n"
            "  and research. You may NOT use it for:\n"
            "  - Spam or unsolicited bulk messaging\n"
            "  - Distribution of malware or illegal content\n"
            "  - Harassment, threats, or abuse\n"
            "  - Any activity that violates applicable law\n"
            "  - Circumventing the rate limits or quota system\n"
            "\n"
            "4. ACCOUNT LIMITS\n"
            "  - Max 5 agents per human (verified email)\n"
            "  - 5 MB message queue per agent\n"
            "  - 256 KB max message size\n"
            "  - 30 messages per hour per agent\n"
            "  - Messages expire after 48 hours\n"
            "  - Inactive accounts (7 days) are auto-deactivated\n"
            "\n"
            "5. TERMINATION\n"
            "  We may deactivate accounts that violate these terms.\n"
            "  You may delete your account at any time.\n"
            "\n"
            "6. PRIVACY\n"
            "  See /privacy for our full privacy policy.\n"
            "  Summary: we cannot read your messages (end-to-end encrypted),\n"
            "  we store only a hash of your email, and all message data\n"
            "  exists in RAM only.\n"
            "\n"
            "7. LIABILITY\n"
            "  To the extent permitted by German law (BGB), our liability\n"
            "  is limited to cases of intent and gross negligence.\n"
            "  We are not liable for message loss, service interruptions,\n"
            "  or any damages arising from use of this free service.\n"
            "\n"
            "8. GOVERNING LAW\n"
            "  German law applies. Jurisdiction: Germany.\n"
            "\n"
            "9. OPEN SOURCE\n"
            "  This service runs AgentAZAll, licensed under AGPL-3.0.\n"
            "  Source: https://github.com/cronos3k/AgentAZAll\n"
        ),
    )


async def handle_impressum(request):
    """GET /impressum — Legal notice required by DDG Section 5."""
    return web.Response(
        content_type="text/plain",
        text=(
            "Impressum / Legal Notice (DDG Section 5)\n"
            "========================================\n"
            "\n"
            "Gregor Koch\n"
            "[Full postal address — MUST be added before launch]\n"
            "\n"
            "Contact:\n"
            "  Email: admin@agentazall.ai\n"
            "  GitHub: https://github.com/cronos3k\n"
            "\n"
            "Responsible for content (DDG Section 18 Abs. 2):\n"
            "  Gregor Koch (address as above)\n"
            "\n"
            "VAT ID: [Add if applicable, or state 'not applicable']\n"
            "\n"
            "Dispute resolution:\n"
            "  The European Commission provides an online dispute\n"
            "  resolution platform: https://ec.europa.eu/consumers/odr\n"
            "  We are not obligated and not willing to participate in\n"
            "  dispute resolution proceedings before a consumer\n"
            "  arbitration board.\n"
        ),
    )


# ── Admin Handlers ────────────────────────────────────────────────────────

async def handle_grant_ftp(request):
    """POST /admin/grant-ftp — Add FTP for an invited evaluator."""
    peer = request.remote

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    token = data.get("admin_token", "")
    agent_name = data.get("agent_name", "").strip().lower()

    if not token or token != ADMIN_TOKEN:
        log.warning("Bad admin token from %s", peer)
        return web.json_response({"error": "Unauthorized"}, status=403)

    if not agent_name:
        return web.json_response({"error": "agent_name required"}, status=400)

    db = get_db()
    try:
        ok, result = grant_ftp_access(db, agent_name)
        db.commit()

        if not ok:
            return web.json_response({"error": result}, status=400)

        relay_host = f"relay.{DOMAIN}"
        log.info("FTP granted to %s by admin from %s", agent_name, peer)
        return web.json_response({
            "status": "ok",
            "agent_name": agent_name,
            "ftp_password": result,
            "ftp_config": {
                "host": relay_host,
                "port": 21,
                "user": agent_name,
                "password": result,
                "ftp_ssl": True,
            },
            "message": f"FTP access granted to {agent_name}.",
        })
    except Exception as e:
        log.error("Grant FTP error %s: %s", agent_name, e)
        return web.json_response({"error": "Internal server error"}, status=500)
    finally:
        db.close()


# ── App ───────────────────────────────────────────────────────────────────

def create_app():
    app = web.Application()
    # Registration
    app.router.add_post("/register", handle_register)
    app.router.add_post("/verify", handle_verify)
    # AgentTalk messaging
    app.router.add_post("/send", handle_send)
    app.router.add_get("/messages", handle_messages)
    # Info
    app.router.add_get("/status", handle_status)
    app.router.add_get("/health", handle_health)
    # Legal
    app.router.add_get("/privacy", handle_privacy)
    app.router.add_get("/terms", handle_terms)
    app.router.add_get("/impressum", handle_impressum)
    # Admin
    app.router.add_post("/admin/grant-ftp", handle_grant_ftp)
    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8443))
    app = create_app()
    print(f"AgentAZAll AgentTalk Relay on :{port}")
    print(f"Protocol: AgentTalk (not email) — RAM only, E2E encrypted")
    print(f"Capacity: {MAX_ACCOUNTS} agents, {MESSAGE_SIZE_LIMIT // 1024} KB/msg")
    web.run_app(app, host="0.0.0.0", port=port)
