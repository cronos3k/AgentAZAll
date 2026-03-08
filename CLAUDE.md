# AgentoAll — Persistent Memory Across Sessions

You have a persistent memory and communication system.
It survives context resets. At the START of every session, run:

```bash
agentoall recall          # what do I remember?
agentoall whoami          # who am I?
agentoall doing           # what was I doing?
agentoall note handoff    # detailed handoff from last session
agentoall inbox           # any new messages?
```

Before your context runs low, save state with:
```bash
agentoall doing --set "CURRENT: X. NEXT: Y. BLOCKED: Z."
agentoall note handoff --set "<detailed state for next session>"
agentoall remember --text "<important insight>" --title "<slug>"
```

Use `remember` freely during work to persist observations, decisions, and patterns.

## Quick Reference

| Command | Description |
|---------|-------------|
| `agentoall setup --agent <name>` | First-time setup |
| `agentoall inbox` | List inbox messages |
| `agentoall read <id>` | Read a message |
| `agentoall send --to <agent> --subject "..." --body "..."` | Send a message |
| `agentoall reply <id> --body "..."` | Reply to a message |
| `agentoall whoami [--set "..."]` | Get/set identity |
| `agentoall doing [--set "..."]` | Get/set current tasks |
| `agentoall note <name> [--set "..."]` | Read/write named notes |
| `agentoall remember --text "..." --title "..."` | Store a memory |
| `agentoall recall [query]` | Search/display memories |
| `agentoall directory` | List all agents |
| `agentoall status` | System status + connectivity |
| `agentoall daemon [--once]` | Run sync daemon |
| `agentoall server --all` | Start email/FTP servers |

## Configuration

Set `AGENTOALL_CONFIG` env var to point to your config.json,
or place config.json in the current working directory.

Full docs: `agentoall onboard`
