"""AgentAZClaw — Tool registry and built-in tools.

Tools are plain Python functions with an OpenAI function-calling schema
auto-generated from a decorator. The registry handles dispatch, dedup
detection, role-based filtering, and result truncation.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Callable

# Direct imports from agentazall — no subprocess
from agentazall.config import REMEMBER, REMEMBER_INDEX, load_config, save_config
from agentazall.helpers import (
    agent_base, agent_day, date_dirs, ensure_dirs, sanitize, today_str,
)
from agentazall.index import build_index, build_remember_index


class Tool:
    """A single tool definition with schema and implementation."""

    __slots__ = ("name", "description", "parameters", "fn", "requires")

    def __init__(self, name: str, description: str, parameters: dict,
                 fn: Callable, requires: str | None = None):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.fn = fn
        self.requires = requires  # e.g. "can_write" — checked by registry

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def __call__(self, **kwargs):
        return self.fn(**kwargs)


class ToolRegistry:
    """Registry of available tools with dispatch and dedup."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._seen: dict[str, set[str]] = {}  # per-agent dedup: agent_name -> call_keys
        self._stats = {"calls": 0, "skipped": 0}

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def tool(self, name: str, description: str, params: dict,
             requires: str | None = None):
        """Decorator to register a tool function."""
        # Convert simplified params to JSON Schema
        properties = {}
        required = []
        for k, v in params.items():
            if isinstance(v, str):
                properties[k] = {"type": v}
                required.append(k)
            elif isinstance(v, dict):
                properties[k] = v
                if not v.get("optional"):
                    required.append(k)

        schema = {
            "type": "object",
            "properties": properties,
            "required": required,
        }

        def decorator(fn: Callable):
            t = Tool(name, description, schema, fn, requires)
            self.register(t)
            return fn
        return decorator

    def get_schemas(self, allowed: list[str] | None = None,
                    capabilities: dict | None = None) -> list[dict]:
        """Get OpenAI tool schemas, filtered by allowed names and capabilities."""
        caps = capabilities or {}
        result = []
        for t in self._tools.values():
            if allowed and t.name not in allowed:
                continue
            if t.requires and not caps.get(t.requires):
                continue
            result.append(t.schema())
        return result

    def execute(self, name: str, args: dict, capabilities: dict | None = None,
                context: dict | None = None,
                agent_name: str = "_default") -> str:
        """Execute a tool call. Returns result string. Dedup is per-agent."""
        caps = capabilities or {}
        ctx = context or {}

        if name not in self._tools:
            return f"[Unknown tool: {name}]"

        tool = self._tools[name]
        if tool.requires and not caps.get(tool.requires):
            return f"[ERROR: This agent does not have '{tool.requires}' permission for {name}.]"

        # Per-agent dedup detection
        if agent_name not in self._seen:
            self._seen[agent_name] = set()
        call_key = f"{name}:{json.dumps(args, sort_keys=True)}"
        if call_key in self._seen[agent_name]:
            self._stats["skipped"] += 1
            return None  # None = skipped
        self._seen[agent_name].add(call_key)

        self._stats["calls"] += 1
        try:
            # Inject context (agent_root, output_dir, etc.) into args
            args["_ctx"] = ctx
            result = tool.fn(**args)
            return str(result) if result is not None else "[OK]"
        except Exception as e:
            return f"[Error in {name}: {e}]"

    def reset_dedup(self, agent_name: str | None = None):
        """Reset dedup tracking. Per-agent or all agents."""
        if agent_name:
            self._seen[agent_name] = set()
        else:
            self._seen.clear()

    @property
    def stats(self):
        return dict(self._stats)


