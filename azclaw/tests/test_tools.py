"""Tests for ToolRegistry and built-in tools."""

import os
import pytest
from azclaw.tools import ToolRegistry, Tool, build_default_registry


def test_tool_schema():
    t = Tool("test", "A test tool", {"type": "object", "properties": {}}, lambda: "ok")
    schema = t.schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "test"


def test_registry_register():
    reg = ToolRegistry()
    t = Tool("foo", "Foo tool", {"type": "object", "properties": {}}, lambda **kw: "bar")
    reg.register(t)
    schemas = reg.get_schemas()
    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == "foo"


def test_registry_decorator():
    reg = ToolRegistry()

    @reg.tool("greet", "Say hello", {"name": "string"})
    def greet(name: str, _ctx=None):
        return f"Hello, {name}!"

    schemas = reg.get_schemas()
    assert len(schemas) == 1
    result = reg.execute("greet", {"name": "World"})
    assert result == "Hello, World!"


def test_registry_dedup():
    reg = ToolRegistry()

    @reg.tool("echo", "Echo input", {"text": "string"})
    def echo(text: str, _ctx=None):
        return text

    r1 = reg.execute("echo", {"text": "hello"}, agent_name="agent1")
    assert r1 == "hello"

    r2 = reg.execute("echo", {"text": "hello"}, agent_name="agent1")
    assert r2 is None  # skipped for same agent

    # Different agent should NOT be dedup'd
    r3 = reg.execute("echo", {"text": "hello"}, agent_name="agent2")
    assert r3 == "hello"  # not skipped — different agent


def test_registry_reset_dedup():
    reg = ToolRegistry()

    @reg.tool("echo", "Echo", {"text": "string"})
    def echo(text: str, _ctx=None):
        return text

    reg.execute("echo", {"text": "a"}, agent_name="agent1")
    reg.reset_dedup("agent1")
    r = reg.execute("echo", {"text": "a"}, agent_name="agent1")
    assert r == "a"  # not skipped after reset


def test_registry_capability_filter():
    reg = ToolRegistry()

    @reg.tool("read", "Read", {"path": "string"})
    def read(path: str, _ctx=None):
        return "content"

    @reg.tool("write", "Write", {"path": "string"}, requires="can_write")
    def write(path: str, _ctx=None):
        return "ok"

    # Without can_write
    schemas = reg.get_schemas(capabilities={"can_write": False})
    names = [s["function"]["name"] for s in schemas]
    assert "read" in names
    assert "write" not in names

    # With can_write
    schemas = reg.get_schemas(capabilities={"can_write": True})
    names = [s["function"]["name"] for s in schemas]
    assert "write" in names


def test_registry_allowed_filter():
    reg = ToolRegistry()

    @reg.tool("a", "Tool A", {"x": "string"})
    def a(x: str, _ctx=None): return "a"

    @reg.tool("b", "Tool B", {"x": "string"})
    def b(x: str, _ctx=None): return "b"

    schemas = reg.get_schemas(allowed=["a"])
    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == "a"


def test_default_registry_has_builtins():
    reg = build_default_registry()
    schemas = reg.get_schemas(capabilities={"can_write": True})
    names = [s["function"]["name"] for s in schemas]
    assert "recall" in names
    assert "remember" in names
    assert "read_file" in names
    assert "write_file" in names
    assert "list_files" in names
    assert "run_python" in names


def test_remember_and_recall(tmp_path):
    reg = build_default_registry()
    root = str(tmp_path / "agent")
    os.makedirs(root, exist_ok=True)
    ctx = {"agent_root": root}

    # Remember
    r = reg.execute("remember", {"text": "PostgreSQL chosen", "title": "db-choice"},
                    context=ctx)
    assert "Stored" in r

    # Recall
    reg.reset_dedup()
    r = reg.execute("recall", {"query": ""},  context=ctx)
    assert "db-choice" in r


def test_write_and_read_file(tmp_path):
    reg = build_default_registry()
    out = str(tmp_path / "output")
    os.makedirs(out, exist_ok=True)
    ctx = {"output_dir": out, "source_dirs": [str(tmp_path)]}

    # Write
    r = reg.execute("write_file", {"path": "test.py", "content": "print('hello')"},
                    capabilities={"can_write": True}, context=ctx)
    assert "Written" in r

    # Read
    reg.reset_dedup()
    r = reg.execute("read_file", {"path": "output/test.py"}, context=ctx)
    assert "print('hello')" in r


def test_unknown_tool():
    reg = ToolRegistry()
    r = reg.execute("nonexistent", {})
    assert "Unknown tool" in r
