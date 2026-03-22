"""Tests for Orchestrator and Topic."""

import pytest
from azclaw.topic import Topic
from azclaw.orchestrator import RunStats, _estimate_tokens


def test_topic_from_task():
    t = Topic.from_task("Build an API", max_rounds=30)
    assert t.title == "Build an API"
    assert t.max_round == 30
    assert t.initial_prompt == "Build an API"


def test_topic_phases():
    t = Topic({
        "title": "Test",
        "phases": [
            {"name": "Phase 1", "rounds": [1, 10], "focus": "Design"},
            {"name": "Phase 2", "rounds": [11, 20], "focus": "Code"},
        ],
        "coherence_probes": [
            {"after_round": 5, "question": "What's the DB choice?"},
        ],
    })
    assert t.get_phase(1)["name"] == "Phase 1"
    assert t.get_phase(15)["name"] == "Phase 2"
    assert t.get_phase(25) is None
    assert t.get_probe(5) == "What's the DB choice?"
    assert t.get_probe(3) is None
    assert t.max_round == 20


def test_topic_roles():
    t = Topic({
        "title": "Test",
        "agent_roles": {"architect": "You design systems."},
    })
    assert t.get_role("architect") == "You design systems."
    assert "reviewer" in t.get_role("reviewer")  # default fallback


def test_run_stats():
    s = RunStats()
    assert s.rounds == 0
    assert s.errors == 0
    s.rounds = 10
    s.total_comp = 50000
    assert s.total_comp == 50000


def test_estimate_tokens():
    assert _estimate_tokens("") == 0
    assert _estimate_tokens("hello world") >= 1
    assert _estimate_tokens("a" * 400) == 100
