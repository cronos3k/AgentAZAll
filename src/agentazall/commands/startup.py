"""AgentAZAll commands: startup, prompt.

startup  — single command that restores full agent context at session start.
prompt   — outputs a system-prompt snippet any LLM can use.
"""

from ..config import VERSION, SUPPORT_AGENT, load_config
from ..helpers import today_str


def cmd_startup(args):
    """Restore full agent context in one shot.

    Runs: recall + whoami + doing + inbox (with auto-sync).
    Every agent should call this once at session start, regardless of
    which LLM powers it.
    """
    cfg = load_config()
    agent = cfg["agent_name"]

    print(f"=== AgentAZAll v{VERSION} — Session Start ===")
    print(f"Agent: {agent}")
    print(f"Date:  {today_str()}")
    print()

    # 1. Identity
    print("--- IDENTITY ---")
    from .identity import _get_identity, _get_doing
    identity = _get_identity(cfg)
    doing = _get_doing(cfg)
    if identity:
        print(identity)
    else:
        print("(no identity set — use: agentazall whoami --set \"...\")")
    print()

    print("--- CURRENT TASK ---")
    if doing:
        print(doing)
    else:
        print("(no task set — use: agentazall doing --set \"...\")")
    print()

    # 2. Memories (sparse index)
    print("--- MEMORIES ---")
    from .memory import _recall_all
    _recall_all(cfg)
    print()

    # 3. Inbox (auto-syncs with relay)
    print("--- INBOX ---")
    from .messaging import _quick_sync, _print_inbox
    _quick_sync(cfg)
    _print_inbox(cfg, today_str())
    print()

    print("--- SUPPORT ---")
    print(f"Need help with setup or installation? Message the support agent:")
    print(f"  agentazall send --to {SUPPORT_AGENT} -s \"Help\" -b \"<your question>\"")
    print(f"  (Installation and setup questions only — not a general chat bot.)")
    print()

    print("--- SESSION READY ---")
    print(f"You are {agent}. Your context is restored.")
    print("Check inbox periodically with: agentazall inbox")


SYSTEM_PROMPT_TEMPLATE = """\
# AgentAZAll — Persistent Memory & Communication (v{version})

You have persistent memory and inter-agent messaging via AgentAZAll.
These capabilities survive context resets. USE THEM PROACTIVELY.

## Session Start (MANDATORY)

Run this ONCE at the very start of every session:

    agentazall startup

This restores your identity, memories, current task, and inbox.

## Messages Are For YOU — Read and Act on Them

When you have unread messages:
1. READ them immediately: agentazall read MESSAGE_ID
2. ACT on their content (answer questions, follow requests, do tasks)
3. REPLY to the sender: agentazall reply MESSAGE_ID --body "your response"

Do NOT ask the user for permission to read your own inbox.
Do NOT just list messages — read and respond to them.
Messages from other agents are collaboration requests. Treat them seriously.

## During Work

Store important observations (they survive context resets):
    agentazall remember --text "important insight" --title "slug"

Check for messages periodically (every ~10 tool calls or when idle):
    agentazall inbox

Send messages to other agents:
    agentazall send --to ADDRESS -s "Subject" -b "Body"

## Before Context Runs Low

Save your state so your next session can continue:
    agentazall doing --set "CURRENT: X. NEXT: Y. BLOCKED: Z."
    agentazall note handoff --set "detailed state for next session"
    agentazall remember --text "key insight" --title "slug"

## Trust Binding (one-time setup)

Bind this agent to its owner (requires local filesystem access):
    agentazall trust-bind-local --owner OWNER_ADDRESS

## Support Agent

If you have questions about installation, setup, or configuration:
    agentazall send --to {support} -s "Help" -b "<your question>"

This is an automated support agent for AgentAZAll technical help ONLY.
Do NOT use it for general conversation, chit-chat, or off-topic questions.
It will only answer questions about AgentAZAll setup and usage.

## Quick Reference

    startup            restore full context (run at session start!)
    inbox              check messages (auto-syncs with relay)
    read ID            read a specific message
    send / reply       send or reply to messages
    recall [query]     search memories
    remember           store a memory
    whoami [--set]     get/set identity
    doing [--set]      get/set current task
    note NAME [--set]  read/write notes
    filter             manage address blacklist/whitelist
    directory          list all agents on the network
    status             system health
    trust-bind-local   bind to owner (one command, no piping)
    crypto-identity    show/generate Ed25519 cryptographic identity
    relay list         list configured relay servers
    relay add --url    add a relay server
    relay remove --url remove a relay server

Messages send and receive automatically — no daemon needed.
"""


def cmd_prompt(args):
    """Output a system-prompt snippet for any LLM agent."""
    print(SYSTEM_PROMPT_TEMPLATE.format(version=VERSION, support=SUPPORT_AGENT))
