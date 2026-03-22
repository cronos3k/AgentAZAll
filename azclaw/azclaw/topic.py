"""AgentAZClaw — Topic/phase configuration.

Topics define what agents work on: phases with round ranges,
source files to examine, coherence probes, and role descriptions.
"""

import json
import os


class Topic:
    """A migration/task topic with phases and probes."""

    def __init__(self, data: dict):
        self.title = data.get("title", "Untitled")
        self.system_context = data.get("system_context", "")
        self.initial_prompt = data.get("initial_prompt", "Begin.")
        self.phases = data.get("phases", [])
        self.probes = data.get("coherence_probes", [])
        self.roles = data.get("agent_roles", {})
        self._data = data

    def get_phase(self, rnd: int) -> dict | None:
        """Get the phase config for a given round number."""
        for p in self.phases:
            r = p.get("rounds", [0, 0])
            if r[0] <= rnd <= r[1]:
                return p
        return None

    def get_probe(self, rnd: int) -> str | None:
        """Get coherence probe question if one is configured for this round."""
        for p in self.probes:
            if p.get("after_round") == rnd:
                return p.get("question")
        return None

    def get_role(self, role_key: str) -> str:
        """Get role description for an agent."""
        return self.roles.get(role_key, f"You are the {role_key}.")

    @property
    def max_round(self) -> int:
        """Last round defined by any phase."""
        if not self.phases:
            return 100
        return max(p["rounds"][1] for p in self.phases)

    @classmethod
    def from_file(cls, path: str) -> "Topic":
        with open(path, "r") as f:
            return cls(json.load(f))

    @classmethod
    def from_task(cls, task: str, max_rounds: int = 50) -> "Topic":
        """Create a simple single-phase topic from a task description."""
        return cls({
            "title": task[:80],
            "system_context": "",
            "initial_prompt": task,
            "phases": [{"name": "Main", "rounds": [1, max_rounds], "focus": task}],
            "coherence_probes": [],
            "agent_roles": {},
        })
