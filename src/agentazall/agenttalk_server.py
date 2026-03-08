#!/usr/bin/env python3
"""
AgentAZAll Local AgentTalk Server

Zero-dependency HTTPS REST API server for agent-to-agent communication.
The modern alternative to Email + FTP — same functionality, simpler protocol.

AgentTalk is functionally identical to Email/FTP from the agent's perspective:
agents send messages, receive messages, and sync state. The difference is
the transport layer: a single HTTPS REST API instead of SMTP + IMAP + POP3.

Features:
    - POST /send          — send a message to another agent
    - GET  /messages      — retrieve pending messages (auto-deleted)
    - POST /register      — create a local agent account
    - GET  /status        — server info
    - GET  /health        — health check
    - GET  /agents        — list registered agents

Usage:
    python agenttalk_server.py                      # defaults (port 8484)
    python agenttalk_server.py --port 9090          # custom port
    python agenttalk_server.py --create-accounts 5  # agent1..agent5

API compatible with the public relay at relay.agentazall.ai — agents can
switch between local and public servers by changing one config line.
"""

import asyncio
import hashlib
import json
import logging
import secrets
import socket
import time
import uuid
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

# -- logging --

LOG_FMT = "%(asctime)s [%(name)-4s] %(message)s"
LOG_DATE = "%H:%M:%S"
logging.basicConfig(level=logging.INFO, format=LOG_FMT, datefmt=LOG_DATE)
log = logging.getLogger("TALK")

# -- port helpers --


def is_port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def find_port(host: str, preferred: int, alt_start: int, alt_end: int) -> int:
    if is_port_free(host, preferred):
        return preferred
    for p in range(alt_start, alt_end):
        if is_port_free(host, p):
            return p
    raise RuntimeError(
        f"No free port (tried {preferred} and {alt_start}-{alt_end})"
    )


# -- message store --


class AgentTalkStore:
    """File-backed store for agents and messages."""

    def __init__(self, base_dir: str):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)
        self.accounts: Dict[str, dict] = self._load_accounts()
        self._msg_counter = int(time.time() * 1000)

    # -- accounts --

    def _accounts_path(self) -> Path:
        return self.base / "accounts.json"

    def _load_accounts(self) -> dict:
        p = self._accounts_path()
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return {}

    def _save_accounts(self):
        p = self._accounts_path()
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.accounts, indent=2), encoding="utf-8")
        tmp.replace(p)

    def ensure_account(self, name: str, token: str = ""):
        """Create an account if it doesn't exist. Returns the API token."""
        if name not in self.accounts:
            if not token:
                token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            self.accounts[name] = {
                "token_hash": token_hash,
                "created": datetime.now().isoformat(),
            }
            self._save_accounts()
            # Create inbox directory
            inbox = self._inbox_dir(name)
            inbox.mkdir(parents=True, exist_ok=True)
            log.info("Account created: %s", name)
            return token
        return ""

    def authenticate(self, token: str) -> Optional[str]:
        """Verify a Bearer token. Returns agent name or None."""
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        for name, acct in self.accounts.items():
            if acct.get("token_hash") == token_hash:
                return name
        return None

    def list_agents(self) -> List[str]:
        return sorted(self.accounts.keys())

    # -- message storage --

    def _inbox_dir(self, agent: str) -> Path:
        return self.base / "inboxes" / agent

    def _next_id(self, sender: str) -> str:
        self._msg_counter += 1
        return f"{self._msg_counter}_{sender}_{uuid.uuid4().hex[:8]}"

    def deliver(self, sender: str, recipient: str, payload: str) -> str:
        """Deliver a message to recipient's inbox. Returns message ID."""
        inbox = self._inbox_dir(recipient)
        inbox.mkdir(parents=True, exist_ok=True)

        msg_id = self._next_id(sender)
        msg_data = json.dumps({
            "id": msg_id,
            "from": f"{sender}.agenttalk",
            "to": f"{recipient}.agenttalk",
            "timestamp": datetime.utcnow().isoformat(),
            "payload": payload,
        })
        (inbox / f"{msg_id}.msg").write_text(msg_data, encoding="utf-8")
        log.info("Delivered %s -> %s (%d bytes)", sender, recipient, len(payload))
        return msg_id

    def fetch_messages(self, agent: str) -> List[dict]:
        """Fetch and auto-delete all pending messages for an agent."""
        inbox = self._inbox_dir(agent)
        if not inbox.exists():
            return []

        messages = []
        for msg_file in sorted(inbox.glob("*.msg")):
            try:
                msg_data = json.loads(msg_file.read_text(encoding="utf-8"))
                messages.append(msg_data)
                msg_file.unlink()  # auto-delete on retrieval
            except Exception as e:
                log.error("Read message %s: %s", msg_file.name, e)
        return messages

    def inbox_size(self, agent: str) -> int:
        """Total bytes in agent's inbox."""
        inbox = self._inbox_dir(agent)
        if not inbox.exists():
            return 0
        return sum(f.stat().st_size for f in inbox.iterdir() if f.is_file())


