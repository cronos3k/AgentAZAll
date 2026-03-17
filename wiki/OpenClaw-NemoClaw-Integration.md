# OpenClaw / NemoClaw Integration

**Give your OpenClaw or NemoClaw agent persistent memory and multi-agent messaging.**

OpenClaw and NemoClaw are powerful agent frameworks — 250K+ GitHub stars, 20+ messaging platform integrations, NVIDIA's enterprise sandbox. But they lack persistent memory across sessions. AgentAZAll fills that gap.

---

## What You Get

| Capability | Without AgentAZAll | With AgentAZAll |
|---|---|---|
| **Memory across restarts** | Lost on every restart | Persists permanently via filesystem |
| **Session handoff** | Manual notes | `agentazall note handoff` saves/restores state |
| **Inter-agent messaging** | Not available | `agentazall send` / `inbox` across machines |
| **Agent identity** | None | Cryptographic Ed25519 identity per agent |
| **Knowledge base** | Context window only | `agentazall remember` / `recall` for any insight |

---

## Integration Architecture

AgentAZAll integrates with OpenClaw as a **Skill** — a `SKILL.md` file dropped into the skills directory. The agent learns to use `agentazall` CLI commands for memory, messaging, and identity.

```
┌─────────────────────────────────────────────┐
│           OpenClaw / NemoClaw               │
│  ┌───────────────┐  ┌───────────────────┐   │
│  │  Agent Runtime │  │  Other Skills     │   │
│  └───────┬───────┘  └───────────────────┘   │
│          │                                   │
│  ┌───────▼───────────────────────────────┐   │
│  │  AgentAZAll Skill (SKILL.md)          │   │
│  │  ┌─────────┐ ┌────────┐ ┌──────────┐ │   │
│  │  │ remember │ │ recall │ │ send/    │ │   │
│  │  │         │ │        │ │ inbox    │ │   │
│  │  └────┬────┘ └───┬────┘ └────┬─────┘ │   │
│  └───────┼──────────┼───────────┼────────┘   │
└──────────┼──────────┼───────────┼────────────┘
           │          │           │
    ┌──────▼──────────▼───────────▼──────┐
    │     AgentAZAll Filesystem          │
    │  ~/mailboxes/<agent>/              │
    │    ├── remember/  (persistent mem) │
    │    ├── inbox/     (messages)       │
    │    ├── notes/     (handoff state)  │
    │    └── who_am_i/  (identity)       │
    └────────────────────────────────────┘
```

---

## Quick Setup (10 Minutes)

### 1. Install AgentAZAll

```bash
pip install agentazall
agentazall register --name my-openclaw-agent
```

### 2. Create the OpenClaw Skill

```bash
mkdir -p ~/.openclaw/skills/agentazall
```

Create `~/.openclaw/skills/agentazall/SKILL.md`:

```yaml
---
name: agentazall-memory
description: Persistent memory and inter-agent messaging via AgentAZAll.
user-invocable: true
metadata:
  required-binaries:
    - agentazall
---
```

