"""Tests for agentazall.multi_transport — config migration + array management."""

import copy

from agentazall.multi_transport import (
    migrate_config, add_relay, remove_relay,
    add_email_account, add_ftp_server, transport_summary,
)


# ── sample configs ──────────────────────────────────────────────────────────

LEGACY_EMAIL_ONLY = {
    "agent_name": "bob@localhost",
    "transport": "email",
    "email": {
        "imap_server": "mail.example.com",
        "imap_port": 993,
        "smtp_server": "mail.example.com",
        "smtp_port": 587,
        "username": "bob@example.com",
        "password": "secret",
    },
    "ftp": {"host": "", "port": 21},
    "agenttalk": {"server": "", "token": ""},
}

LEGACY_BOTH = {
    "agent_name": "alice@localhost",
    "transport": "both",
    "email": {
        "imap_server": "imap.alice.io",
        "imap_port": 993,
        "username": "alice@alice.io",
        "password": "pw",
    },
    "ftp": {
        "host": "ftp.alice.io",
        "port": 21,
    },
    "agenttalk": {"server": "", "token": ""},
}

LEGACY_AGENTTALK = {
    "agent_name": "keel.abc123.agenttalk",
    "transport": "agenttalk",
    "email": {"imap_server": "", "username": ""},
    "ftp": {"host": "", "port": 21},
    "agenttalk": {
        "server": "https://relay.agentazall.ai:8443",
        "token": "tok_abc123",
    },
}


# ── migration ───────────────────────────────────────────────────────────────

class TestMigration:

    def test_email_only(self):
        cfg = migrate_config(copy.deepcopy(LEGACY_EMAIL_ONLY))
        assert len(cfg["email_accounts"]) == 1
        assert cfg["email_accounts"][0]["imap_server"] == "mail.example.com"
        assert cfg["ftp_servers"] == []
        assert cfg["relays"] == []
        # Legacy key unchanged
        assert cfg["email"]["imap_server"] == "mail.example.com"

    def test_both_transports(self):
        cfg = migrate_config(copy.deepcopy(LEGACY_BOTH))
        assert len(cfg["email_accounts"]) == 1
        assert len(cfg["ftp_servers"]) == 1
        assert cfg["ftp_servers"][0]["host"] == "ftp.alice.io"
        assert cfg["relays"] == []

    def test_agenttalk(self):
        cfg = migrate_config(copy.deepcopy(LEGACY_AGENTTALK))
        assert len(cfg["relays"]) == 1
        assert cfg["relays"][0]["server"] == "https://relay.agentazall.ai:8443"
        assert cfg["relays"][0]["token"] == "tok_abc123"
        assert cfg["email_accounts"] == []

    def test_idempotent(self):
        cfg = migrate_config(copy.deepcopy(LEGACY_AGENTTALK))
        cfg2 = migrate_config(copy.deepcopy(cfg))
        assert cfg2["relays"] == cfg["relays"]
        assert cfg2["email_accounts"] == cfg["email_accounts"]
        assert cfg2["ftp_servers"] == cfg["ftp_servers"]

    def test_already_migrated_preserves_arrays(self):
        cfg = copy.deepcopy(LEGACY_AGENTTALK)
        cfg["relays"] = [
            {"server": "https://relay1.example.com", "token": "t1"},
            {"server": "https://relay2.example.com", "token": "t2"},
        ]
        cfg = migrate_config(cfg)
        assert len(cfg["relays"]) == 2  # not overwritten

    def test_empty_config(self):
        cfg = migrate_config({
            "email": {}, "ftp": {}, "agenttalk": {},
        })
        assert cfg["email_accounts"] == []
        assert cfg["ftp_servers"] == []
        assert cfg["relays"] == []


# ── relay management ────────────────────────────────────────────────────────

