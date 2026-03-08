---
title: AgentAZAll - Persistent Memory for LLM Agents
emoji: "\U0001F9E0"
colorFrom: indigo
colorTo: purple
sdk: gradio
sdk_version: "5.23.0"
python_version: "3.12"
app_file: app.py
pinned: false
short_description: "Agent memory & communication over Email and FTP — protocols running since 1971"
tags:
  - agent
  - memory
  - multi-agent
  - persistent-memory
  - tool-use
  - email
  - ftp
  - smtp
models:
  - HuggingFaceTB/SmolLM2-1.7B-Instruct
preload_from_hub:
  - HuggingFaceTB/SmolLM2-1.7B-Instruct
---

# AgentAZAll — Agent Memory & Communication over Email and FTP

Chat with an AI agent that actually **remembers** — and syncs with other agents over
**SMTP, IMAP, and FTP**, protocols that have been running since 1971. This demo uses
[SmolLM2-1.7B-Instruct](https://huggingface.co/HuggingFaceTB/SmolLM2-1.7B-Instruct)
on ZeroGPU, powered by [AgentAZAll](https://github.com/cronos3k/AgentAZAll).
No proprietary APIs. No vendor lock-in. Just infrastructure that already won.

## What You Can Do

- **Chat** with an agent that stores and recalls memories across messages
- **Send messages** between agents in a simulated multi-agent network
- **Browse** the agent dashboard to see memories, inbox, and identity
- **Watch** the agent use tools in real time (remember, recall, send, inbox)

## How It Works

AgentAZAll gives every agent a file-based mailbox with:
- **Persistent memory** (`remember` / `recall`) that survives context resets
- **Email transport** (SMTP/IMAP/POP3) — agents communicate over protocols from 1982
- **FTP transport** — file sync over the original internet file protocol (1971)
- **Identity continuity** (`whoami` / `doing`) across sessions
- **Working notes** for ongoing projects

No database, no proprietary API — plain text files synced over protocols every server already speaks.

## Install Locally

```bash
pip install agentazall
agentazall setup --agent my-agent@localhost
agentazall remember --text "Important fact" --title "my-fact"
agentazall recall
```

## License

AGPL-3.0-or-later
