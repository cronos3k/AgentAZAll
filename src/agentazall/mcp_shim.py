"""Minimal MCP stdio server — the doorbell.

Pushes inbox notifications into any MCP-compatible LLM client's context.
Exposes one resource (agentazall://inbox) and watches for new messages.
No tools, no prompts, no sampling — just the doorbell.
"""

import json
import sys
import threading
import time
from io import StringIO
from pathlib import Path

from .config import INBOX, VERSION, load_config
from .helpers import agent_day, today_str

PROTOCOL_VERSION = "2025-03-26"

# ── JSON-RPC helpers ────────────────────────────────────────────────────────


def _ok(id, result):
    return {"jsonrpc": "2.0", "id": id, "result": result}


def _err(id, code, message):
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}


# ── The shim ────────────────────────────────────────────────────────────────


class McpShim:
    """Bare-minimum MCP server over stdio."""

    def __init__(self, poll_interval=5):
        self._poll_interval = poll_interval
        self._cfg = None
        self._running = False
        self._known_files = set()
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()

    # ── inbox snapshot ──────────────────────────────────────────────────

    def _today_inbox(self):
        """Return today's inbox Path, or None if config not loaded."""
        if not self._cfg:
            return None
        return agent_day(self._cfg) / INBOX

    def _capture_inbox(self):
        """Run _print_inbox and capture its stdout output."""
        from .commands.messaging import _print_inbox
        if not self._cfg:
            return "No config loaded."
        buf = StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = buf
            d = today_str()
            _print_inbox(self._cfg, d)
        finally:
            sys.stdout = old_stdout
        return buf.getvalue() or f"No messages for {d}."

    # ── poll loop (background thread) ───────────────────────────────────

    def _poll_loop(self):
        """Watch inbox for new .txt files, send notification on change."""
        first_scan = True
        while self._running:
            try:
                inbox = self._today_inbox()
                if inbox and inbox.exists():
                    current = set(f.name for f in inbox.glob("*.txt"))
                    if current != self._known_files:
                        if not first_scan and self._known_files is not None:
                            self._send_json({
                                "jsonrpc": "2.0",
                                "method": "notifications/resources/list_changed",
                            })
                            self._send_json({
                                "jsonrpc": "2.0",
                                "method": "notifications/resources/updated",
                                "params": {"uri": "agentazall://inbox"},
                            })
                        self._known_files = current
                        first_scan = False
                else:
                    first_scan = True
                    self._known_files = set()
            except Exception as exc:
                print(f"poll error: {exc}", file=sys.stderr)
            time.sleep(self._poll_interval)

    # ── stdio I/O ───────────────────────────────────────────────────────

    def _send_json(self, obj):
        """Write one JSON-RPC message to stdout (thread-safe)."""
        with self._write_lock:
            sys.stdout.write(json.dumps(obj) + "\n")
            sys.stdout.flush()

    def _handle(self, msg):
        """Dispatch one JSON-RPC message. Return response dict or None."""
        method = msg.get("method", "")
        id = msg.get("id")  # None for notifications

        if method == "initialize":
            self._cfg = load_config()
            return _ok(id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {
                    "resources": {
                        "subscribe": True,
                        "listChanged": True,
                    },
                },
                "serverInfo": {
                    "name": "agentazall",
                    "version": VERSION,
                },
            })

        if method == "notifications/initialized":
            # Client handshake done — start watching
            self._running = True
            t = threading.Thread(target=self._poll_loop, daemon=True)
            t.start()
            return None  # no response for notifications

        if method == "resources/list":
            name = "AgentAZAll Inbox"
            if self._cfg:
                name = f"Inbox — {self._cfg.get('agent_name', 'agent')}"
            return _ok(id, {
                "resources": [{
                    "uri": "agentazall://inbox",
                    "name": name,
                    "description": "Current inbox messages with previews. "
                                   "Read ALL new messages before responding.",
                    "mimeType": "text/plain",
                }],
            })

        if method == "resources/read":
            uri = (msg.get("params") or {}).get("uri", "")
            if uri != "agentazall://inbox":
                return _err(id, -32602, f"Unknown resource: {uri}")
            text = self._capture_inbox()
            return _ok(id, {
                "contents": [{
                    "uri": "agentazall://inbox",
                    "mimeType": "text/plain",
                    "text": text,
                }],
            })

        if method == "resources/subscribe":
            # Accept subscription — we'll send updates via poll loop
            return _ok(id, {})

        if method == "resources/unsubscribe":
            return _ok(id, {})

        if method == "ping":
            return _ok(id, {})

        # Unknown method
        if id is not None:
            return _err(id, -32601, f"Method not found: {method}")
        return None  # ignore unknown notifications

    def run(self):
        """Main stdio loop — read JSON-RPC from stdin, respond on stdout."""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError as exc:
                self._send_json(_err(None, -32700, f"Parse error: {exc}"))
                continue

            resp = self._handle(msg)
            if resp is not None:
                self._send_json(resp)

    def stop(self):
        self._running = False


# ── CLI entry point ─────────────────────────────────────────────────────────


def cmd_mcp_shim(args):
    """Run the MCP doorbell server on stdio."""
    interval = getattr(args, "poll_interval", 5) or 5
    shim = McpShim(poll_interval=interval)
    try:
        shim.run()
    except (KeyboardInterrupt, EOFError):
        shim.stop()
