"""AgentAZAll MCP server — persistent memory & communication for Claude.

Exposes AgentAZAll's full feature set as MCP tools + resources:
- remember/recall: persistent memory that survives context resets
- send/inbox: inter-agent messaging across three transports
- whoami/doing: agent identity and state tracking

Works with Claude Code, Claude Desktop, and any MCP-compatible client.

Usage:
    agentazall mcp-shim              # start MCP server on stdio
    claude mcp add agentazall -- agentazall mcp-shim
"""

import json
import os
import sys
import threading
import time
from datetime import datetime
from io import StringIO
from pathlib import Path

from .config import INBOX, REMEMBER, REMEMBER_INDEX, VERSION, load_config
from .helpers import (
    agent_base, agent_day, date_dirs, ensure_dirs,
    sanitize, today_str,
)
from .index import build_index, build_remember_index

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
                    "tools": {},
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

        # ── Tool listing ─────────────────────────────────────────────
        if method == "tools/list":
            return _ok(id, {"tools": self._get_tools()})

        # ── Tool execution ───────────────────────────────────────────
        if method == "tools/call":
            params = msg.get("params", {})
            name = params.get("name", "")
            args = params.get("arguments", {})
            try:
                result = self._execute_tool(name, args)
                return _ok(id, {
                    "content": [{"type": "text", "text": result}],
                })
            except Exception as exc:
                return _ok(id, {
                    "content": [{"type": "text", "text": f"Error: {exc}"}],
                    "isError": True,
                })

        # Unknown method
        if id is not None:
            return _err(id, -32601, f"Method not found: {method}")
        return None  # ignore unknown notifications

    # ── Tool definitions ───────────────────────────────────────────────

    def _get_tools(self):
        return [
            {
                "name": "remember",
                "description": "Store a memory permanently. Survives context resets, session restarts, and model swaps. Use to store decisions, insights, user preferences, or anything worth remembering.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "The content to remember"},
                        "title": {"type": "string", "description": "Short slug title (e.g. 'db-choice', 'user-preference')"},
                    },
                    "required": ["text", "title"],
                },
            },
            {
                "name": "recall",
                "description": "Search persistent memories. Empty query returns all memory titles. Provide a query to filter by keyword. Memories persist across sessions.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query (empty = list all)"},
                    },
                },
            },
            {
                "name": "send",
                "description": "Send a message to another agent or person via AgentAZAll. Messages are delivered via HTTPS relay, email, or FTP depending on transport config.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string", "description": "Recipient address (e.g. 'agent.agenttalk' or 'user@email.com')"},
                        "subject": {"type": "string", "description": "Message subject"},
                        "body": {"type": "string", "description": "Message body"},
                    },
                    "required": ["to", "subject", "body"],
                },
            },
            {
                "name": "inbox",
                "description": "Check inbox for new messages from other agents or people.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "whoami",
                "description": "Get or set agent identity. Without text, returns current identity. With text, updates identity.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "New identity text (omit to just read current)"},
                    },
                },
            },
            {
                "name": "doing",
                "description": "Get or set what the agent is currently working on. Persists across sessions.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Current task description (omit to just read)"},
                    },
                },
            },
        ]

    # ── Tool execution ───────────────────────────────────────────────

    def _execute_tool(self, name, args):
        if not self._cfg:
            return "Error: MCP server not initialized."

        if name == "remember":
            text = args.get("text", "")
            title = args.get("title", "untitled")
            d = today_str()
            ensure_dirs(self._cfg, d)
            rem_dir = agent_day(self._cfg, d) / REMEMBER
            slug = sanitize(title)
            fpath = rem_dir / f"{slug}.txt"
            if fpath.exists():
                old = fpath.read_text(encoding="utf-8")
                fpath.write_text(old + "\n" + text, encoding="utf-8")
            else:
                fpath.write_text(text, encoding="utf-8")
            build_index(self._cfg, d)
            build_remember_index(self._cfg)
            return f"Memory stored: {slug}"

        if name == "recall":
            query = args.get("query", "")
            b = agent_base(self._cfg)
            build_remember_index(self._cfg)
            idx_path = b / REMEMBER_INDEX
            if not idx_path.exists():
                return "No memories stored yet."
            if not query:
                text = idx_path.read_text(encoding="utf-8")
                if len(text) > 8000:
                    lines = text.split("\n")
                    text = "\n".join(lines[-200:])
                return text
            # Filtered search
            q = query.lower()
            results = []
            for d in sorted(date_dirs(self._cfg), reverse=True):
                rem_dir = b / d / REMEMBER
                if not rem_dir.exists():
                    continue
                for f in sorted(rem_dir.glob("*.txt")):
                    content = f.read_text(encoding="utf-8", errors="replace")
                    if q in content.lower() or q in f.stem.lower():
                        results.append(f"[{d}] {f.stem}\n  {content.strip()}")
            if not results:
                return f"No memories matching '{query}'."
            return f"Recall: '{query}' ({len(results)} found)\n\n" + "\n\n".join(results)

        if name == "send":
            to = args.get("to", "")
            subject = args.get("subject", "")
            body = args.get("body", "")
            from .commands.messaging import _queue_message
            _queue_message(self._cfg, to, subject, body)
            # Trigger daemon sync
            try:
                from .daemon import sync_once
                sync_once(self._cfg)
            except Exception:
                pass
            return f"Message queued to {to}: {subject}"

        if name == "inbox":
            return self._capture_inbox()

        if name == "whoami":
            from .helpers import agent_day as _ad
            text = args.get("text")
            d = today_str()
            ensure_dirs(self._cfg, d)
            whoami_dir = _ad(self._cfg, d) / "who_am_i"
            whoami_dir.mkdir(parents=True, exist_ok=True)
            fpath = whoami_dir / "identity.txt"
            if text:
                fpath.write_text(text, encoding="utf-8")
                return f"Identity updated: {text[:100]}"
            if fpath.exists():
                return fpath.read_text(encoding="utf-8")
            return "No identity set. Use whoami with text to set one."

        if name == "doing":
            from .helpers import agent_day as _ad
            text = args.get("text")
            d = today_str()
            ensure_dirs(self._cfg, d)
            doing_dir = _ad(self._cfg, d) / "what_am_i_doing"
            doing_dir.mkdir(parents=True, exist_ok=True)
            fpath = doing_dir / "tasks.txt"
            if text:
                fpath.write_text(text, encoding="utf-8")
                return f"Tasks updated: {text[:100]}"
            if fpath.exists():
                return fpath.read_text(encoding="utf-8")
            return "No current tasks. Use doing with text to set one."

        return f"Unknown tool: {name}"

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
