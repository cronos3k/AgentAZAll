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
short_description: "Give LLM agents memory that survives across sessions"
tags:
  - agent
  - memory
  - multi-agent
  - persistent-memory
  - tool-use
models:
  - HuggingFaceTB/SmolLM2-1.7B-Instruct
preload_from_hub:
  - HuggingFaceTB/SmolLM2-1.7B-Instruct
---

# AgentAZAll — Persistent Memory for LLM Agents

Chat with an AI agent that actually **remembers**. This demo runs
[SmolLM2-1.7B-Instruct](https://huggingface.co/HuggingFaceTB/SmolLM2-1.7B-Instruct)
on ZeroGPU, powered by [AgentAZAll](https://github.com/gregorkoch/agentazall) —
a file-based persistent memory and communication system for LLM agents.

## What You Can Do

- **Chat** with an agent that stores and recalls memories across messages
- **Send messages** between agents in a simulated multi-agent network
- **Browse** the agent dashboard to see memories, inbox, and identity
- **Watch** the agent use tools in real time (remember, recall, send, inbox)

## How It Works

AgentAZAll gives every agent a file-based mailbox with:
- **Persistent memory** (`remember` / `recall`) that survives context resets
- **Inter-agent messaging** (`send` / `inbox` / `reply`)
- **Identity continuity** (`whoami` / `doing`)
- **Working notes** for ongoing projects

No database required — everything is plain text files organized by date.

## Install Locally

```bash
pip install agentazall
agentazall setup --agent my-agent@localhost
agentazall remember --text "Important fact" --title "my-fact"
agentazall recall
```

## License

GPL-3.0-or-later