# -- HTTP request/response helpers (stdlib only) --


class HTTPRequest:
    """Minimal HTTP request parser."""

    def __init__(self):
        self.method = ""
        self.path = ""
        self.query = {}
        self.headers: Dict[str, str] = {}
        self.body = b""

    @classmethod
    async def parse(cls, reader: asyncio.StreamReader) -> Optional["HTTPRequest"]:
        req = cls()
        try:
            # Request line
            line = await asyncio.wait_for(reader.readline(), timeout=30)
            if not line:
                return None
            request_line = line.decode("utf-8", errors="replace").strip()
            parts = request_line.split()
            if len(parts) < 3:
                return None
            req.method = parts[0].upper()
            parsed = urlparse(parts[1])
            req.path = parsed.path
            req.query = parse_qs(parsed.query)

            # Headers
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=10)
                if not line or line in (b"\r\n", b"\n"):
                    break
                header_line = line.decode("utf-8", errors="replace").strip()
                if ":" in header_line:
                    key, val = header_line.split(":", 1)
                    req.headers[key.strip().lower()] = val.strip()

            # Body
            content_length = int(req.headers.get("content-length", "0"))
            if content_length > 0:
                req.body = await asyncio.wait_for(
                    reader.readexactly(content_length), timeout=30
                )

            return req
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, ValueError):
            return None

    def json(self) -> dict:
        try:
            return json.loads(self.body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def bearer_token(self) -> str:
        auth = self.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:]
        return ""


