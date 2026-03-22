"""Tests for Agent class."""

import os
import pytest
from azclaw.agent import Agent, AgentStats


def test_agent_creation():
    a = Agent("test-agent", role="Test role", endpoint="http://localhost:8080/v1/chat/completions")
    assert a.name == "test-agent"
    assert a.role == "Test role"
    assert not a.can_write
    assert "recall" in a.tools
    assert "remember" in a.tools
    assert "write_file" not in a.tools


def test_agent_can_write():
    a = Agent("dev", can_write=True)
    assert a.can_write
    assert "write_file" in a.tools
    assert "run_python" in a.tools


def test_agent_capabilities():
    a = Agent("dev", can_write=True)
    assert a.capabilities == {"can_write": True}

    b = Agent("arch")
    assert b.capabilities == {"can_write": False}


def test_agent_root_created(tmp_path):
    root = str(tmp_path / "agents" / "test")
    a = Agent("test", root=root)
    assert os.path.isdir(root)


def test_agent_stats_default():
    s = AgentStats()
    assert s.completion_tokens == 0
    assert s.avg_speed == 0.0


def test_agent_stats_speed():
    s = AgentStats(completion_tokens=1000, elapsed=10.0)
    assert s.avg_speed == 100.0


def test_agent_repr():
    a = Agent("arch", endpoint="http://localhost:8080/v1/chat/completions")
    assert "arch" in repr(a)
    assert "WRITES" not in repr(a)

    b = Agent("dev", endpoint="http://localhost:8080/v1/chat/completions", can_write=True)
    assert "WRITES" in repr(b)
