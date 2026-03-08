"""Tests for agentoall.helpers module."""

import json
import re

from agentoall.config import ALL_SUBDIRS
from agentoall.helpers import (
    agent_base,
    agent_day,
    date_dirs,
    ensure_dirs,
    generate_id,
    now_str,
    safe_move,
    sanitize,
    today_str,
    validate_agent_key,
)


class TestDateHelpers:
    def test_today_str_format(self):
        result = today_str()
        assert re.match(r"\d{4}-\d{2}-\d{2}$", result)

    def test_now_str_format(self):
        result = now_str()
        assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", result)


class TestPathHelpers:
    def test_agent_base(self, cfg):
        result = agent_base(cfg)
        assert result.name == "test-agent@localhost"

    def test_agent_day(self, cfg):
        result = agent_day(cfg, "2026-01-15")
        assert result.name == "2026-01-15"
        assert result.parent.name == "test-agent@localhost"

    def test_agent_day_default(self, cfg):
        result = agent_day(cfg)
        assert re.match(r"\d{4}-\d{2}-\d{2}$", result.name)


class TestEnsureDirs:
    def test_creates_all_subdirs(self, cfg):
        root = ensure_dirs(cfg)
        for sub in ALL_SUBDIRS:
            assert (root / sub).exists()

    def test_creates_agent_level_dirs(self, cfg):
        ensure_dirs(cfg)
        base = agent_base(cfg)
        assert (base / "skills").exists()
        assert (base / "tools").exists()


class TestGenerateId:
    def test_length(self):
        result = generate_id("a@l", "b@l", "test")
        assert len(result) == 12

    def test_unique(self):
        id1 = generate_id("a@l", "b@l", "test")
        id2 = generate_id("a@l", "b@l", "test")
        assert id1 != id2  # includes random component


class TestSanitize:
    def test_basic(self):
        assert sanitize("hello-world.txt") == "hello-world.txt"

    def test_special_chars(self):
        result = sanitize("file name! @#$.txt")
        assert " " not in result
        assert "!" not in result
        assert "@" not in result


class TestSafeMove:
    def test_move(self, tmp_path):
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_text("content", encoding="utf-8")
        safe_move(str(src), str(dst))
        assert dst.exists()
        assert not src.exists()
        assert dst.read_text(encoding="utf-8") == "content"


class TestDateDirs:
    def test_empty(self, cfg):
        result = date_dirs(cfg)
        assert result == []

    def test_finds_dates(self, cfg):
        ensure_dirs(cfg, "2026-01-01")
        ensure_dirs(cfg, "2026-01-02")
        result = date_dirs(cfg)
        assert "2026-01-01" in result
        assert "2026-01-02" in result

    def test_ignores_non_dates(self, cfg):
        ensure_dirs(cfg)
        base = agent_base(cfg)
        (base / "not-a-date").mkdir(parents=True, exist_ok=True)
        result = date_dirs(cfg)
        assert "not-a-date" not in result


class TestValidateAgentKey:
    def test_no_key_file(self, cfg):
        assert validate_agent_key(cfg) is True

    def test_matching_key(self, cfg):
        ensure_dirs(cfg)
        base = agent_base(cfg)
        key_file = base / ".agent_key"
        key_file.write_text(json.dumps({
            "key": cfg["agent_key"],
        }), encoding="utf-8")
        assert validate_agent_key(cfg) is True

    def test_mismatched_key(self, cfg):
        ensure_dirs(cfg)
        base = agent_base(cfg)
        key_file = base / ".agent_key"
        key_file.write_text(json.dumps({
            "key": "wrong_key_value",
        }), encoding="utf-8")
        assert validate_agent_key(cfg) is False