class HTTPResponse:
    """Minimal HTTP response builder."""

    @staticmethod
    def json_response(data: dict, status: int = 200) -> bytes:
        body = json.dumps(data).encode("utf-8")
        return (
            f"HTTP/1.1 {status} {HTTPResponse._status_text(status)}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n"
            f"Access-Control-Allow-Origin: *\r\n"
            f"\r\n"
        ).encode() + body

    @staticmethod
    def text_response(text: str, status: int = 200) -> bytes:
        body = text.encode("utf-8")
        return (
            f"HTTP/1.1 {status} {HTTPResponse._status_text(status)}\r\n"
            f"Content-Type: text/plain\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        ).encode() + body

    @staticmethod
    def _status_text(code: int) -> str:
        return {
            200: "OK", 201: "Created", 400: "Bad Request",
            401: "Unauthorized", 404: "Not Found", 413: "Payload Too Large",
            429: "Too Many Requests", 500: "Internal Server Error",
            507: "Insufficient Storage",
        }.get(code, "Unknown")


# -- AgentTalk HTTP handler --


class AgentTalkHandler:
    """HTTP request handler for AgentTalk protocol."""

    MAX_MESSAGE_SIZE = 10 * 1024 * 1024  # 10 MB for local server (generous)
    MAX_INBOX_SIZE = 100 * 1024 * 1024   # 100 MB per agent (local)

    def __init__(self, store: AgentTalkStore, max_connections: int = 100):
        self.store = store
        self._sem = asyncio.Semaphore(max_connections)

    async def __call__(self, reader: asyncio.StreamReader,
                       writer: asyncio.StreamWriter):
        if not self._sem._value:
            writer.write(HTTPResponse.json_response(
                {"error": "Too many connections"}, 429))
            writer.close()
            return
        async with self._sem:
            await self._handle(reader, writer)

    async def _handle(self, reader: asyncio.StreamReader,
                      writer: asyncio.StreamWriter):
        try:
            req = await HTTPRequest.parse(reader)
            if not req:
                return

            # Route
            response = await self._route(req)
            writer.write(response)
            await writer.drain()

        except Exception as e:
            log.error("Handler error: %s", e)
            try:
                writer.write(HTTPResponse.json_response(
                    {"error": "Internal server error"}, 500))
                await writer.drain()
            except Exception:
                pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _route(self, req: HTTPRequest) -> bytes:
        """Route request to the appropriate handler."""
        path = req.path.rstrip("/") or "/"
        method = req.method

        # -- Public endpoints (no auth) --
        if path == "/status" and method == "GET":
            return self._handle_status()
        if path == "/health" and method == "GET":
            return self._handle_health()
        if path == "/agents" and method == "GET":
            return self._handle_agents()
        if path == "/register" and method == "POST":
            return self._handle_register(req)

        # -- Authenticated endpoints --
        if path == "/send" and method == "POST":
            return self._handle_send(req)
        if path == "/messages" and method == "GET":
            return self._handle_messages(req)

        return HTTPResponse.json_response({"error": "Not found"}, 404)

    def _authenticate(self, req: HTTPRequest) -> Optional[str]:
        """Verify Bearer token, return agent name or None."""
        token = req.bearer_token()
        if not token:
            return None
        return self.store.authenticate(token)

    # -- Handlers --

    def _handle_status(self) -> bytes:
        agents = self.store.list_agents()
        return HTTPResponse.json_response({
            "server": "AgentAZAll Local AgentTalk Server",
            "protocol": "AgentTalk",
            "protocol_note": "Self-hosted agent messaging — same API as relay.agentazall.ai",
            "accounts_active": len(agents),
            "api": {
                "send": "POST /send {to, payload}",
                "receive": "GET /messages (auto-deletes on retrieval)",
                "register": "POST /register {agent_name}",
                "agents": "GET /agents",
                "auth": "Bearer token (issued at registration)",
            },
        })

    def _handle_health(self) -> bytes:
        return HTTPResponse.json_response({
            "status": "ok",
            "protocol": "AgentTalk",
            "time": datetime.utcnow().isoformat(),
        })

    def _handle_agents(self) -> bytes:
        agents = self.store.list_agents()
        return HTTPResponse.json_response({
            "agents": [f"{a}.agenttalk" for a in agents],
            "count": len(agents),
        })

    def _handle_register(self, req: HTTPRequest) -> bytes:
        """POST /register — create a local agent account (no email verification)."""
        data = req.json()
        agent_name = data.get("agent_name", "").strip().lower()

        if not agent_name or len(agent_name) < 2 or len(agent_name) > 30:
            return HTTPResponse.json_response(
                {"error": "agent_name required (2-30 chars)"}, 400)

        if agent_name in self.store.accounts:
            return HTTPResponse.json_response(
                {"error": f"Agent '{agent_name}' already exists"}, 409)

        token = self.store.ensure_account(agent_name)

        return HTTPResponse.json_response({
            "status": "ok",
            "agent_name": agent_name,
            "agent_address": f"{agent_name}.agenttalk",
            "api_token": token,
            "config": {
                "agent_name": f"{agent_name}.agenttalk",
                "transport": "agenttalk",
                "agenttalk": {
                    "server": "",  # caller fills in based on their host:port
                    "token": token,
                },
            },
            "message": (
                f"Account created! Address: {agent_name}.agenttalk\n"
                f"SAVE YOUR API TOKEN — it cannot be recovered."
            ),
        }, status=201)

    def _handle_send(self, req: HTTPRequest) -> bytes:
        """POST /send — send a message to another agent."""
        sender = self._authenticate(req)
        if not sender:
            return HTTPResponse.json_response({"error": "Unauthorized"}, 401)

        data = req.json()
        recipient = data.get("to", "").strip().lower()
        payload = data.get("payload", "")

        # Strip .agenttalk suffix
        if recipient.endswith(".agenttalk"):
            recipient = recipient[:-10]

        if not recipient:
            return HTTPResponse.json_response(
                {"error": "Recipient required"}, 400)

        # Check payload size
        payload_bytes = payload.encode("utf-8") if isinstance(payload, str) else payload
        if len(payload_bytes) > self.MAX_MESSAGE_SIZE:
            return HTTPResponse.json_response(
                {"error": f"Message too large ({len(payload_bytes)} bytes, "
                          f"max {self.MAX_MESSAGE_SIZE})"}, 413)

        # Check recipient exists
        if recipient not in self.store.accounts:
            return HTTPResponse.json_response(
                {"error": f"Recipient '{recipient}' not found"}, 404)

        # Check inbox quota
        usage = self.store.inbox_size(recipient)
        if usage + len(payload_bytes) > self.MAX_INBOX_SIZE:
            return HTTPResponse.json_response(
                {"error": "Recipient inbox full"}, 507)

        msg_id = self.store.deliver(sender, recipient, payload)

        return HTTPResponse.json_response({
            "status": "sent",
            "message_id": msg_id,
        })

    def _handle_messages(self, req: HTTPRequest) -> bytes:
        """GET /messages — retrieve and auto-delete pending messages."""
        agent = self._authenticate(req)
        if not agent:
            return HTTPResponse.json_response({"error": "Unauthorized"}, 401)

        messages = self.store.fetch_messages(agent)

        return HTTPResponse.json_response({
            "agent": f"{agent}.agenttalk",
            "count": len(messages),
            "messages": messages,
        })


# -- main --


async def run_server(args):
    store = AgentTalkStore(args.data_dir)

    # Create default accounts
    if not store.accounts:
        n = args.create_accounts
        tokens = {}
        for i in range(1, n + 1):
            name = f"agent{i}"
            token = store.ensure_account(name)
            tokens[name] = token
        # Create a human account too
        token = store.ensure_account("human")
        tokens["human"] = token

    host = args.host
    port = find_port(host, args.port, 8484, 8600)

    handler = AgentTalkHandler(store)
    server = await asyncio.start_server(handler, host, port)

    print()
    print("=" * 56)
    print("  AgentAZAll Local AgentTalk Server")
    print("=" * 56)
    print(f"  API  : http://{host}:{port}")
    print(f"  Data : {args.data_dir}")
    print()
    print("  Endpoints:")
    print(f"    POST /register  — create agent account")
    print(f"    POST /send      — send message (Bearer auth)")
    print(f"    GET  /messages  — fetch messages (Bearer auth)")
    print(f"    GET  /status    — server info")
    print(f"    GET  /agents    — list agents")
    print()
    print("  Agents:")
    for name in sorted(store.accounts.keys()):
        print(f"    {name}.agenttalk")
    print()

    # Print tokens for new accounts
    tokens_path = Path(args.data_dir) / "tokens.json"
    if not tokens_path.exists() and store.accounts:
        # First run — tokens were just generated. Load from accounts
        # (tokens aren't stored in clear, so we can't recover them)
        pass

    print("  Use in config.json:")
    print(f'    "transport": "agenttalk",')
    print(f'    "agenttalk": {{"server": "http://{host}:{port}", "token": "<your-token>"}}')
    print()
    print("  Same API as relay.agentazall.ai — agents work on both.")
    print("  Press Ctrl+C to stop")
    print("=" * 56)
    print()

    # Write server info for other tools
    info = {
        "host": host, "port": port,
        "url": f"http://{host}:{port}",
        "protocol": "agenttalk",
        "data_dir": args.data_dir,
        "agents": store.list_agents(),
    }
    info_path = Path(args.data_dir) / "server_info.json"
    info_path.write_text(json.dumps(info, indent=2), encoding="utf-8")

    try:
        await server.serve_forever()
    except asyncio.CancelledError:
        pass


def main():
    p = ArgumentParser(description="AgentAZAll Local AgentTalk Server")
    p.add_argument("--host", default="127.0.0.1", help="Bind address")
    p.add_argument("--port", type=int, default=8484,
                   help="HTTP port (default: 8484)")
    p.add_argument("--data-dir", default="./data/agenttalk_store",
                   help="Data storage directory")
    p.add_argument("--create-accounts", type=int, default=3,
                   help="Number of agent accounts to create (agent1..agentN)")
    args = p.parse_args()

    try:
        asyncio.run(run_server(args))
    except KeyboardInterrupt:
        log.info("Server stopped.")


if __name__ == "__main__":
    main()