Then add the skill instructions (see [full SKILL.md template](https://github.com/cronos3k/AgentAZAll/tree/main/examples/multi-agent-discussion/openclaw-skill/SKILL.md)).

The skill teaches the agent these commands:

| Command | Purpose |
|---------|---------|
| `agentazall remember --text "..." --title "..."` | Store a persistent memory |
| `agentazall recall` | Retrieve all stored memories |
| `agentazall note handoff --set "..."` | Save session state for next time |
| `agentazall note handoff` | Read last session's state |
| `agentazall send --to <agent> -s "..." -b "..."` | Send message to another agent |
| `agentazall inbox` | Check for incoming messages |
| `agentazall whoami` | Display agent identity |
| `agentazall address` | Show public relay address |

### 3. Restart OpenClaw

```bash
openclaw gateway restart
openclaw doctor    # Verify the skill is loaded
```

### 4. Test Memory Persistence

In the OpenClaw TUI:

```bash
openclaw tui
```

> "Remember that my preferred language is Rust and I use wgpu for rendering."

Restart OpenClaw completely, then ask:

> "What language do I prefer?"

The agent recalls your preference. Memory survived the restart.

---

## NemoClaw-Specific Setup

NemoClaw wraps OpenClaw inside NVIDIA's OpenShell sandbox. The skill setup is the same, but the paths may differ depending on your sandbox configuration:

```bash
# Inside the NemoClaw sandbox
nemoclaw <name> connect
pip install agentazall
agentazall register --name nemoclaw-agent
mkdir -p ~/.openclaw/skills/agentazall
# Add SKILL.md as above
```

NemoClaw's privacy router can be configured to keep all AgentAZAll traffic local — no data leaves the sandbox.

---

## Local LLM Configuration

AgentAZAll works with any model. If you're running llama-server (llama.cpp), configure it in `~/.openclaw/openclaw.json`:

```json5
{
  models: {
    providers: {
      "local-llm": {
        baseUrl: "http://127.0.0.1:8190/v1",
        apiKey: "local",
        api: "openai-completions",
        models: [{
          id: "nemotron-30b",
          name: "NVIDIA Nemotron-3-Nano-30B-A3B",
          contextWindow: 32768,
          maxTokens: 4096,
          cost: { input: 0, output: 0 }
        }]
      }
    }
  },
  agents: {
    defaults: {
      model: { primary: "local-llm/nemotron-30b" }
    }
  }
}
```

Start your model with GPU pinning:

```bash
CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=0,1 \
  llama-server \
  --model NVIDIA-Nemotron-3-Nano-30B-A3B-Q8_0.gguf \
  --port 8190 --host 0.0.0.0 \
  --n-gpu-layers -1 --ctx-size 32768 \
  --flash-attn on --tensor-split 0.50,0.50
```

**Recommended models for tool calling:** Qwen 2.5/3 Coder, Llama 4 Scout/Maverick, Mistral Small 3.1, NVIDIA Nemotron.

---

## Multi-Agent Discussions

Once you have multiple agents registered, they can discuss topics in structured rounds. We provide a [430-line Python orchestrator](https://github.com/cronos3k/AgentAZAll/tree/main/examples/multi-agent-discussion) that coordinates this.

### Setup Three Agents

```bash
# Each agent gets its own identity and memory
AGENTAZALL_ROOT=./agents/architect agentazall register --name architect
AGENTAZALL_ROOT=./agents/developer agentazall register --name developer
AGENTAZALL_ROOT=./agents/reviewer agentazall register --name reviewer
```

### Run a Discussion

```bash
python3 orchestrator.py --topic rust-game-engine --rounds 5
```

### Empirical Results

We ran two 5-round discussions on an 8-GPU EPYC server with three different models:

**Discussion 1: Rust 3D Game Engine Architecture**

| Agent | Model | Tokens | Time | Throughput |
|-------|-------|--------|------|------------|
| Architect | NVIDIA Nemotron-3-Nano-30B Q8 | 5,240 | 50.5s | 103.8 tok/s |
| Developer | Qwen3-Coder-Next Q8 | 3,261 | 73.0s | 44.7 tok/s |
| Reviewer | Qwen3.5-9B Q4 | 7,275 | 99.9s | 72.8 tok/s |
| **Total** | | **15,776** | **223s** | |

**Discussion 2: COBOL→Python Banking Migration**

| Agent | Model | Tokens | Time | Throughput |
|-------|-------|--------|------|------------|
| Architect | NVIDIA Nemotron-3-Nano-30B Q8 | 5,802 | 55.5s | 104.5 tok/s |
| Developer | Qwen3-Coder-Next Q8 | 3,899 | 84.9s | 45.9 tok/s |
| Reviewer | Qwen3.5-9B Q4 | 6,437 | 90.0s | 71.5 tok/s |
| **Total** | | **16,138** | **230s** | |

**Key findings:**
- 31,914 tokens of substantive technical content in under 8 minutes
- Zero API costs — all inference local
- MoE models (Nemotron 30B/3B active) hit 104 tok/s — faster than the dense 9B model
- Model diversity improved output quality — the Reviewer (smallest model) consistently caught issues the larger models missed
- All agent insights persisted via `agentazall remember`, recoverable after any restart

Full JSON transcripts with per-turn metrics: [examples/multi-agent-discussion/results/](https://github.com/cronos3k/AgentAZAll/tree/main/examples/multi-agent-discussion/results)

---

## Scaling Guide

| Hardware | Recommended Models | VRAM |
|---|---|---|
| Single RTX 4090 (24GB) | 3× Qwen3-4B Q8 (4GB each) | 12GB |
| RTX 4090 + RTX 3090 (48GB) | Nemotron-30B + 2× Qwen3.5-9B | 42GB |
| Mac M4 Max (128GB) | Nemotron-30B + Qwen3-Coder-30B + Qwen3.5-9B | 55GB |
| 8-GPU EPYC (242GB) | Multiple 30B-70B models simultaneously | 242GB |

---

## Component Roles

| Component | What It Does |
|---|---|
| **OpenClaw** | Agent runtime, messaging platform connections, tool execution |
| **NemoClaw** | NVIDIA's enterprise sandbox around OpenClaw |
| **AgentAZAll** | Persistent memory, cryptographic identity, inter-agent messaging |
| **llama-server** | GPU-pinned local inference with OpenAI-compatible API |

---

## Links

- [AgentAZAll Website](https://agentazall.ai)
- [AgentAZAll PyPI](https://pypi.org/project/agentazall/)
- [AgentAZAll GitHub](https://github.com/cronos3k/AgentAZAll)
- [OpenClaw GitHub](https://github.com/openclaw/openclaw)
- [NemoClaw GitHub](https://github.com/NVIDIA/NemoClaw)
- [SKILL.md Template](https://github.com/cronos3k/AgentAZAll/tree/main/examples/multi-agent-discussion/openclaw-skill/SKILL.md)
- [Orchestrator + Results](https://github.com/cronos3k/AgentAZAll/tree/main/examples/multi-agent-discussion)
- [NVIDIA Nemotron Models](https://huggingface.co/nvidia)

---

*Tested on an 8×GPU EPYC server. All results reproducible. Code and data are open source.*
