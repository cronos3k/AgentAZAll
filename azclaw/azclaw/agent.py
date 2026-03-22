"""AgentAZClaw — Agent class.

An Agent wraps an LLM endpoint with a role, tool permissions,
and its own AgentAZAll memory root. That's it.
"""

import os
from dataclasses import dataclass, field

from .llm import chat_completion, check_health


@dataclass
class AgentStats:
    """Cumulative stats for one agent across all rounds."""
    completion_tokens: int = 0
    prompt_tokens: int = 0
    elapsed: float = 0.0
    tool_calls: int = 0
    files_written: int = 0
    rounds: int = 0

    @property
    def avg_speed(self) -> float:
        return round(self.completion_tokens / self.elapsed, 1) if self.elapsed > 0 else 0.0


class Agent:
    """An LLM with a role, tool permissions, and persistent memory.

    Usage:
        agent = Agent("architect", role="Design the solution",
                      endpoint="http://localhost:8200/v1/chat/completions")
    """

    def __init__(
        self,
        name: str,
        role: str = "",
        endpoint: str = "http://localhost:8080/v1/chat/completions",
        model: str = "default",
        tools: list[str] | None = None,
        max_tokens: int = 8192,
        temperature: float = 0.7,
        root: str | None = None,
        can_write: bool = False,
    ):
        self.name = name
        self.role = role or f"You are {name}."
        self.endpoint = endpoint
        self.model = model
        self.tools = tools or ["recall", "remember", "read_file", "list_files"]
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.can_write = can_write or ("write_file" in self.tools)
        self.root = root or os.path.join(".", "agents", name)
        self.stats = AgentStats()

        # Auto-add write tools if can_write
        if self.can_write:
            for t in ("write_file", "run_python"):
                if t not in self.tools:
                    self.tools.append(t)

        # Ensure agent root exists
        os.makedirs(self.root, exist_ok=True)

    @property
    def capabilities(self) -> dict:
        """Capability flags for tool filtering."""
        return {"can_write": self.can_write}

    @property
    def context(self) -> dict:
        """Context dict injected into tool calls."""
        return {"agent_root": self.root}

    def is_healthy(self) -> bool:
        """Check if the LLM endpoint is reachable."""
        return check_health(self.endpoint)

    def chat(self, messages: list, tools: list | None = None) -> dict:
        """Send a chat completion request."""
        resp = chat_completion(
            endpoint=self.endpoint,
            messages=messages,
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            tools=tools,
            timeout=600,
        )

        # Track stats
        self.stats.prompt_tokens += resp.get("prompt_tokens", 0)
        self.stats.completion_tokens += resp.get("completion_tokens", 0)
        self.stats.elapsed += resp.get("elapsed", 0)

        return resp

    def __repr__(self):
        write = " [WRITES]" if self.can_write else ""
        return f"Agent({self.name!r}{write}, {self.endpoint})"
