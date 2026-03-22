# Custom Tools Guide

AZClaw comes with 6 built-in tools. You can add your own.

## Built-in Tools

| Tool | Description | Requires |
|------|-------------|----------|
| `recall` | Search persistent memories | — |
| `remember` | Store a decision permanently | — |
| `read_file` | Read source or output files | — |
| `list_files` | List files in directories | — |
| `write_file` | Write files to output/ | `can_write` |
| `run_python` | Execute Python code | `can_write` |

## Adding a Custom Tool

### Step 1: Get the Registry

```python
from azclaw import build_default_registry

registry = build_default_registry()  # includes all 6 built-ins
```

### Step 2: Register Your Tool

```python
@registry.tool(
    "search_code",                           # tool name
    "Search the codebase using ripgrep",     # description (shown to LLM)
    {"query": "string", "file_type": "string"},  # parameters
)
def search_code(query: str, file_type: str = "py", _ctx=None):
    import subprocess
    r = subprocess.run(
        ["rg", query, "--type", file_type, "."],
        capture_output=True, text=True, timeout=10,
    )
    return r.stdout[:5000] or "[No matches]"
```

### Step 3: Pass to Orchestrator

```python
from azclaw import Agent, Orchestrator

orch = Orchestrator(
    agents=[...],
    registry=registry,  # your custom registry
)
```

## Parameter Types

The `params` dict maps parameter names to types:

```python
# Simple — all required
{"query": "string", "count": "integer", "verbose": "boolean"}

# With defaults — mark as optional
{"query": "string", "max_results": {"type": "integer", "optional": True}}

# With descriptions
{"query": {"type": "string", "description": "The search query"}}
```

These are auto-converted to OpenAI function-calling JSON Schema.

## The `_ctx` Parameter

Every tool function receives a `_ctx` keyword argument with runtime context:

```python
def my_tool(query: str, _ctx=None):
    ctx = _ctx or {}
    agent_root = ctx.get("agent_root", ".")    # agent's memory directory
    output_dir = ctx.get("output_dir", ".")    # where files are written
    source_dirs = ctx.get("source_dirs", ["."])  # source code directories
    max_result = ctx.get("max_tool_result", 12000)  # result truncation limit
```

## Permission Gating

Restrict tools to agents with specific capabilities:

```python
@registry.tool(
    "deploy",
    "Deploy to production",
    {"service": "string"},
    requires="can_deploy",  # only agents with this capability can use it
)
def deploy(service: str, _ctx=None):
    ...
```

Then create agents with the capability:

```python
ops_agent = Agent("ops", can_write=True)
# In the agent's capabilities dict, add custom capabilities:
# (extend the Agent class or pass via registry.execute)
```

Currently, the built-in capability is `can_write`. For custom capabilities, override `Agent.capabilities`.

## Tool Result Truncation

Tool results longer than `max_tool_result` (default: 12,000 characters) are automatically truncated. If your tool returns large data, truncate it yourself for better control:

```python
@registry.tool("read_database", "Query the database", {"sql": "string"})
def read_database(sql: str, _ctx=None):
    results = db.execute(sql)
    # Return first 50 rows, not everything
    rows = results[:50]
    output = "\n".join(str(r) for r in rows)
    if len(results) > 50:
        output += f"\n... [{len(results)} total rows, showing first 50]"
    return output
```

## Dedup Behavior

If an agent calls the same tool with the same arguments twice in one turn, the second call is automatically skipped (returns `None`). This prevents degenerate loops where agents repeatedly call `recall("")`.

Dedup is tracked **per agent per round** — different agents can make the same call, and the same agent can make the same call in different rounds.

## Examples

### Run Shell Commands

```python
@registry.tool("shell", "Run a shell command", {"command": "string"}, requires="can_write")
def shell(command: str, _ctx=None):
    import subprocess
    r = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
    out = r.stdout[:3000]
    if r.stderr:
        out += "\n[STDERR]\n" + r.stderr[:1000]
    return out or "[No output]"
```

### Run Rust Code

```python
@registry.tool("run_rust", "Compile and test Rust code",
               {"command": "string"}, requires="can_write")
def run_rust(command: str = "check", _ctx=None):
    ctx = _ctx or {}
    output_dir = ctx.get("output_dir", ".")
    import subprocess
    r = subprocess.run(
        ["cargo", command],
        capture_output=True, text=True, timeout=120, cwd=output_dir,
    )
    out = r.stdout[:3000]
    if r.stderr:
        out += "\n[STDERR]\n" + r.stderr[:2000]
    return out or "[No output]"
```

### Web Search

```python
@registry.tool("web_search", "Search the web", {"query": "string"})
def web_search(query: str, _ctx=None):
    from urllib.request import urlopen, Request
    import json
    # Use a search API (SearXNG, Brave, etc.)
    url = f"http://localhost:8888/search?q={query}&format=json"
    with urlopen(url, timeout=10) as r:
        data = json.loads(r.read())
    results = data.get("results", [])[:5]
    return "\n\n".join(f"**{r['title']}**\n{r['url']}\n{r['content'][:200]}" for r in results)
```

### Read PDF

```python
@registry.tool("read_pdf", "Extract text from a PDF file", {"path": "string"})
def read_pdf(path: str, _ctx=None):
    import subprocess
    r = subprocess.run(["pdftotext", path, "-"], capture_output=True, text=True, timeout=30)
    return r.stdout[:10000] or "[Empty PDF or extraction failed]"
```
