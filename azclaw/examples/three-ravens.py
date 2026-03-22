#!/usr/bin/env python3
"""AgentAZClaw — Three Ravens quickstart.

Three agents. One task. Twenty lines. Memory-first.

Requirements:
    pip install azclaw
    # Start a local LLM server (llama.cpp, Ollama, vLLM, etc.)
"""

from azclaw import Agent, Orchestrator

# Three agents, same endpoint, different roles
endpoint = "http://localhost:8080/v1/chat/completions"

architect = Agent("architect",
                  role="You design software architecture. Be specific about file structure, data models, and API contracts.",
                  endpoint=endpoint)

developer = Agent("developer",
                  role="You write Python code. Follow the Architect's design exactly. Write clean, tested code.",
                  endpoint=endpoint, can_write=True)

reviewer  = Agent("reviewer",
                  role="You review code for bugs, security issues, and design violations. Be constructive.",
                  endpoint=endpoint)

# Run
orch = Orchestrator(agents=[architect, developer, reviewer])
orch.set_task("Build a FastAPI REST API for a todo app with SQLite backend. Include CRUD endpoints, Pydantic models, and basic error handling.", max_rounds=20)
orch.run()

# Results
print(f"\nFiles written: {orch.stats.files_written}")
print(f"Memories stored: {orch.stats.memories_stored}")
print(f"Total tokens: {orch.stats.total_comp + orch.stats.total_prompt:,}")
