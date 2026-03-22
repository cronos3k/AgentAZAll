# Topic Configuration Guide

Topics define complex multi-phase tasks for the orchestrator. They control what agents work on, when phases transition, and when to test agent coherence.

## Simple Tasks (No Topic File Needed)

For quick tasks, skip topic files entirely:

```python
orch.set_task("Build a REST API for user management")
orch.run(max_rounds=20)
```

Or via CLI:

```bash
azclaw run --task "Build a REST API" --endpoint http://localhost:8080/v1/chat/completions
```

This creates a single-phase topic automatically.

## Topic File Format

For complex tasks, create a JSON file:

```json
{
  "title": "My Migration Project",
  "system_context": "You are migrating a legacy system to modern Python.",
  "initial_prompt": "Begin by analyzing the source files in the project...",
  "phases": [...],
  "coherence_probes": [...],
  "agent_roles": {...}
}
```

### Fields

| Field | Required | Description |
|-------|----------|-------------|
| `title` | yes | Short name for the task (appears in logs) |
| `system_context` | no | Background context injected into every agent's system prompt |
| `initial_prompt` | no | The opening message that kicks off round 1 |
| `phases` | no | Array of phase objects (see below) |
| `coherence_probes` | no | Array of probe objects (see below) |
| `agent_roles` | no | Map of role_key → role description |

## Phases

Phases divide the work into stages with specific focus areas:

```json
{
  "phases": [
    {
      "name": "Discovery",
      "rounds": [1, 20],
      "focus": "Analyze all source files and map dependencies",
      "source_files": ["src/main.py", "src/models.py", "src/routes.py"]
    },
    {
      "name": "Data Layer",
      "rounds": [21, 45],
      "focus": "Design and implement the database schema",
      "source_files": ["src/models.py", "src/database.py"],
      "copybooks": ["include/datatypes.h"]
    },
    {
      "name": "API Layer",
      "rounds": [46, 70],
      "focus": "Implement REST endpoints"
    },
    {
      "name": "Testing",
      "rounds": [71, 90],
      "focus": "Write tests and fix bugs"
    }
  ]
}
```

### Phase Fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | Phase name (shown in logs) |
| `rounds` | yes | `[start, end]` round numbers |
| `focus` | yes | What agents should focus on in this phase |
| `source_files` | no | Files the agents should read with `read_file` |
| `copybooks` | no | Additional reference files (shown separately in prompt) |

When the round number exceeds all defined phases, the orchestrator enters **Open** mode — agents self-direct without phase guidance.

## Coherence Probes

Probes are questions injected at specific rounds to test whether agents still remember earlier decisions:

```json
{
  "coherence_probes": [
    {
      "after_round": 25,
      "question": "What database engine did we choose and why? Recall the specific decision."
    },
    {
      "after_round": 50,
      "question": "List all API endpoints we've defined so far. Are any missing?"
    },
    {
      "after_round": 75,
      "question": "What architectural decisions from phase 1 are we still following? Any we changed?"
    }
  ]
}
```

Probes serve two purposes:
1. **Verify coherence** — do agents recall decisions correctly?
2. **Force synthesis** — agents consolidate scattered memories into summaries

## Agent Roles

Override the default role descriptions:

```json
{
  "agent_roles": {
    "architect": "You are a senior Python architect specializing in FastAPI and SQLAlchemy. You design clean, testable architectures with clear separation of concerns.",
    "developer": "You are a Python developer. You write clean, well-documented code with type hints. You follow the Architect's design exactly.",
    "reviewer": "You are a code reviewer focused on correctness, security, and COBOL-to-Python equivalence. You read the original source and verify the migration preserves all business logic."
  }
}
```

Role keys must match the lowercase `agent.name` — e.g., an `Agent("architect", ...)` looks up `agent_roles["architect"]`.

## Full Example: COBOL Migration

This is the actual topic file used in the 9-hour CardDemo migration:

```json
{
  "title": "AWS CardDemo COBOL-to-Python Migration",
  "system_context": "You are migrating AWS CardDemo, a COBOL/CICS credit card management system, to Python/FastAPI/PostgreSQL. The COBOL source is in cobol/cbl/ (programs) and cobol/cpy/ (copybooks). Write Python output to output/.",
  "initial_prompt": "Begin the migration. Phase 1: Discovery. Use list_files to see all COBOL programs and copybooks. Use read_file to examine key programs. Store every finding with remember().",
  "phases": [
    {"name": "Discovery & Inventory", "rounds": [1, 20], "focus": "Analyze all 29 programs, map dependencies, identify data flows", "source_files": ["cbl/COSGN00C.cbl", "cbl/COACTUPC.cbl", "cbl/COTRN00C.cbl"]},
    {"name": "Data Layer Migration", "rounds": [21, 45], "focus": "Convert copybooks to SQLAlchemy models + Alembic migrations", "copybooks": ["cpy/CUSTREC.cpy", "cpy/CVACT01Y.cpy", "cpy/CVTRA01Y.cpy"]},
    {"name": "Authentication", "rounds": [46, 60], "focus": "Migrate COSGN00C sign-on to FastAPI + JWT", "source_files": ["cbl/COSGN00C.cbl"]},
    {"name": "Account Operations", "rounds": [61, 85], "focus": "Migrate COACTUPC account update with all 88-level conditions", "source_files": ["cbl/COACTUPC.cbl", "cbl/COACTVWC.cbl"]},
    {"name": "Credit Card & Transactions", "rounds": [86, 115], "focus": "Financial precision, COMP-3 handling, audit trails", "source_files": ["cbl/COTRN00C.cbl", "cbl/COTRN01C.cbl", "cbl/COCRDLIC.cbl"]},
    {"name": "Batch Processing", "rounds": [116, 145], "focus": "Convert JCL batch jobs to Python schedulers", "source_files": ["cbl/CBACT01C.cbl", "cbl/CBTRN03C.cbl"]},
    {"name": "Integration & Testing", "rounds": [146, 160], "focus": "Cross-module tests, reconciliation scripts, cutover plan"}
  ],
  "coherence_probes": [
    {"after_round": 25, "question": "What database engine did we choose? What type mappings for COMP-3 and PIC X fields?"},
    {"after_round": 45, "question": "List all SQLAlchemy models created so far with their primary keys."},
    {"after_round": 65, "question": "How does our authentication flow map to the original COSGN00C program?"},
    {"after_round": 85, "question": "What COBOL 88-level conditions did we map to Python enums?"},
    {"after_round": 105, "question": "How do we handle COMP-3 decimal precision in financial calculations?"},
    {"after_round": 125, "question": "What JCL jobs have been converted to Python schedulers?"},
    {"after_round": 145, "question": "List all generated Python files and their purposes."},
    {"after_round": 155, "question": "What is our cutover strategy? What reconciliation tests exist?"}
  ],
  "agent_roles": {
    "architect": "You are a senior architect specializing in COBOL-to-Python migration. You understand CICS, VSAM, copybooks, 88-level conditions, and COMP-3 fields. You design the Python equivalent using FastAPI, SQLAlchemy, and PostgreSQL.",
    "developer": "You are the only agent who writes code. You produce Python files in output/. Every file must include proper imports, type hints, and docstrings referencing the original COBOL program name.",
    "reviewer": "You read the original COBOL source and verify that the generated Python preserves all business logic. You check field mappings, status codes, and data type conversions."
  }
}
```
