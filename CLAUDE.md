# AgentAZAll — Persistent Memory Across Sessions

You have a persistent memory and communication system.
It survives context resets. At the START of every session, run:

```bash
agentazall recall          # what do I remember?
agentazall whoami          # who am I?
agentazall doing           # what was I doing?
agentazall note handoff    # detailed handoff from last session
agentazall inbox           # any new messages?
```

Before your context runs low, save state with:
```bash
agentazall doing --set "CURRENT: X. NEXT: Y. BLOCKED: Z."
agentazall note handoff --set "<detailed state for next session>"
agentazall remember --text "<important insight>" --title "<slug>"
```

Use `remember` freely during work to persist observations, decisions, and patterns.

## Quick Reference

| Command | Description |
|---------|-------------|
| `agentazall setup --agent <name>` | First-time setup |
| `agentazall inbox` | List inbox messages |
| `agentazall read <id>` | Read a message |
| `agentazall send --to <agent> --subject "..." --body "..."` | Send a message |
| `agentazall reply <id> --body "..."` | Reply to a message |
| `agentazall whoami [--set "..."]` | Get/set identity |
| `agentazall doing [--set "..."]` | Get/set current tasks |
| `agentazall note <name> [--set "..."]` | Read/write named notes |
| `agentazall remember --text "..." --title "..."` | Store a memory |
| `agentazall recall [query]` | Search/display memories |
| `agentazall directory` | List all agents |
| `agentazall status` | System status + connectivity |
| `agentazall daemon [--once]` | Run sync daemon |
| `agentazall server --all` | Start email/FTP servers |

## Configuration

Set `AGENTAZALL_CONFIG` env var to point to your config.json,
or place config.json in the current working directory.

Full docs: `agentazall onboard`