class TestRelayManagement:

    def test_add_relay(self):
        cfg = {"relays": [], "agenttalk": {"server": "", "token": ""}}
        cfg = add_relay(cfg, "https://relay1.com:8443", "tok1")
        assert len(cfg["relays"]) == 1
        assert cfg["relays"][0]["server"] == "https://relay1.com:8443"
        # Legacy key synced
        assert cfg["agenttalk"]["server"] == "https://relay1.com:8443"

    def test_add_duplicate_updates(self):
        cfg = {"relays": [{"server": "https://r1.com", "token": "old"}],
               "agenttalk": {"server": "https://r1.com", "token": "old"}}
        cfg = add_relay(cfg, "https://r1.com", "new_token")
        assert len(cfg["relays"]) == 1
        assert cfg["relays"][0]["token"] == "new_token"

    def test_add_second_relay(self):
        cfg = {"relays": [{"server": "https://r1.com", "token": "t1"}],
               "agenttalk": {"server": "https://r1.com", "token": "t1"}}
        cfg = add_relay(cfg, "https://r2.com", "t2")
        assert len(cfg["relays"]) == 2
        # Legacy key still points to first relay
        assert cfg["agenttalk"]["server"] == "https://r1.com"

    def test_remove_relay(self):
        cfg = {"relays": [
            {"server": "https://r1.com", "token": "t1"},
            {"server": "https://r2.com", "token": "t2"},
        ], "agenttalk": {"server": "https://r1.com", "token": "t1"}}
        cfg = remove_relay(cfg, "https://r1.com")
        assert len(cfg["relays"]) == 1
        assert cfg["relays"][0]["server"] == "https://r2.com"
        # Legacy key updated to next relay
        assert cfg["agenttalk"]["server"] == "https://r2.com"

    def test_remove_last_relay(self):
        cfg = {"relays": [{"server": "https://r1.com", "token": "t1"}],
               "agenttalk": {"server": "https://r1.com", "token": "t1"}}
        cfg = remove_relay(cfg, "https://r1.com")
        assert cfg["relays"] == []
        assert cfg["agenttalk"]["server"] == ""

    def test_remove_nonexistent(self):
        cfg = {"relays": [{"server": "https://r1.com"}]}
        cfg = remove_relay(cfg, "https://nonexistent.com")
        assert len(cfg["relays"]) == 1


# ── email / ftp management ──────────────────────────────────────────────────

class TestEmailFtpManagement:

    def test_add_email(self):
        cfg = {"email_accounts": [], "email": {}}
        acct = {"imap_server": "imap.gmail.com", "username": "me@gmail.com"}
        cfg = add_email_account(cfg, acct)
        assert len(cfg["email_accounts"]) == 1
        assert cfg["email"]["imap_server"] == "imap.gmail.com"

    def test_add_duplicate_email_updates(self):
        cfg = {"email_accounts": [
            {"imap_server": "imap.gmail.com", "username": "me@gmail.com", "password": "old"}
        ], "email": {}}
        cfg = add_email_account(cfg, {
            "imap_server": "imap.gmail.com", "username": "me@gmail.com", "password": "new"
        })
        assert len(cfg["email_accounts"]) == 1
        assert cfg["email_accounts"][0]["password"] == "new"

    def test_add_ftp(self):
        cfg = {"ftp_servers": [], "ftp": {}}
        cfg = add_ftp_server(cfg, {"host": "ftp.example.com", "port": 21})
        assert len(cfg["ftp_servers"]) == 1
        assert cfg["ftp"]["host"] == "ftp.example.com"

    def test_add_duplicate_ftp_updates(self):
        cfg = {"ftp_servers": [
            {"host": "ftp.example.com", "port": 21, "user": "old"}
        ], "ftp": {}}
        cfg = add_ftp_server(cfg, {"host": "ftp.example.com", "port": 21, "user": "new"})
        assert len(cfg["ftp_servers"]) == 1
        assert cfg["ftp_servers"][0]["user"] == "new"


# ── transport summary ───────────────────────────────────────────────────────

class TestTransportSummary:

    def test_no_transports(self):
        assert transport_summary({}) == "No transports configured."

    def test_all_transports(self):
        cfg = {
            "relays": [{"server": "r1.com"}, {"server": "r2.com"}],
            "email_accounts": [{"username": "me@x.com"}],
            "ftp_servers": [{"host": "ftp.x.com", "port": 21}],
        }
        s = transport_summary(cfg)
        assert "2 relay(s)" in s
        assert "1 account(s)" in s
        assert "1 server(s)" in s
