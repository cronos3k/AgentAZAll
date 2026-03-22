# AZClaw — Memory-First Multi-Agent Orchestrator

**Three agents. Shared persistent memory. Runs for hours. Context never grows.**

AZClaw is a multi-agent orchestrator built on [AgentAZAll](https://github.com/cronos3k/AgentAZAll). It runs multiple LLM agents in rounds, using persistent memory instead of conversation history. The context window stays small. Speed stays constant. Agents recall what they need, when they need it.

Validated in production: **3 agents, 199 rounds, 8 hours 46 minutes, 402 memories, 52 Python files, zero errors, $0 in API costs.**

## Install

```bash
pip install azclaw
```

This automatically installs `agentazall` as a dependency.

## 20-Line Quickstart

```python
from azclaw import Agent, Orchestrator

endpoint = "http://localhost:8080/v1/chat/completions"

architect = Agent("architect",
    role="You design software architecture. Be specific about file structure and data models.",
    endpoint=endpoint)

developer = Agent("developer",
    role="You write Python code. Follow the Architect's design exactly.",
    endpoint=endpoint, can_write=True)

reviewer = Agent("reviewer",
    role="You review code for bugs, security issues, and design violations.",
    endpoint=endpoint)

orch = Orchestrator(agents=[architect, developer, reviewer])
orch.set_task("Build a FastAPI REST API for a todo app with SQLite backend.")
orch.run(max_rounds=20)

print(f"Files: {orch.stats.files_written}")
print(f"Memories: {orch.stats.memories_stored}")
```

## How It Works

### Memory-First Architecture

Every other multi-agent framework stuffs the full conversation history into each API call. By round 30, context overflows. Speed collapses. Agents forget earlier decisions.

AZClaw takes the opposite approach:

- **Only the last round** goes into context
- **Everything else** is stored via `remember()` and retrieved via `recall()`
- Context stays at **2–9K tokens** regardless of how many rounds have passed
- Speed at round 199 is the same as round 1

### Role-Based Tool Access

| Role | recall | remember | read_file | list_files | write_file | run_python |
|------|--------|----------|-----------|------------|------------|------------|
| Architect | yes | yes | yes | yes | no | no |
| Developer | yes | yes | yes | yes | **yes** | **yes** |
| Reviewer | yes | yes | yes | yes | no | no |

Only the Developer writes code. The Architect designs. The Reviewer validates. This prevents agents from overwriting each other's work.

### Dedup Detection

If an agent calls the same tool with the same arguments twice in one turn, the duplicate is skipped automatically. If ALL calls in a turn are duplicates, the agent is forced to analyze existing results instead of looping.

### Graceful Stop

```bash
touch STOP          # creates STOP file — orchestrator finishes current round and exits
azclaw stop         # same thing via CLI
```

Or send SIGINT/SIGTERM — the orchestrator catches the signal and exits cleanly after the current round.

## CLI

```bash
# Run with a topic file
azclaw run --topic topics/my-migration.json

# Run with a simple task
azclaw run --task "Build a REST API for user management" --endpoint http://localhost:8080/v1/chat/completions

# Run with custom agents
azclaw run --task "Review this codebase" --agents "designer:http://localhost:8200/v1/chat/completions,coder:http://localhost:8201/v1/chat/completions"

# Resume from checkpoint
azclaw run --topic my-topic.json --resume logs/my_topic_checkpoint.json

# Stop gracefully
azclaw stop
```

## Topic Configuration

For complex multi-phase tasks, define a topic JSON:

```json
{
  "title": "COBOL to Python Migration",
  "system_context": "You are migrating a COBOL banking application to Python/FastAPI.",
  "initial_prompt": "Begin by analyzing the COBOL source files...",
  "phases": [
    {
      "name": "Discovery",
      "rounds": [1, 20],
      "focus": "Analyze all programs, map dependencies",
      "source_files": ["cbl/COSGN00C.cbl", "cbl/COACTUPC.cbl"]
    },
    {
      "name": "Data Layer",
      "rounds": [21, 45],
      "focus": "Convert copybooks to SQLAlchemy models"
    }
  ],
  "coherence_probes": [
    {"after_round": 25, "question": "What database engine did we choose and why?"}
  ],
  "agent_roles": {
    "architect": "You design the Python architecture. Map COBOL constructs to modern equivalents.",
    "developer": "You write Python code that preserves COBOL business logic exactly.",
    "reviewer": "You verify generated code against the original COBOL source."
  }
}
```

## Custom Tools

Register custom tools with a decorator:

```python
from azclaw import build_default_registry

registry = build_default_registry()

@registry.tool("search_code", "Search codebase with ripgrep",
               {"query": "string", "file_type": "string"})
def search_code(query: str, file_type: str = "py", _ctx=None):
    import subprocess
    r = subprocess.run(["rg", query, "--type", file_type, "."],
                       capture_output=True, text=True, timeout=10)
    return r.stdout[:5000] or "[No matches]"

# Pass to orchestrator
orch = Orchestrator(agents=[...], registry=registry)
```

## Checkpointing & Resume

AZClaw saves checkpoints every 5 rounds to `logs/`. If a run is interrupted, resume from where it stopped:

```bash
azclaw run --topic my-topic.json --resume logs/my_topic_checkpoint.json
```

The checkpoint preserves: round number, all agent stats, memory counts, and the last 100 history messages.

## The 9-Hour Proof

Three NVIDIA Nemotron-3-Nano-30B-A3B agents (3B active params each, MoE) ran for 8 hours 46 minutes on an AMD EPYC server with 8 GPUs, migrating AWS CardDemo (50,000 lines of COBOL) to Python:

| Metric | Value |
|--------|-------|
| Rounds | 199 |
| Runtime | 8h 46m |
| Python files | 52 (2,543 lines) |
| Memories | 402 |
| Tool calls | 1,599 |
| Tokens | 24.3M total |
| Context per agent | 2–9K (flat) |
| Speed | 97–137 tok/s (start to finish) |
| Errors | 0 |
| Cloud API cost | $0.00 |

Download the full results: [carddemo-agentazall-results.zip](https://agentazall.ai/experiments/carddemo-cobol-migration/carddemo-agentazall-results.zip) (743KB)

## Architecture

```
~960 lines of Python. 1 dependency (agentazall). That's it.

azclaw/
├── __init__.py       (20 lines)   Public API
├── agent.py          (100 lines)  Agent class — LLM + role + tools
├── orchestrator.py   (350 lines)  Round loop, memory-first context, checkpoints
├── tools.py          (260 lines)  ToolRegistry + 6 built-in tools
├── llm.py            (100 lines)  urllib-only OpenAI client
├── topic.py          (70 lines)   Phase/topic config loader
└── cli.py            (100 lines)  CLI entry point
```

## Requirements

- Python 3.10+
- Any OpenAI-compatible LLM endpoint (llama.cpp, vLLM, Ollama, LM Studio, OpenRouter)
- At least one GPU with 8GB+ VRAM (for a small model)

## Links

- **AgentAZAll**: [github.com/cronos3k/AgentAZAll](https://github.com/cronos3k/AgentAZAll)
- **Website**: [agentazall.ai](https://agentazall.ai)
- **Autonomous Demo**: [agentazall.ai/autonomous.html](https://agentazall.ai/autonomous.html)
- **PyPI**: [pypi.org/project/azclaw](https://pypi.org/project/azclaw/)

## License

AGPL-3.0 — same as AgentAZAll.
