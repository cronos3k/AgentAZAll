"""Pytest fixtures for AgentoAll tests."""

import json
import os

import pytest


@pytest.fixture
def tmp_project(tmp_path):
    """Create a temporary project directory with a valid config."""
    config = {
        "agent_name": "test-agent@localhost",
        "agent_key": "testkey1234567890abcdef12345678",
        "allow_memory_sharing": False,
        "mailbox_dir": str(tmp_path / "data" / "mailboxes"),
        "transport": "email",
        "sync_interval": 10,
        "log_file": str(tmp_path / "logs" / "agentoall.log"),
        "email": {
            "imap_server": "127.0.0.1",
            "imap_port": 1143,
            "imap_ssl": False,
            "imap_folder": "INBOX",
            "smtp_server": "127.0.0.1",
            "smtp_port": 2525,
            "smtp_ssl": False,
            "smtp_starttls": False,
            "pop3_server": "127.0.0.1",
            "pop3_port": 1110,
            "pop3_ssl": False,
            "use_pop3": False,
            "username": "test-agent@localhost",
            "password": "password",
            "sync_special_folders": True,
        },
        "ftp": {
            "host": "127.0.0.1",
            "port": 2121,
            "port_range": [2121, 2199],
            "user": "agentoftp",
            "password": "agentoftp_pass",
            "root": str(tmp_path / "data" / "ftp_root"),
        },
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    # Set env so load_config finds it
    os.environ["AGENTOALL_CONFIG"] = str(config_path)

    yield tmp_path

    # Cleanup
    os.environ.pop("AGENTOALL_CONFIG", None)


@pytest.fixture
def cfg(tmp_project):
    """Load config from the temporary project."""
    from agentoall.config import load_config
    return load_config()
