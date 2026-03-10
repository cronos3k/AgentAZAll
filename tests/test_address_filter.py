"""Tests for address_filter module."""

import pytest
from agentazall.address_filter import should_accept, get_filter_status


# ── should_accept ─────────────────────────────────────────────────────────────

class TestShouldAccept:
    """Test the should_accept gate function."""

    def test_default_config_accepts_all(self):
        """Empty default config accepts everything."""
        cfg = {}
        assert should_accept(cfg, "anyone@anywhere") is True

    def test_mode_off_accepts_all(self):
        cfg = {"address_filter": {"mode": "off"}}
        assert should_accept(cfg, "anyone@anywhere") is True

    def test_empty_sender_accepted(self):
        """Empty sender (local message) always accepted."""
        cfg = {"address_filter": {"mode": "blacklist", "blacklist": ["*"]}}
        assert should_accept(cfg, "") is True

    def test_blacklist_exact_match(self):
        cfg = {"address_filter": {
            "mode": "blacklist",
            "blacklist": ["spammer@host.local"],
            "whitelist": [],
            "log_blocked": False,
        }}
        assert should_accept(cfg, "spammer@host.local") is False
        assert should_accept(cfg, "friend@host.local") is True

    def test_blacklist_case_insensitive(self):
        cfg = {"address_filter": {
            "mode": "blacklist",
            "blacklist": ["Spammer@Host.Local"],
            "whitelist": [],
            "log_blocked": False,
        }}
        assert should_accept(cfg, "spammer@host.local") is False
        assert should_accept(cfg, "SPAMMER@HOST.LOCAL") is False

    def test_blacklist_wildcard_domain(self):
        cfg = {"address_filter": {
            "mode": "blacklist",
            "blacklist": ["*@spamhost.local"],
            "whitelist": [],
            "log_blocked": False,
        }}
        assert should_accept(cfg, "any@spamhost.local") is False
        assert should_accept(cfg, "friend@goodhost.local") is True

    def test_blacklist_wildcard_suffix(self):
        cfg = {"address_filter": {
            "mode": "blacklist",
            "blacklist": ["noisy-bot.*"],
            "whitelist": [],
            "log_blocked": False,
        }}
        assert should_accept(cfg, "noisy-bot.abc123.agenttalk") is False
        assert should_accept(cfg, "quiet-bot.abc123.agenttalk") is True

    def test_blacklist_transport_class(self):
        cfg = {"address_filter": {
            "mode": "blacklist",
            "blacklist": ["*.agenttalk"],
            "whitelist": [],
            "log_blocked": False,
        }}
        assert should_accept(cfg, "anyone.abc.agenttalk") is False
        assert should_accept(cfg, "friend@localhost") is True

    def test_whitelist_mode_accepts_listed(self):
        cfg = {"address_filter": {
            "mode": "whitelist",
            "blacklist": [],
            "whitelist": ["friend@host.local"],
            "log_blocked": False,
        }}
        assert should_accept(cfg, "friend@host.local") is True
        assert should_accept(cfg, "stranger@host.local") is False

    def test_whitelist_empty_accepts_all(self):
        """Empty whitelist in whitelist mode = safe default (accept all)."""
        cfg = {"address_filter": {
            "mode": "whitelist",
            "blacklist": [],
            "whitelist": [],
            "log_blocked": False,
        }}
        assert should_accept(cfg, "anyone@anywhere") is True

    def test_whitelist_wildcard(self):
        cfg = {"address_filter": {
            "mode": "whitelist",
            "blacklist": [],
            "whitelist": ["*@trusted.ai"],
            "log_blocked": False,
        }}
        assert should_accept(cfg, "agent1@trusted.ai") is True
        assert should_accept(cfg, "agent1@untrusted.ai") is False

    def test_blacklist_wins_over_whitelist(self):
        """If address is on both lists, blacklist wins."""
        cfg = {"address_filter": {
            "mode": "whitelist",
            "blacklist": ["blocked@trusted.ai"],
            "whitelist": ["*@trusted.ai"],
            "log_blocked": False,
        }}
        assert should_accept(cfg, "blocked@trusted.ai") is False
        assert should_accept(cfg, "friend@trusted.ai") is True


# ── get_filter_status ─────────────────────────────────────────────────────────

class TestGetFilterStatus:

    def test_defaults(self):
        status = get_filter_status({})
        assert status["mode"] == "blacklist"
        assert status["blacklist"] == []
        assert status["whitelist"] == []
        assert status["log_blocked"] is True

    def test_reflects_config(self):
        cfg = {"address_filter": {
            "mode": "whitelist",
            "blacklist": ["a@b"],
            "whitelist": ["c@d"],
            "log_blocked": False,
        }}
        status = get_filter_status(cfg)
        assert status["mode"] == "whitelist"
        assert status["blacklist"] == ["a@b"]
        assert status["whitelist"] == ["c@d"]
        assert status["log_blocked"] is False
