"""Tests for agentazall.index module."""


from agentazall.config import INBOX, REMEMBER
from agentazall.helpers import agent_day, ensure_dirs
from agentazall.index import build_index, build_remember_index
from agentazall.messages import format_message


class TestBuildIndex:
    def test_creates_index_file(self, cfg):
        d = "2026-03-08"
        ensure_dirs(cfg, d)
        idx = build_index(cfg, d)
        assert idx is not None
        assert idx.exists()
        content = idx.read_text(encoding="utf-8")
        assert "AgentAZAll Index" in content
        assert "INBOX" in content

    def test_index_includes_messages(self, cfg):
        d = "2026-03-08"
        ensure_dirs(cfg, d)
        # Create a test message
        content_str, msg_id = format_message(
            "sender@localhost", "test-agent@localhost",
            "Test Subject", "Body"
        )
        inbox = agent_day(cfg, d) / INBOX
        (inbox / f"{msg_id}.txt").write_text(content_str, encoding="utf-8")

        idx = build_index(cfg, d)
        content = idx.read_text(encoding="utf-8")
        assert "Test Subject" in content
        assert "INBOX (1)" in content

    def test_nonexistent_date(self, cfg):
        idx = build_index(cfg, "1999-01-01")
        assert idx is None


class TestBuildRememberIndex:
    def test_empty(self, cfg):
        ensure_dirs(cfg, "2026-03-08")
        idx = build_remember_index(cfg)
        if idx:
            content = idx.read_text(encoding="utf-8")
            assert "Total memories: 0" in content

    def test_with_memories(self, cfg):
        d = "2026-03-08"
        ensure_dirs(cfg, d)
        rem_dir = agent_day(cfg, d) / REMEMBER
        (rem_dir / "test-memory.txt").write_text(
            "This is a test memory about Python.", encoding="utf-8"
        )

        idx = build_remember_index(cfg)
        assert idx is not None
        content = idx.read_text(encoding="utf-8")
        assert "test-memory" in content
        assert "Total memories: 1" in content
