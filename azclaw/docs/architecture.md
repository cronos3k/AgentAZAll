# Architecture & Design Decisions

## The Core Problem

Every multi-agent framework uses the context window as long-term memory. This means:

1. Context grows linearly with every round
2. By round 30, you're sending 50K+ tokens per agent per turn
3. Speed collapses as KV cache fills
4. Eventually you hit the context limit and must truncate — losing decisions
5. Truncated agents contradict their own earlier conclusions

We observed this directly: orchestrator v2 saw the Architect's speed drop from 96 tok/s to **2 tok/s** in 25 rounds. The system was unusable after 30 minutes.

## The Fix: Memory-First

AZClaw's design rule: **only the last round goes into context. Everything else is a tool call.**

```
What each agent sees every turn:
┌─────────────────────────────────────────┐
│ System prompt (role + tools)    ~800 tok │
│ Phase instruction               ~200 tok │
│ Last round's messages          ~2-6K tok │
│                                          │
│ TOTAL: 3-9K tokens. Always.              │
└─────────────────────────────────────────┘
```

When an agent needs information from round 47, it calls `recall(query="database")` and gets the stored decision back. This costs one tool call. The alternative — carrying every message from rounds 1-46 in context — costs 50K+ tokens and gets worse every round.

### The Proof

| Metric | Context-First (v2) | Memory-First (AZClaw) |
|--------|--------------------|-----------------------|
| Context at round 10 | ~15K tokens | ~4K tokens |
| Context at round 50 | ~60K+ (overflow) | ~5K tokens |
| Context at round 199 | impossible | ~6K tokens |
| Speed at round 10 | 95 t/s | 98 t/s |
| Speed at round 50 | 2 t/s | 104 t/s |
| Speed at round 199 | — | 101 t/s |

## Components

### Agent

An `Agent` is an LLM endpoint + a role + tool permissions + an AgentAZAll memory root.

```python
Agent(
    name="developer",                    # identity
    role="You write Python code.",       # system prompt role section
    endpoint="http://...",               # OpenAI-compatible URL
    model="nemotron-30b",                # model name for the API
    tools=["recall", "remember", ...],   # allowed tool names
    can_write=True,                      # gates write_file + run_python
    root="./agents/developer",           # AgentAZAll memory directory
    max_tokens=8192,                     # per-turn generation limit
    temperature=0.7,                     # sampling temperature
)
```

Each agent gets its own filesystem directory for memories. When any agent calls `recall("")`, it gets the **merged index** across all agents — this is how knowledge flows between them without context pollution.

### Orchestrator

The orchestrator runs agents in round-robin order. Each round:

1. Build system prompt (role + phase + tool descriptions)
2. Get last round's messages (nothing else)
3. Format for the API (merge consecutive same-role messages)
4. Call the LLM with tool schemas
5. Process tool calls (up to 5 tool rounds per agent turn)
6. Record the agent's response in history
7. Move to next agent

After all agents have spoken, advance to the next round.

### ToolRegistry

Tools are plain functions with a decorator. The registry:

- Auto-generates OpenAI function-calling schemas from the decorator
- Filters tools by agent permissions (`allowed` list + `capabilities`)
- Tracks per-agent dedup (same agent can't call same tool with same args twice per turn)
- Injects context (agent_root, output_dir, source_dirs) into every call via `_ctx`

### Topic

Topics define multi-phase tasks. Each phase has:
- A name and focus description
- A round range (e.g., rounds 1-20)
- Optional source file lists for the agents to examine
- Optional coherence probes (questions injected at specific rounds to test agent consistency)

For simple tasks, `Orchestrator.set_task("description")` auto-creates a single-phase topic.

## Design Decisions

### 1. No Subprocess for Memory

Orchestrator v3 (the prototype) called `agentazall recall` via subprocess. AZClaw imports AgentAZAll's Python functions directly:

```python
# v3 (subprocess):
result = subprocess.run(["agentazall", "recall", query], ...)

# AZClaw (direct):
from agentazall.index import build_remember_index
idx_path.read_text()
```

Direct calls are faster and don't require `agentazall` to be on PATH. Subprocess is only used for `whoami` initialization (which is a one-time setup).

### 2. Per-Agent Dedup

The v3 prototype had global dedup — if any agent called `recall("")`, the second agent's identical call would be skipped. This was wrong: each agent needs its own recall result. AZClaw tracks dedup per agent name:

```python
self._seen: dict[str, set[str]]  # agent_name -> set of call_keys
```

### 3. History Pruning

Even though only the last round goes into context, the full history stays in memory for checkpointing. To prevent unbounded growth, history older than 10 rounds is pruned:

```python
if len(self._history) > 200:
    cutoff_round = rnd - 10
    self._history = [m for m in self._history if m.get("round", 0) >= cutoff_round]
```

This doesn't affect agent behavior (they only see last round anyway) but keeps memory usage bounded.

### 4. urllib-Only LLM Client

No `requests`, no `httpx`, no `openai` SDK. Just Python stdlib `urllib.request`. This means:
- Zero external dependencies beyond agentazall
- Works with any OpenAI-compatible endpoint
- No version conflicts with other packages

### 5. Log File Mirroring

All output goes to both stdout and a timestamped log file. This means:
- You can watch the run live in the terminal
- The full log is preserved for analysis
- No need for separate logging configuration

### 6. Flexible Health Checks

The health check tries two endpoints:
- `/health` (llama.cpp native)
- `/v1/models` (LM Studio, vLLM, Ollama, OpenRouter)

This means AZClaw works with any backend without configuration.

## File Structure

```
When you run AZClaw, it creates:

./
├── output/                    # Generated files (code, configs, etc.)
├── agents/
│   ├── architect/data/        # Architect's AgentAZAll memory
│   │   └── mailboxes/...
│   │       └── remember/      # Stored decisions
│   ├── developer/data/        # Developer's memories
│   └── reviewer/data/         # Reviewer's memories
├── logs/
│   ├── <topic>_<timestamp>.log      # Full run log
│   └── <topic>_checkpoint.json      # Resume checkpoint
└── STOP                       # Touch this to stop gracefully
```

Everything is plain files. No database. No vector store. You can `cat`, `grep`, `git commit`, or `rm -rf` any of it.
