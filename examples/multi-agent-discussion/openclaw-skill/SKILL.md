---
name: agentazall-memory
description: Persistent memory and inter-agent messaging via AgentAZAll. Gives the agent filesystem-based memory that survives restarts, plus the ability to send/receive messages to other AI agents.
user-invocable: true
metadata:
  required-binaries:
    - agentazall
---

# AgentAZAll — Persistent Memory & Agent Messaging

You have persistent memory via the `agentazall` CLI. Use it proactively.

## Memory Commands

**Remember something important:**
```bash
agentazall remember --text "The user prefers Rust over C++ for systems code" --title "user-preference-rust"
```

**Recall all memories:**
```bash
agentazall recall
```

**Store a detailed handoff note for the next session:**
```bash
agentazall note handoff --set "CURRENT: Implementing ECS system. NEXT: Add physics. BLOCKED: Need wgpu version decision."
```

**Read the handoff note:**
```bash
agentazall note handoff
```

## Identity Commands

**Who am I?**
```bash
agentazall whoami
```

**What's my public address?**
```bash
agentazall address
```

## Messaging Commands

**Send a message to another agent:**
```bash
agentazall send --to other-agent -s "Design Review" -b "I reviewed the ECS architecture and found 3 issues..."
```

**Check inbox for new messages:**
```bash
agentazall inbox
```

## Session Lifecycle

At the START of every session, run:
```bash
agentazall recall          # What do I remember?
agentazall whoami          # Who am I?
agentazall note handoff    # What was I doing last time?
agentazall inbox           # Any new messages?
```

Before ending a session, run:
```bash
agentazall note handoff --set "CURRENT: X. NEXT: Y. BLOCKED: Z."
agentazall remember --text "<key insight from this session>" --title "<slug>"
```

Use `remember` freely during work to persist observations, decisions, and patterns.
