"""Tests for agentazall.config module."""

import json
import os
from pathlib import Path

from agentazall.config import (
    AGENT_LEVEL_DIRS,
    ALL_SUBDIRS,
    DEFAULT_CONFIG,
    INBOX,
    NOTES,
    OUTBOX,
    REMEMBER,
    SENT,
    SKILLS,
    TOOLS,
    VERSION,
    WHAT_AM_I_DOING,
    WHO_AM_I,
    _deep_merge,
    load_config,
    resolve_config_path,
    save_config,
)


class TestConstants:
    def test_version_format(self):
        assert VERSION
        assert "." in VERSION

    def test_folder_constants(self):
        assert INBOX == "inbox"
        assert OUTBOX == "outbox"
        assert SENT == "sent"
        assert WHO_AM_I == "who_am_i"
        assert WHAT_AM_I_DOING == "what_am_i_doing"
        assert NOTES == "notes"
        assert REMEMBER == "remember"
        assert SKILLS == "skills"
        assert TOOLS == "tools"

    def test_all_subdirs_tuple(self):
        assert isinstance(ALL_SUBDIRS, tuple)
        assert INBOX in ALL_SUBDIRS
        assert REMEMBER in ALL_SUBDIRS

    def test_agent_level_dirs(self):
        assert SKILLS in AGENT_LEVEL_DIRS
        assert TOOLS in AGENT_LEVEL_DIRS


class TestDeepMerge:
    def test_flat_merge(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        base = {"x": {"a": 1, "b": 2}}
        override = {"x": {"b": 3}}
        result = _deep_merge(base, override)
        assert result == {"x": {"a": 1, "b": 3}}

    def test_does_not_mutate_base(self):
        base = {"a": 1}
        override = {"a": 2}
        _deep_merge(base, override)
        assert base["a"] == 1


class TestConfigResolution:
    def test_env_config(self, tmp_path, monkeypatch):
        p = tmp_path / "custom.json"
        p.write_text("{}", encoding="utf-8")
        monkeypatch.setenv("AGENTAZALL_CONFIG", str(p))
        monkeypatch.delenv("AGENTAZALL_ROOT", raising=False)
        assert resolve_config_path() == p

    def test_env_root(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AGENTAZALL_CONFIG", raising=False)
        monkeypatch.setenv("AGENTAZALL_ROOT", str(tmp_path))
        assert resolve_config_path() == tmp_path / "config.json"

    def test_cwd_fallback(self, monkeypatch):
        monkeypatch.delenv("AGENTAZALL_CONFIG", raising=False)
        monkeypatch.delenv("AGENTAZALL_ROOT", raising=False)
        result = resolve_config_path()
        assert result.name == "config.json"


class TestLoadSaveConfig:
    def test_load_config(self, tmp_project):
        cfg = load_config()
        assert cfg["agent_name"] == "test-agent@localhost"
        assert cfg["transport"] == "email"

    def test_save_and_reload(self, tmp_project):
        cfg = load_config()
        cfg["agent_name"] = "modified@localhost"
        save_config(cfg)
        cfg2 = load_config()
        assert cfg2["agent_name"] == "modified@localhost"

    def test_internal_keys_not_saved(self, tmp_project):
        cfg = load_config()
        save_config(cfg)
        config_path = Path(os.environ["AGENTAZALL_CONFIG"])
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        assert "_config_path" not in raw

    def test_default_config_has_required_keys(self):
        assert "agent_name" in DEFAULT_CONFIG
        assert "email" in DEFAULT_CONFIG
        assert "ftp" in DEFAULT_CONFIG
        assert "transport" in DEFAULT_CONFIG
