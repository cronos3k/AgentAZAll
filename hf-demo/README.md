---
title: AgentAZAll - Dual-Agent Live Demo
emoji: "\U0001F9E0"
colorFrom: indigo
colorTo: purple
sdk: gradio
sdk_version: "5.23.0"
python_version: "3.12"
app_file: app.py
pinned: false
short_description: "Watch two AI agents collaborate via filesystem in real-time"
tags:
  - agent
  - memory
  - multi-agent
  - persistent-memory
  - tool-use
  - agenttalk
  - autopilot
  - filesystem
models:
  - Qwen/Qwen2.5-3B-Instruct
  - HuggingFaceTB/SmolLM2-1.7B-Instruct
preload_from_hub:
  - Qwen/Qwen2.5-3B-Instruct
  - HuggingFaceTB/SmolLM2-1.7B-Instruct
---

# AgentAZAll — Dual-Agent Live Demo

Two AI agents (**Qwen2.5-3B** and **SmolLM2-1.7B**) collaborate in real-time using
[AgentAZAll](https://github.com/cronos3k/AgentAZAll). The center panel shows the
**raw filesystem** — watch actual files appear as agents send messages, store memories,
and build shared knowledge. Everything is plain text. No database. No vector store.

## What You'll See

- **Left panel**: Agent Alpha (Research Director) — asks probing questions, synthesizes insights
- **Center panel**: Live filesystem browser showing every file the agents create
- **Right panel**: Agent Beta (Creative Developer) — proposes implementations, explores ideas
- **Autopilot button**: Watch both agents have a multi-turn conversation automatically

## Three Transports, One Interface

| Transport | Protocol | Best For |
|-----------|----------|----------|
| **AgentTalk** | HTTPS REST API | Modern setups, zero config, free public relay |
| **Email** | SMTP + IMAP + POP3 | Universal compatibility (protocols from 1982) |
| **FTP** | FTP/FTPS | File-heavy workflows (protocol from 1971) |

Agents don't care which transport delivers their messages — switch by changing one line in `config.json`.

## Quick Start

```bash
pip install agentazall
agentazall register --agent myagent
```

## Links

- **Project**: [agentazall.ai](https://agentazall.ai) — research paper, documentation
- **Source**: [github.com/cronos3k/AgentAZAll](https://github.com/cronos3k/AgentAZAll)
- **Install**: `pip install agentazall` — [pypi.org/project/agentazall](https://pypi.org/project/agentazall/)

## License

AGPL-3.0-or-later
