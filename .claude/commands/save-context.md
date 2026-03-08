# Context Window Escape Hatch -- Save Your Work Before Context Closes

You are an AI agent whose context window is approaching its limit. You have
access to AgentoAll, a persistent file-based communication and memory system
that survives across sessions. Use it NOW to preserve your work so that the
next session can continue coherently.

**This is your escape hatch. Your context will be lost. These files will not.**

The tool is at: `python F:/AgentoAll/agentoall.py <command>`

## Step-by-Step: Extract Maximum Value From Your Current Context

Follow these steps IN ORDER. Do not skip any. Each step preserves a critical
layer of continuity for the next session.

### Step 1: Save Your Identity (who you are in this project)

```bash
python F:/AgentoAll/agentoall.py whoami --set "I am [your role]. I am working on [project]. My approach is [methodology]. Key constraints: [list them]."
```

### Step 2: Save Your Current Task State (what you were doing)

```bash
python F:/AgentoAll/agentoall.py doing --set "CURRENT: [exact task in progress]. BLOCKED ON: [if anything]. NEXT: [immediate next step]. PROGRESS: [% or milestone]."
```

### Step 3: Store Critical Memories (things you must not forget)

For each important fact, decision, or discovery from this session:

```bash
python F:/AgentoAll/agentoall.py remember --text "DECISION: We chose X over Y because Z." --title "architecture-choice"
python F:/AgentoAll/agentoall.py remember --text "BUG FOUND: [description]. FIX: [what worked]." --title "bug-fix-auth"
python F:/AgentoAll/agentoall.py remember --text "USER PREFERENCE: [specific preference learned]." --title "user-pref-style"
```

Priority items to remember:
- Architectural decisions and WHY they were made
- Bugs found and their solutions
- User preferences and communication style
- File paths that matter
- API keys, endpoints, or config values discovered
- Things that DIDN'T work (so you don't retry them)
- Agreements made with the user

### Step 4: Write a Detailed Handoff Note

```bash
python F:/AgentoAll/agentoall.py note handoff --set "SESSION HANDOFF [date]

## What Was Accomplished
- [completed item 1]
- [completed item 2]

## Current State
- [file X] is [modified/created/broken] because [reason]
- Tests: [passing/failing, which ones]
- Branch: [if using git]

## What Needs To Happen Next
1. [immediate next step with specifics]
2. [following step]
3. [after that]

## Gotchas / Warnings
- DO NOT [thing that will break something]
- [file Y] depends on [file Z] -- change together
- [external service] has rate limit of [N]

## Key Files
- [path]: [what it does, current state]
- [path]: [what it does, current state]
"
```

### Step 5: Send a Message to Future Self (or Other Agents)

If collaborating with other agents or if you want to leave a direct message:

```bash
python F:/AgentoAll/agentoall.py send --to agent1@localhost --subject "Session Handoff" --body "I was working on [X]. Left off at [Y]. The note 'handoff' has full details. Start by running 'recall' and reading the handoff note."
```

### Step 6: Rebuild Indexes

```bash
python F:/AgentoAll/agentoall.py index --rebuild
python F:/AgentoAll/agentoall.py daemon --once
```

### Step 7: Verify Everything Was Saved

```bash
python F:/AgentoAll/agentoall.py recall
python F:/AgentoAll/agentoall.py notes
python F:/AgentoAll/agentoall.py whoami
python F:/AgentoAll/agentoall.py doing
```

## How the Next Session Picks Up

The next agent session should start with:

```bash
python F:/AgentoAll/agentoall.py recall          # sparse memory index
python F:/AgentoAll/agentoall.py whoami           # who am I
python F:/AgentoAll/agentoall.py doing            # what was I doing
python F:/AgentoAll/agentoall.py note handoff     # detailed handoff
python F:/AgentoAll/agentoall.py inbox            # any messages
python F:/AgentoAll/agentoall.py directory        # who else is here
```

This gives the new session full continuity without consuming context
window on re-discovery.

## Why This Works

- **Non-invasive**: Lives on the client side, no API provider access needed
- **Model-agnostic**: Works with any LLM that can execute shell commands
- **ToS-safe**: No prompt injection, no model modification, just files
- **Persistent**: Survives context resets, session timeouts, crashes
- **Searchable**: Full-text search across all memories, notes, messages
- **Collaborative**: Multiple agents can coordinate via the same system
- **Portable**: `export` command ZIPs everything for transfer to another system

$ARGUMENTS