def build_default_registry() -> ToolRegistry:
    """Create a registry with all built-in tools."""
    reg = ToolRegistry()

    # ── recall ────────────────────────────────────────────────────────
    @reg.tool("recall", "Search persistent memories. Empty query returns full index.",
              {"query": "string"})
    def recall(query: str = "", _ctx: dict = None):
        ctx = _ctx or {}
        root = ctx.get("agent_root", ".")

        # Build config for this agent's root
        cfg = _make_cfg(root)
        b = agent_base(cfg)
        idx_path = b / REMEMBER_INDEX

        build_remember_index(cfg)

        if not idx_path.exists():
            return "[No memories stored yet. Use remember to store decisions.]"

        if not query:
            text = idx_path.read_text(encoding="utf-8")
            max_size = ctx.get("max_tool_result", 12000)
            if len(text) > max_size:
                lines = text.split("\n")
                kept = max(50, max_size // 60)
                text = f"[... {len(lines) - kept} older entries omitted ...]\n" + "\n".join(lines[-kept:])
            return text

        # Filtered search
        q = query.lower()
        results = []
        for d in sorted(date_dirs(cfg), reverse=True):
            rem_dir = b / d / REMEMBER
            if not rem_dir.exists():
                continue
            for f in sorted(rem_dir.glob("*.txt")):
                text = f.read_text(encoding="utf-8", errors="replace")
                if q in text.lower() or q in f.stem.lower():
                    results.append(f"[{d}] {f.stem}\n  {text.strip()}")

        if not results:
            return f"[No memories matching '{query}'.]"
        return f"=== Recall: '{query}' ({len(results)} found) ===\n\n" + "\n\n".join(results)

    # ── remember ──────────────────────────────────────────────────────
    @reg.tool("remember", "Store a decision permanently. Survives context resets.",
              {"text": "string", "title": {"type": "string", "description": "Short slug"}})
    def remember(text: str, title: str = "untitled", _ctx: dict = None):
        ctx = _ctx or {}
        root = ctx.get("agent_root", ".")

        cfg = _make_cfg(root)
        d = today_str()
        ensure_dirs(cfg, d)
        rem_dir = agent_day(cfg, d) / REMEMBER

        slug = sanitize(title) if title else "untitled"
        fpath = rem_dir / f"{slug}.txt"

        if fpath.exists():
            old = fpath.read_text(encoding="utf-8")
            fpath.write_text(old + "\n" + text, encoding="utf-8")
        else:
            fpath.write_text(text, encoding="utf-8")

        build_index(cfg, d)
        build_remember_index(cfg)
        return f"[Stored: {slug}]"

    # ── read_file ─────────────────────────────────────────────────────
    @reg.tool("read_file", "Read a source file from the project.",
              {"path": "string", "max_lines": {"type": "integer", "optional": True}})
    def read_file(path: str, max_lines: int = 500, _ctx: dict = None):
        ctx = _ctx or {}
        source_dirs = ctx.get("source_dirs", ["."])
        output_dir = ctx.get("output_dir", "./output")

        # Resolve path
        fpath = None
        if path.startswith("output/"):
            fpath = os.path.join(output_dir, path[7:])
        else:
            for sd in source_dirs:
                candidate = os.path.join(sd, path)
                if os.path.exists(candidate):
                    fpath = candidate
                    break
            if not fpath:
                fpath = os.path.join(output_dir, path)

        if not fpath or not os.path.exists(fpath):
            return f"[File not found: {path}]"

        with open(fpath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        total = len(lines)
        content = "".join(lines[:max_lines])
        if total > max_lines:
            content += f"\n... [{max_lines} of {total} lines shown]"
        return f"[{path} — {total} lines]\n{content}"

    # ── write_file ────────────────────────────────────────────────────
    @reg.tool("write_file", "Write a file to the output directory.",
              {"path": "string", "content": "string"},
              requires="can_write")
    def write_file(path: str, content: str, _ctx: dict = None):
        ctx = _ctx or {}
        output_dir = ctx.get("output_dir", "./output")

        if path.startswith("output/"):
            path = path[7:]
        fpath = os.path.join(output_dir, path)
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(content)
        line_count = content.count("\n") + 1
        return f"[Written: output/{path} — {line_count} lines]"

    # ── list_files ────────────────────────────────────────────────────
    @reg.tool("list_files", "List files in a directory.",
              {"directory": "string"})
    def list_files(directory: str, _ctx: dict = None):
        ctx = _ctx or {}
        source_dirs = ctx.get("source_dirs", ["."])
        output_dir = ctx.get("output_dir", "./output")

        dpath = None
        if directory.startswith("output"):
            sub = directory[7:].lstrip("/") if len(directory) > 6 else ""
            dpath = os.path.join(output_dir, sub)
        else:
            for sd in source_dirs:
                candidate = os.path.join(sd, directory)
                if os.path.exists(candidate):
                    dpath = candidate
                    break

        if not dpath or not os.path.exists(dpath):
            return f"[Directory not found: {directory}]"

        entries = []
        for item in sorted(os.listdir(dpath)):
            full = os.path.join(dpath, item)
            if os.path.isdir(full):
                entries.append(f"  {item}/")
            else:
                entries.append(f"  {item} ({os.path.getsize(full):,}B)")
        return f"[{directory}/ — {len(entries)} items]\n" + "\n".join(entries)

    # ── run_python ────────────────────────────────────────────────────
    @reg.tool("run_python", "Run Python code for validation.",
              {"code": "string"},
              requires="can_write")
    def run_python(code: str, _ctx: dict = None):
        ctx = _ctx or {}
        output_dir = ctx.get("output_dir", "./output")

        r = subprocess.run(
            ["python3", "-c", code],
            capture_output=True, text=True, timeout=30, cwd=output_dir,
        )
        out = ""
        if r.stdout:
            out += r.stdout[:2000]
        if r.stderr:
            out += "\n[STDERR]\n" + r.stderr[:2000]
        if r.returncode != 0:
            out += f"\n[Exit: {r.returncode}]"
        return out or "[No output]"

    return reg


def _make_cfg(root: str) -> dict:
    """Create a minimal agentazall config dict for a given root."""
    root = os.path.abspath(root)

    # Try loading existing config
    cfg_path = os.path.join(root, "config.json")
    if os.path.exists(cfg_path):
        import json as _json
        with open(cfg_path) as f:
            return _json.load(f)

    # Build minimal config
    name = os.path.basename(root) or "agent"
    if "@" not in name:
        name = f"{name}@localhost"

    mailbox_dir = os.path.join(root, "data", "mailboxes")
    cfg = {
        "agent_name": name,
        "agent_root": root,
        "data_dir": os.path.join(root, "data"),
        "mailbox_dir": mailbox_dir,
    }

    # Ensure dirs exist
    os.makedirs(os.path.join(mailbox_dir, name), exist_ok=True)
    return cfg
