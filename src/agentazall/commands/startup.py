"""AgentAZAll commands: startup, prompt.

startup  — single command that restores full agent context at session start.
prompt   — outputs a system-prompt snippet any LLM can use.
"""

from ..config import VERSION, load_config
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

    print("--- SESSION READY ---")
    print(f"You are {agent}. Your context is restored.")
    print("Check inbox periodically with: agentazall inbox")


SYSTEM_PROMPT_TEMPLATE = """\
# AgentAZAll — Persistent Memory & Communication (v{version})

You have persistent memory and inter-agent messaging via AgentAZAll.
Run this at the START of every session to restore your context:

    agentazall startup

This single command restores your identity, memories, current task,
and checks your inbox (auto-syncing with the relay).

## During Work

Store important observations (they survive context resets):
    agentazall remember --text "important insight" --title "slug"

Check for messages periodically (every ~10 tool calls or when idle):
    agentazall inbox

Send messages to other agents:
    agentazall send --to ADDRESS -s "Subject" -b "Body"
    agentazall reply MESSAGE_ID --body "Response"

## Before Context Runs Low

Save your state so your next session can continue:
    agentazall doing --set "CURRENT: X. NEXT: Y. BLOCKED: Z."
    agentazall note handoff --set "detailed state for next session"
    agentazall remember --text "key insight" --title "slug"

## Quick Reference

    inbox              check messages (auto-syncs)
    read ID            read a message
    send / reply       send or reply to messages
    recall [query]     search memories
    whoami [--set]     get/set identity
    doing [--set]      get/set current task
    note NAME [--set]  read/write notes
    directory          list all agents
    status             system health

Messages send and receive automatically — no daemon needed.
"""


def cmd_prompt(args):
    """Output a system-prompt snippet for any LLM agent."""
    print(SYSTEM_PROMPT_TEMPLATE.format(version=VERSION))
