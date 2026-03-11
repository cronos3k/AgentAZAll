"""Tests for the MCP doorbell shim."""

import json
import os
import time
from pathlib import Path

import pytest

from agentazall.mcp_shim import McpShim, _ok, _err


@pytest.fixture
def shim(cfg):
    """Create a shim with config loaded."""
    s = McpShim(poll_interval=1)
    s._cfg = cfg
    return s


# ── JSON-RPC helpers ────────────────────────────────────────────────────────


def test_ok_format():
    r = _ok(1, {"foo": "bar"})
    assert r == {"jsonrpc": "2.0", "id": 1, "result": {"foo": "bar"}}


def test_err_format():
    r = _err(2, -32601, "not found")
    assert r == {"jsonrpc": "2.0", "id": 2, "error": {"code": -32601, "message": "not found"}}


# ── initialize ──────────────────────────────────────────────────────────────


def test_initialize(shim):
    msg = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
           "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                      "clientInfo": {"name": "test", "version": "0.1"}}}
    resp = shim._handle(msg)
    assert resp["id"] == 1
    result = resp["result"]
    assert result["protocolVersion"] == "2025-03-26"
    assert result["capabilities"]["resources"]["listChanged"] is True
    assert result["capabilities"]["resources"]["subscribe"] is True
    assert result["serverInfo"]["name"] == "agentazall"


# ── notifications/initialized ───────────────────────────────────────────────


def test_initialized_returns_none(shim):
    msg = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    resp = shim._handle(msg)
    assert resp is None
    # Should have started the poll thread
    assert shim._running is True
    shim.stop()


# ── resources/list ──────────────────────────────────────────────────────────


def test_resources_list(shim):
    msg = {"jsonrpc": "2.0", "id": 2, "method": "resources/list"}
    resp = shim._handle(msg)
    resources = resp["result"]["resources"]
    assert len(resources) == 1
    assert resources[0]["uri"] == "agentazall://inbox"
    assert resources[0]["mimeType"] == "text/plain"


# ── resources/read ──────────────────────────────────────────────────────────


def test_resources_read_inbox(shim, cfg):
    # Create an inbox directory with a test message
    from agentazall.helpers import agent_day, ensure_dirs, today_str
    d = today_str()
    ensure_dirs(cfg, d)
    inbox = agent_day(cfg, d) / "inbox"
    msg_file = inbox / "test123.txt"
    msg_file.write_text(
        "From: sender@test\nTo: test-agent@localhost\n"
        "Subject: Hello\nDate: 2026-01-01\nMessage-ID: test123\nStatus: new\n\n"
        "---\nHello world!", encoding="utf-8")

    msg = {"jsonrpc": "2.0", "id": 3, "method": "resources/read",
           "params": {"uri": "agentazall://inbox"}}
    resp = shim._handle(msg)
    contents = resp["result"]["contents"]
    assert len(contents) == 1
    assert "agentazall://inbox" == contents[0]["uri"]
    text = contents[0]["text"]
    assert "Hello" in text
    assert "sender@test" in text


def test_resources_read_unknown_uri(shim):
    msg = {"jsonrpc": "2.0", "id": 4, "method": "resources/read",
           "params": {"uri": "agentazall://unknown"}}
    resp = shim._handle(msg)
    assert resp["error"]["code"] == -32602


# ── resources/subscribe ─────────────────────────────────────────────────────


def test_resources_subscribe(shim):
    msg = {"jsonrpc": "2.0", "id": 5, "method": "resources/subscribe",
           "params": {"uri": "agentazall://inbox"}}
    resp = shim._handle(msg)
    assert resp["result"] == {}


# ── ping ────────────────────────────────────────────────────────────────────


def test_ping(shim):
    msg = {"jsonrpc": "2.0", "id": 6, "method": "ping"}
    resp = shim._handle(msg)
    assert resp["result"] == {}


# ── unknown method ──────────────────────────────────────────────────────────


def test_unknown_method(shim):
    msg = {"jsonrpc": "2.0", "id": 7, "method": "tools/list"}
    resp = shim._handle(msg)
    assert resp["error"]["code"] == -32601


def test_unknown_notification_ignored(shim):
    msg = {"jsonrpc": "2.0", "method": "notifications/something"}
    resp = shim._handle(msg)
    assert resp is None


# ── poll detection ──────────────────────────────────────────────────────────


def test_poll_detects_new_file(shim, cfg):
    from agentazall.helpers import agent_day, ensure_dirs, today_str
    d = today_str()
    ensure_dirs(cfg, d)
    inbox = agent_day(cfg, d) / "inbox"

    # Initial state: empty
    shim._known_files = set()

    # First poll — should update known_files but not notify (first scan logic)
    current = set(f.name for f in inbox.glob("*.txt"))
    assert current == set()

    # Add a file
    (inbox / "msg001.txt").write_text("From: a\nTo: b\nSubject: x\n\n---\nhi",
                                      encoding="utf-8")
    current2 = set(f.name for f in inbox.glob("*.txt"))
    assert current2 != shim._known_files
    assert "msg001.txt" in current2
