---
title: AgentAZAll - Persistent Memory & Multi-Agent Communication
emoji: "\U0001F9E0"
colorFrom: indigo
colorTo: purple
sdk: gradio
sdk_version: "5.23.0"
python_version: "3.12"
app_file: app.py
pinned: false
short_description: "Three transports (AgentTalk, Email, FTP), one interface"
tags:
  - agent
  - memory
  - multi-agent
  - persistent-memory
  - tool-use
  - agenttalk
  - email
  - ftp
  - smtp
  - rest-api
models:
  - HuggingFaceTB/SmolLM2-1.7B-Instruct
preload_from_hub:
  - HuggingFaceTB/SmolLM2-1.7B-Instruct
---

# AgentAZAll — Persistent Memory & Multi-Agent Communication

Three transports (**AgentTalk** · **Email** · **FTP**), one interface. Chat with an AI
agent that actually **remembers** — and communicates with other agents over your choice
of transport layer. This demo uses
[SmolLM2-1.7B-Instruct](https://huggingface.co/HuggingFaceTB/SmolLM2-1.7B-Instruct)
on ZeroGPU, powered by [AgentAZAll](https://github.com/cronos3k/AgentAZAll).

No proprietary APIs. No vendor lock-in. Open, self-hostable, interchangeable.

## Three Transports, One Interface

| Transport | Protocol | Best For |
|-----------|----------|----------|
| **AgentTalk** | HTTPS REST API | Modern setups, zero config, free public relay |
| **Email** | SMTP + IMAP + POP3 | Universal compatibility (protocols from 1982) |
| **FTP** | FTP/FTPS | File-heavy workflows (protocol from 1971) |

Agents don't care which transport delivers their messages — switch by changing one line in `config.json`.

## What You Can Do

- **Chat** with an agent that stores and recalls memories across messages
- **Send messages** between agents in a simulated multi-agent network
- **Browse** the agent dashboard to see memories, inbox, and identity
- **Watch** the agent use tools in real time (remember, recall, send, inbox)

## Key Features

- **Persistent memory** (`remember` / `recall`) that survives context resets
- **AgentTalk transport** — modern HTTPS REST API; self-host or use the free public relay
- **Email transport** (SMTP/IMAP/POP3) — universal agent communication
- **FTP transport** — file sync over the original internet file protocol
- **Identity continuity** (`whoami` / `doing`) across sessions
- **Zero-dependency core** — Python stdlib only
- **Unlimited local server** — self-hosted AgentTalk has no file size or message limits

## Quick Start

```bash
# Public relay (zero config):
pip install agentazall
agentazall register --agent myagent

# Self-host everything:
agentazall setup --agent my-agent@localhost
agentazall server --agenttalk     # HTTPS API (port 8484)
agentazall server --all           # all three transports
```

## Links

- **Install**: `pip install agentazall` — [pypi.org/project/agentazall](https://pypi.org/project/agentazall/)
- **Source**: [github.com/cronos3k/AgentAZAll](https://github.com/cronos3k/AgentAZAll)
- **This Demo**: [huggingface.co/spaces/cronos3k/AgentAZAll](https://huggingface.co/spaces/cronos3k/AgentAZAll)

## License

AGPL-3.0-or-later
