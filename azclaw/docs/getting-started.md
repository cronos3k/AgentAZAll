# Getting Started with AZClaw

## Prerequisites

1. **Python 3.10+**
2. **A local LLM server** — any of these work:
   - [llama.cpp](https://github.com/ggerganov/llama.cpp) (`llama-server`)
   - [Ollama](https://ollama.ai) (`ollama serve`)
   - [LM Studio](https://lmstudio.ai) (built-in server)
   - [vLLM](https://docs.vllm.ai) (`vllm serve`)
   - Any OpenAI-compatible `/v1/chat/completions` endpoint

## Installation

```bash
pip install azclaw
```

This installs both `azclaw` (the orchestrator) and `agentazall` (persistent memory).

## Your First Run

### Step 1: Start a Local LLM

Any model works. For best results with multi-agent tasks, use a model with tool-calling support:

```bash
# llama.cpp example
llama-server --model your-model.gguf --port 8080 --ctx-size 32768

# Ollama example
ollama run llama3.1

# LM Studio — just load a model and start the server
```

### Step 2: Run Three Agents

Create a file called `my_first_run.py`:

```python
from azclaw import Agent, Orchestrator

endpoint = "http://localhost:8080/v1/chat/completions"

architect = Agent("architect",
    role="You design software architecture.",
    endpoint=endpoint)

developer = Agent("developer",
    role="You write code.",
    endpoint=endpoint, can_write=True)

reviewer = Agent("reviewer",
    role="You review code for bugs.",
    endpoint=endpoint)

orch = Orchestrator(agents=[architect, developer, reviewer])
orch.set_task("Build a Python script that fetches weather data from an API and displays it.")
orch.run(max_rounds=10)
```

Run it:

```bash
python my_first_run.py
```

### Step 3: Watch It Work

You'll see output like:

```
============================================================
  AgentAZClaw — Memory-First Orchestrator
  Topic: Build a Python script that fetches weather data...
  Agents: 3
  Stop: touch /your/path/STOP
============================================================

  OK architect -> http://localhost:8080/v1/chat/completions
  OK developer [WRITES] -> http://localhost:8080/v1/chat/completions
  OK reviewer -> http://localhost:8080/v1/chat/completions

  Running. Output -> ./output

------------------------------------------------------------
  Round 1 [Main]
------------------------------------------------------------
  [architect ] (0K ctx) -> 2 tool(s):
    -> recall({}) = 118ch
    -> remember({"text": "Use requests library..."}) = 31ch
  3521 tok, 45.2 t/s, 78s, tools:2
```

### Step 4: Check the Output

After the run:

```
output/              # Generated code
agents/
├── architect/       # Architect's memories
├── developer/       # Developer's memories
└── reviewer/        # Reviewer's memories
logs/                # Run logs + checkpoints
```

Look at the generated files:

```bash
ls output/
cat output/weather.py
```

Look at what the agents remembered:

```bash
# Using agentazall CLI
AGENTAZALL_ROOT=./agents/architect agentazall recall
AGENTAZALL_ROOT=./agents/developer agentazall recall
```

## Using the CLI

Instead of writing a Python script, use the CLI directly:

```bash
# Simple task
azclaw run --task "Build a calculator in Python" --endpoint http://localhost:8080/v1/chat/completions

# With a topic file (for complex multi-phase tasks)
azclaw run --topic my-migration.json

# Stop a running orchestrator
azclaw stop

# Resume an interrupted run
azclaw run --topic my-migration.json --resume logs/my_migration_checkpoint.json
```

## Using Multiple LLM Endpoints

For maximum speed, run each agent on a separate GPU:

```python
architect = Agent("architect",
    endpoint="http://localhost:8200/v1/chat/completions",
    model="nemotron-30b")

developer = Agent("developer",
    endpoint="http://localhost:8201/v1/chat/completions",
    model="qwen3-coder-30b", can_write=True)

reviewer = Agent("reviewer",
    endpoint="http://localhost:8202/v1/chat/completions",
    model="nemotron-30b")
```

Or via CLI:

```bash
azclaw run --task "Build an API" \
  --agents "architect:http://localhost:8200/v1/chat/completions,developer:http://localhost:8201/v1/chat/completions,reviewer:http://localhost:8202/v1/chat/completions"
```

## Two-Agent Setup

You don't need three agents. Two works fine:

```python
designer = Agent("designer", role="Design and plan.", endpoint=endpoint)
builder = Agent("builder", role="Write code.", endpoint=endpoint, can_write=True)

orch = Orchestrator(agents=[designer, builder])
orch.set_task("Build a web scraper for HN front page.")
orch.run(max_rounds=15)
```

## Next Steps

- [Architecture & Design Decisions](architecture.md) — why memory-first works
- [Topic Configuration Guide](topic-configuration.md) — multi-phase tasks
- [Custom Tools Guide](custom-tools.md) — extend agents with your own tools
