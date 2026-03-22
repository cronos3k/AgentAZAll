"""AgentAZClaw — Memory-first multi-agent orchestrator.

OpenClaw is the kitchen sink. AgentAZClaw is the sharp knife.

Usage:
    from azclaw import Agent, Orchestrator

    architect = Agent("architect", role="Design the solution",
                      endpoint="http://localhost:8080/v1/chat/completions")
    developer = Agent("developer", role="Write the code",
                      endpoint="http://localhost:8080/v1/chat/completions",
                      can_write=True)
    reviewer  = Agent("reviewer", role="Review the code",
                      endpoint="http://localhost:8080/v1/chat/completions")

    orch = Orchestrator(agents=[architect, developer, reviewer])
    orch.set_task("Build a FastAPI REST API for a todo app")
    orch.run(max_rounds=30)
"""

from .agent import Agent
from .orchestrator import Orchestrator, RunStats
from .tools import ToolRegistry, build_default_registry
from .topic import Topic

__version__ = "0.1.0"
__all__ = [
    "Agent",
    "Orchestrator",
    "RunStats",
    "ToolRegistry",
    "build_default_registry",
    "Topic",
]
