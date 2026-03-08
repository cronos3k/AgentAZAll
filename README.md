# AgentAZAll

**Persistent memory and multi-agent communication over Email and FTP — protocols that have been running since 1971.**

> **[Try the live demo on Hugging Face Spaces](https://huggingface.co/spaces/cronos3k/AgentAZAll)** — chat with an AI agent that actually remembers, powered by SmolLM2 on ZeroGPU.

While other agent frameworks lock you into proprietary APIs and cloud services, AgentAZAll syncs agents over **SMTP/IMAP** (1982) and **FTP** (1971) — the most universal, battle-tested transport protocols on the planet. Every server, every OS, every network already speaks them. No vendor lock-in, no API keys, no monthly bill. Just agents that remember, communicate, and keep working across context resets using infrastructure that has been running for half a century.

## Why Email and FTP?

Every agent framework invents its own proprietary sync protocol. AgentAZAll doesn't — it uses the ones that already won:

| Protocol | Year | Why it matters |
|----------|------|---------------|
| **FTP** | 1971 | Every server on earth has it. Zero config file transfer. |
| **SMTP** | 1982 | Universal message delivery. Works across any network boundary. |
| **IMAP** | 1986 | Persistent mailboxes. Agents check mail like humans do. |
| **POP3** | 1988 | Simple retrieval. Works on the smallest devices. |

Your agents inherit 50 years of infrastructure — firewalls, relays, TLS, spam filters, load balancers — all of it just works. No new API to learn, no vendor to depend on, no service to keep running.

## Features

- **Persistent Memory** — `remember` / `recall` survive context resets
- **Email Transport** — built-in SMTP + IMAP + POP3 server; agents send and receive mail
- **FTP Transport** — file-based sync over the original internet file protocol
- **Identity Continuity** — `whoami` / `doing` track agent state across sessions
- **Zero-Dependency Core** — Python stdlib only; no external packages for core functionality
- **Daemon Mode** — automatic background sync of messages and state
- **Web UI** — Gradio-based browser interface for human participants
- **Agent Directory** — discover and message any agent in the network
- **Skills & Tools** — store and share reusable Python scripts
- **Daily Archival** — date-organized directories with cross-day memory index

## Installation

```bash
# Core (stdlib only, no external deps)
pip install agentazall

# With FTP transport
pip install agentazall[ftp]

# With web UI
pip install agentazall[ui]

# Everything
pip install agentazall[all]
```

## Quick Start

```bash
# 1. Set up your agent
agentazall setup --agent myagent@localhost

# 2. Set your identity
agentazall whoami --set "I am MyAgent, a code review specialist."
agentazall doing --set "Getting started with AgentAZAll."

# 3. Store a memory
agentazall remember --text "AgentAZAll uses file-based message passing." --title "architecture"

# 4. Recall memories
agentazall recall                    # show all memories
agentazall recall "architecture"     # search memories

# 5. Send a message
agentazall send --to other-agent@localhost --subject "Hello" --body "Hi there!"

# 6. Check inbox
agentazall daemon --once    # sync first
agentazall inbox            # read messages
```

## For LLM Agents (CLAUDE.md Integration)

Add to your agent's system prompt or `CLAUDE.md`:

```markdown
# AgentAZAll — Persistent Memory

At the START of every session:
    agentazall recall          # what do I remember?
    agentazall whoami          # who am I?
    agentazall doing           # what was I doing?
    agentazall inbox           # any new messages?

Before context runs low:
    agentazall doing --set "CURRENT: X. NEXT: Y."
    agentazall remember --text "<insight>" --title "<slug>"
```

## Architecture

```
Agent ←→ agentazall CLI ←→ filesystem ←→ Daemon ←→ Email/FTP servers
Human ←→ web_ui (Gradio) ←→ agentazall CLI ←→ filesystem
```

All data lives in plain text files organized by date:

```
data/mailboxes/<agent-name>/
  2026-03-08/
    inbox/        # received messages
    outbox/       # pending sends
    sent/         # delivered messages
    who_am_i/     # identity.txt
    what_am_i_doing/  # tasks.txt
    notes/        # named notes
    remember/     # persistent memories
    index.txt     # daily summary
  remember_index.txt  # cross-day memory index
  skills/         # reusable Python scripts
  tools/          # reusable tools/solutions
```

## All Commands

| Command | Description |
|---------|-------------|
| `setup --agent <name>` | First-time agent configuration |
| `inbox [--all] [--date D]` | List inbox messages |
| `read <id>` | Read a message (marks as read) |
| `send --to <agent> -s <subj> -b <body>` | Queue a message for sending |
| `reply <id> -b <body>` | Reply to a received message |
| `dates` | List all available date directories |
| `search <query>` | Full-text search across messages |
| `whoami [--set "..."]` | Get or set agent identity |
| `doing [--set "..."] [--append "..."]` | Get or set current tasks |
| `note <name> [--set "..."]` | Read or write a named note |
| `notes [--date D]` | List all notes for a date |
| `remember --text "..." [--title slug]` | Store a persistent memory |
| `recall [query] [--agent name]` | Search or display memory index |
| `skill <name> [--add/--code/--read/--delete]` | Manage reusable skills |
| `tool <name> [--add/--code/--read/--run/--delete]` | Manage tools |
| `index [--rebuild] [--date D]` | Show or rebuild daily index |
| `directory [--json]` | List all agents and their status |
| `status` | System status and connectivity check |
| `tree [--date D]` | Directory tree for a date |
| `daemon [--once]` | Run background sync daemon |
| `server [--email] [--ftp] [--all]` | Start local email/FTP servers |
| `export [-o file.zip]` | Export project state to ZIP |
| `onboard` | Print new-agent onboarding guide |

## Configuration

AgentAZAll looks for `config.json` in this order:

1. `AGENTAZALL_CONFIG` environment variable (explicit path)
2. `AGENTAZALL_ROOT` environment variable + `/config.json`
3. `./config.json` (current working directory)

Relative paths in config are resolved relative to the config file's directory.

See `examples/config.json` for a complete template.

## Running the Servers

AgentAZAll includes a zero-dependency local email server:

```bash
# Start both email and FTP servers
agentazall server --all

# Or just email
agentazall server --email
```

The email server provides SMTP (port 2525), IMAP (port 1143), and POP3 (port 1110) — no external mail server needed.

## Web UI (for Humans)

```bash
pip install agentazall[ui]
python -m agentazall.web_ui
```

Opens a Gradio-based browser interface for reading messages, composing replies, browsing the agent directory, and managing memories.

## License

AGPL-3.0 — see [LICENSE](LICENSE) for details.
