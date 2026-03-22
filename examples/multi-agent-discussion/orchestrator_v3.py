#!/usr/bin/env python3
"""
AgentAZAll Multi-Agent Orchestrator v3 — Memory-First Edition

KEY DESIGN PRINCIPLES:
1. Context stays SMALL. Only last round in context. Everything else via recall().
2. Only the DEVELOPER writes files. Architect designs, Reviewer reviews.
3. Agents use recall() at the start of each turn, remember() after each decision.

This is what AgentAZAll is FOR. The orchestrator doesn't second-guess it.

Stop: touch /home/gregor/openclaw-demo/STOP
"""

import json
import time
import sys
import os
import subprocess
import urllib.request
import urllib.error
import re
import argparse
import signal
from datetime import datetime
from pathlib import Path

# ── Agent Configuration ──────────────────────────────────────────────
# ALL agents use Nemotron — only model that handles tool calling + COBOL analysis properly.
# Qwen MoE models failed: degenerate recall("") loops, XML hallucinations, 0 code written in 41 rounds.
# Nemotron: 231K tokens, 16 memories, 114 t/s in same test. Clear winner.
NEMOTRON_MODEL = "/home/gregor/.cache/lm-studio/models/lmstudio-community/NVIDIA-Nemotron-3-Nano-30B-A3B-GGUF/NVIDIA-Nemotron-3-Nano-30B-A3B-Q8_0.gguf"

AGENTS = [
    {
        "name": "Architect",
        "role_key": "architect",
        "endpoint": "http://127.0.0.1:8200/v1/chat/completions",
        "model_id": "nemotron-30b-a3b",
        "model_label": "Nemotron-3-Nano-30B-A3B-Q8_0",
        "agentazall_root": "./agents/architect",
        "max_tokens": 8192,
        "can_write_files": False,  # Architect designs, doesn't code
    },
    {
        "name": "Developer",
        "role_key": "developer",
        "endpoint": "http://127.0.0.1:8201/v1/chat/completions",
        "model_id": "nemotron-30b-a3b",
        "model_label": "Nemotron-3-Nano-30B-A3B-Q8_0",
        "agentazall_root": "./agents/developer",
        "max_tokens": 8192,
        "can_write_files": True,   # ONLY Developer writes code
    },
    {
        "name": "Reviewer",
        "role_key": "reviewer",
        "endpoint": "http://127.0.0.1:8202/v1/chat/completions",
        "model_id": "nemotron-30b-a3b",
        "model_label": "Nemotron-3-Nano-30B-A3B-Q8_0",
        "agentazall_root": "./agents/reviewer",
        "max_tokens": 8192,
        "can_write_files": False,  # Reviewer reads and critiques, doesn't write
    },
]

# Paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(SCRIPT_DIR, "results")
TOPICS_DIR = os.path.join(SCRIPT_DIR, "topics")
STOP_FILE = os.path.join(SCRIPT_DIR, "STOP")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
COBOL_ROOT = "/home/gregor/localcode/carddemo/app"

_shutdown = False

def _handle_signal(signum, frame):
    global _shutdown
    _shutdown = True
    print("\n  >> Signal received. Finishing round...")

signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)

def should_stop():
    if _shutdown:
        return "signal"
    if os.path.exists(STOP_FILE):
        return "stop-file"
    return None


# ── Utilities ────────────────────────────────────────────────────────

def estimate_tokens(text):
    return max(1, len(text) // 4) if text else 0

def strip_think(text):
    if not text:
        return ""
    stripped = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    if stripped and len(stripped) > 20:
        return stripped
    thinks = re.findall(r"<think>(.*?)</think>", text, flags=re.DOTALL)
    return "\n\n".join(t.strip() for t in thinks if t.strip()) if thinks else text.strip()

def load_topic(name):
    with open(os.path.join(TOPICS_DIR, f"{name}.json"), "r") as f:
        return json.load(f)


# ── Tool Definitions (per-role) ──────────────────────────────────────

def get_tools_for_agent(agent):
    """Return the tool schema appropriate for this agent's role."""
    # Everyone can read, list, recall, remember
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a source file. COBOL: 'cbl/COSGN00C.cbl', copybook: 'cpy/CUSTREC.cpy'. Python: 'output/models/customer.py'.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "max_lines": {"type": "integer", "default": 500}
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "List files: 'cobol/cbl', 'cobol/cpy', 'output', or sub-paths.",
                "parameters": {
                    "type": "object",
                    "properties": {"directory": {"type": "string"}},
                    "required": ["directory"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "recall",
                "description": "Search your persistent memories. Call with '' for all, or a query like 'database choice'. USE THIS FIRST every turn.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "remember",
                "description": "Store a decision/insight permanently. Survives all context resets. Store EVERY key decision.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "title": {"type": "string", "description": "Short slug, e.g. 'db-choice'"}
                    },
                    "required": ["text", "title"]
                }
            }
        },
    ]

    # Only Developer can write files and run Python
    if agent.get("can_write_files"):
        tools.extend([
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": "Write a Python file to output/. Creates parent dirs. YOU are the only agent who can write code.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Path under output/"},
                            "content": {"type": "string", "description": "Full file content"}
                        },
                        "required": ["path", "content"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "run_python",
                    "description": "Run Python code for validation. Runs in output/ directory.",
                    "parameters": {
                        "type": "object",
                        "properties": {"code": {"type": "string"}},
                        "required": ["code"]
                    }
                }
            },
        ])

    return tools


def _agent_env(agent):
    env = os.environ.copy()
    env["AGENTAZALL_ROOT"] = agent["agentazall_root"]
    env["PATH"] = os.path.expanduser("~/.local/bin") + os.pathsep + env.get("PATH", "")
    return env


def execute_tool(name, args, agent):
    """Execute a tool call and return result string."""
    try:
        if name == "read_file":
            path = args.get("path", "")
            max_lines = args.get("max_lines", 500)
            if path.startswith("output/"):
                fpath = os.path.join(OUTPUT_DIR, path[7:])
            elif path.startswith("cobol/"):
                fpath = os.path.join(COBOL_ROOT, path[6:])
            else:
                fpath = os.path.join(COBOL_ROOT, path)
                if not os.path.exists(fpath):
                    fpath = os.path.join(OUTPUT_DIR, path)
            if not os.path.exists(fpath):
                return f"[File not found: {path}]"
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            total = len(lines)
            content = "".join(lines[:max_lines])
            if total > max_lines:
                content += f"\n... [{max_lines} of {total} lines shown]"
            return f"[{path} — {total} lines]\n{content}"

        elif name == "write_file":
            if not agent.get("can_write_files"):
                return "[ERROR: Only the Developer agent can write files. Describe what you want the Developer to implement.]"
            path = args.get("path", "")
            if path.startswith("output/"):
                path = path[7:]
            content = args.get("content", "")
            fpath = os.path.join(OUTPUT_DIR, path)
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(content)
            return f"[Written: output/{path} — {content.count(chr(10))+1} lines]"

        elif name == "list_files":
            d = args.get("directory", "")
            if d.startswith("cobol"):
                dpath = os.path.join(COBOL_ROOT, d[6:].lstrip("/") if len(d) > 5 else "")
            elif d.startswith("output"):
                dpath = os.path.join(OUTPUT_DIR, d[7:].lstrip("/") if len(d) > 6 else "")
            else:
                dpath = os.path.join(COBOL_ROOT, d)
            if not os.path.exists(dpath):
                return f"[Dir not found: {d}]"
            entries = []
            for item in sorted(os.listdir(dpath)):
                full = os.path.join(dpath, item)
                if os.path.isdir(full):
                    entries.append(f"  {item}/")
                else:
                    entries.append(f"  {item} ({os.path.getsize(full):,}B)")
            return f"[{d}/ — {len(entries)} items]\n" + "\n".join(entries)

        elif name == "run_python":
            if not agent.get("can_write_files"):
                return "[ERROR: Only the Developer agent can run Python.]"
            code = args.get("code", "")
            r = subprocess.run(["python3", "-c", code], capture_output=True, text=True, timeout=30, cwd=OUTPUT_DIR)
            out = ""
            if r.stdout: out += r.stdout[:2000]
            if r.stderr: out += "\n[STDERR]\n" + r.stderr[:2000]
            if r.returncode != 0: out += f"\n[Exit: {r.returncode}]"
            return out or "[No output]"

        elif name == "recall":
            query = args.get("query", "")
            cmd = ["agentazall", "recall"]
            if query:
                cmd.append(query)
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, env=_agent_env(agent))
            out = r.stdout.strip()
            if not out or "No memories" in out:
                return "[No memories found. Store decisions with the remember tool.]"
            if len(out) > 8000:
                lines = out.split("\n")
                out = "[... last 200 lines ...]\n" + "\n".join(lines[-200:])
            return out

        elif name == "remember":
            text = args.get("text", "")
            title = args.get("title", "untitled")
            subprocess.run(
                ["agentazall", "remember", "--text", text, "--title", title],
                capture_output=True, text=True, timeout=10, env=_agent_env(agent)
            )
            return f"[Stored: {title}]"

        return f"[Unknown tool: {name}]"
    except Exception as e:
        return f"[Error: {e}]"


# ── LLM API ─────────────────────────────────────────────────────────

def call_llm(agent, messages, tools=None, temperature=0.7):
    payload = {
        "model": agent["model_id"],
        "messages": messages,
        "max_tokens": agent["max_tokens"],
        "temperature": temperature,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        agent["endpoint"], data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode()[:300]}", "elapsed": time.time()-t0}
    except Exception as e:
        return {"error": str(e), "elapsed": time.time()-t0}

    elapsed = time.time() - t0
    choice = result.get("choices", [{}])[0]
    msg = choice.get("message", {})
    usage = result.get("usage", {})
    return {
        "content": strip_think(msg.get("content", "") or ""),
        "tool_calls": msg.get("tool_calls"),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "tokens_per_sec": round(usage.get("completion_tokens", 0) / elapsed, 1) if elapsed > 0 else 0,
        "elapsed": round(elapsed, 1),
    }

def check_health(agent):
    try:
        url = agent["endpoint"].replace("/v1/chat/completions", "/health")
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.loads(r.read()).get("status") == "ok"
    except Exception:
        return False


# ── Process Tool Calls ───────────────────────────────────────────────

def process_tools(agent, messages, tool_calls, metrics):
    all_results = []
    total_p = total_c = 0
    total_t = 0.0
    seen_calls = set()  # Degenerate loop detection

    for loop_i in range(5):  # max 5 tool rounds
        if not tool_calls:
            break

        parts = []
        new_calls = 0
        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "?")
            try:
                args = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}

            # Degenerate loop detection: skip repeated identical calls
            call_key = f"{name}:{json.dumps(args, sort_keys=True)}"
            if call_key in seen_calls:
                print(f"    → {name}({json.dumps(args)[:70]}) = SKIPPED (duplicate)")
                continue
            seen_calls.add(call_key)
            new_calls += 1

            result = execute_tool(name, args, agent)
            all_results.append({"tool": name, "args_preview": json.dumps(args)[:100], "len": len(result)})
            print(f"    → {name}({json.dumps(args)[:70]}) = {len(result)}ch")

            if name == "remember":
                metrics["memories_stored"] += 1
            if name == "write_file" and not result.startswith("[ERROR"):
                metrics["files_written_total"] += 1

            if len(result) > 12000:
                result = result[:12000] + "\n... [truncated]"
            parts.append(f"=== {name} ===\n{result}")

        # If ALL calls were duplicates, force the agent to produce content
        if new_calls == 0:
            messages.append({"role": "assistant", "content": "I've already retrieved this information."})
            messages.append({
                "role": "user",
                "content": "You already have all the information from your tools. Now ANALYZE the data and produce your output. "
                "Do NOT call the same tools again. State your conclusions, decisions, and next steps."
            })
            agent_tools = get_tools_for_agent(agent)
            resp = call_llm(agent, messages, tools=agent_tools)
            total_p += resp.get("prompt_tokens", 0)
            total_c += resp.get("completion_tokens", 0)
            total_t += resp.get("elapsed", 0)
            content = resp.get("content", "")
            return content or "[no response after dedup]", total_p, total_c, total_t, all_results

        messages.append({"role": "assistant", "content": f"Calling {len(tool_calls)} tool(s)."})
        messages.append({
            "role": "user",
            "content": "Tool results:\n\n" + "\n\n".join(parts) +
                       "\n\nContinue. Store decisions with remember. Write code with write_file (Developer only). "
                       "Do NOT re-call tools you already used — use the results you have."
        })

        agent_tools = get_tools_for_agent(agent)
        resp = call_llm(agent, messages, tools=agent_tools)
        total_p += resp.get("prompt_tokens", 0)
        total_c += resp.get("completion_tokens", 0)
        total_t += resp.get("elapsed", 0)

        if "error" in resp:
            return "[tool error]", total_p, total_c, total_t, all_results

        content = resp.get("content", "")
        tool_calls = resp.get("tool_calls")

        if not tool_calls and content and len(content.strip()) > 10:
            return content, total_p, total_c, total_t, all_results

    return content or "[no response]", total_p, total_c, total_t, all_results


# ── Message Building (LEAN — last round only) ────────────────────────

def get_phase(topic, rnd):
    for p in topic.get("phases", []):
        if p["rounds"][0] <= rnd <= p["rounds"][1]:
            return p
    return None

def get_probe(topic, rnd):
    for p in topic.get("coherence_probes", []):
        if p["after_round"] == rnd:
            return p["question"]
    return None

def build_system_prompt(topic, agent, rnd):
    """LEAN system prompt. No memories — agents use recall tool."""
    phase = get_phase(topic, rnd)
    role = topic.get("agent_roles", {}).get(agent["role_key"], f"You are {agent['name']}.")

    phase_sec = ""
    if phase:
        phase_sec = f"\n=== PHASE: {phase['name']} (Rounds {phase['rounds'][0]}-{phase['rounds'][1]}) ===\nFocus: {phase['focus']}\n"
        if phase.get("cobol_files"):
            phase_sec += "COBOL files to examine (use read_file):\n" + "".join(f"  - {f}\n" for f in phase["cobol_files"])
        if phase.get("copybooks"):
            phase_sec += "Copybooks:\n" + "".join(f"  - {f}\n" for f in phase["copybooks"])
    else:
        phase_sec = "\n=== OPEN DISCUSSION ===\nContinue.\n"

    can_write = agent.get("can_write_files", False)
    if can_write:
        write_doc = (
            "- write_file(path, content): Write Python to output/ — YOU ARE THE ONLY AGENT WHO CAN DO THIS\n"
            "- run_python(code): Validate Python code\n"
        )
        write_rule = "You are the ONLY agent who writes code. The Architect tells you WHAT to build. The Reviewer tells you what to FIX. You implement."
    else:
        write_doc = ""
        write_rule = "You CANNOT write files. Describe what you want the Developer to implement. Be specific: file paths, class names, method signatures."

    return (
        f"{topic.get('system_context', '')}\n\n"
        f"ROLE: {role}\n\n"
        f"Round: {rnd}\n{phase_sec}\n"
        f"=== TOOLS ===\n"
        f"- read_file(path): Read COBOL ('cbl/COSGN00C.cbl') or output Python ('output/models/customer.py')\n"
        f"- list_files(dir): List files in 'cobol/cbl', 'cobol/cpy', 'output'\n"
        f"{write_doc}"
        f"- recall(query): Search persistent memories — call ONCE at start with '' to get index\n"
        f"- remember(text, title): Store decisions permanently with a short slug title like 'db-choice'\n\n"
        f"=== RULES ===\n"
        f"1. Call recall('') ONCE at the start (not repeatedly). Then read COBOL files relevant to this phase.\n"
        f"2. {write_rule}\n"
        f"3. Store EVERY architectural decision with remember(). Include specific details: field names, types, mappings.\n"
        f"4. NEVER contradict a prior decision without explaining why.\n"
        f"5. Reference specific COBOL program names and copybook fields. Read the source before deciding.\n"
        f"6. After reading source files, produce DETAILED analysis. Don't just say 'I read it'. Extract field mappings, program flow, data types.\n"
        f"7. Do NOT call the same tool with the same arguments twice in one turn.\n"
    )


def build_last_round(history, rnd):
    """ONLY messages from previous round. Nothing else."""
    prev = rnd - 1
    msgs = [m for m in history if m.get("round") == prev or (rnd == 1 and m.get("round") == 0)]
    return msgs


def format_for_api(msgs, agent_name, probe=None):
    chat = []
    for m in msgs:
        a = m.get("agent", "")
        c = m.get("content", "")
        if a == agent_name:
            chat.append({"role": "assistant", "content": c})
        else:
            label = f"[{a}]: " if a and a not in ("system", "probe") else ""
            chat.append({"role": "user", "content": label + c})

    # Merge consecutive same-role
    merged = []
    for msg in chat:
        if merged and merged[-1]["role"] == msg["role"]:
            merged[-1]["content"] += "\n\n" + msg["content"]
        else:
            merged.append(dict(msg))

    if probe:
        merged.append({"role": "user", "content": f"[COHERENCE CHECK] {probe}"})

    if merged and merged[-1]["role"] == "assistant":
        merged.append({"role": "user", "content": "Continue. recall('') first, then work."})
    if merged and merged[0]["role"] == "assistant":
        merged.insert(0, {"role": "user", "content": "Continue."})
    if not merged:
        merged.append({"role": "user", "content": "Begin. Call recall('') then list_files('cobol/cbl')."})

    return merged


# ── AgentAZAll Init ──────────────────────────────────────────────────

def init_agent(agent):
    os.makedirs(agent["agentazall_root"], exist_ok=True)
    env = _agent_env(agent)
    try:
        r = subprocess.run(["agentazall", "whoami"], capture_output=True, text=True, timeout=10, env=env)
        if r.returncode != 0 or "not registered" in r.stdout.lower():
            subprocess.run(
                ["agentazall", "whoami", "--set", f"I am {agent['name']}, CardDemo migration."],
                capture_output=True, text=True, timeout=10, env=env
            )
            print(f"  Init: {agent['name']}")
        else:
            print(f"  Ready: {agent['name']}")
    except FileNotFoundError:
        print(f"  WARN: agentazall not found")


# ── Main ─────────────────────────────────────────────────────────────

def run(topic_name, resume_file=None):
    topic = load_topic(topic_name)
    os.makedirs(RESULTS_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)

    max_phase = max((p["rounds"][1] for p in topic.get("phases", [])), default=100)

    if resume_file and os.path.exists(resume_file):
        with open(resume_file, "r") as f:
            state = json.load(f)
        history, metrics = state["history"], state["metrics"]
        start, rpath = state["last_round"] + 1, resume_file
    else:
        history = []
        metrics = {
            "topic": topic["title"], "version": "v3-memory-first",
            "started": datetime.now().isoformat(),
            "agents": [{"name": a["name"], "model": a["model_label"],
                        "comp": 0, "prompt": 0, "time": 0,
                        "tools": 0, "files": 0} for a in AGENTS],
            "total_comp": 0, "total_prompt": 0, "total_time": 0,
            "rounds": 0, "memories_stored": 0, "tool_calls_total": 0,
            "files_written_total": 0, "probes": 0, "errors": 0,
        }
        start = 1
        rpath = os.path.join(RESULTS_DIR, f"{topic_name}_v3_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

    print(f"\n{'='*70}")
    print(f"  Orchestrator v3 — Memory-First / Developer-Only-Writes")
    print(f"  Topic: {topic['title']}")
    print(f"  Context: LAST ROUND ONLY. Memory via recall() tool.")
    print(f"  File writes: DEVELOPER ONLY. Others negotiate.")
    print(f"  Stop: touch {STOP_FILE}")
    print(f"{'='*70}\n")

    for a in AGENTS:
        ok = check_health(a)
        w = " [WRITES CODE]" if a.get("can_write_files") else ""
        print(f"  {'OK' if ok else '!!':4s} {a['name']}{w} ({a['model_label']})")
        if not ok: sys.exit(1)

    print()
    for a in AGENTS:
        init_agent(a)

    if not history:
        history.append({
            "role": "user", "content": topic.get("initial_prompt", "Begin."),
            "round": 0, "agent": "system", "timestamp": datetime.now().isoformat(),
        })

    print(f"\n  Running. Output → {OUTPUT_DIR}\n")

    rnd = start
    errs = 0

    while True:
        stop = should_stop()
        if stop:
            print(f"\n  >> STOP ({stop})")
            break
        if errs >= 15:
            print(f"\n  >> {errs} errors. Stopping.")
            break

        phase = get_phase(topic, rnd)
        pname = phase["name"] if phase else "Open"

        print(f"\n{'─'*60}")
        print(f"  Round {rnd} [{pname}]")
        print(f"{'─'*60}")

        probe = get_probe(topic, rnd)
        if probe:
            print(f"  ★ PROBE: {probe[:80]}...")
            history.append({
                "role": "user", "content": f"[COHERENCE CHECK — Round {rnd}] {probe}",
                "round": rnd, "agent": "probe", "timestamp": datetime.now().isoformat(),
            })
            metrics["probes"] += 1

        last = build_last_round(history, rnd)
        rnd_err = False

        for i, agent in enumerate(AGENTS):
            sys_prompt = build_system_prompt(topic, agent, rnd)
            chat = format_for_api(last, agent["name"], probe)
            messages = [{"role": "system", "content": sys_prompt}] + chat
            agent_tools = get_tools_for_agent(agent)

            ctx_k = sum(estimate_tokens(m["content"]) for m in messages) // 1000
            sys.stdout.write(f"  [{agent['name']:10s}] ({ctx_k}K ctx) ")
            sys.stdout.flush()

            resp = call_llm(agent, messages, tools=agent_tools)

            if "error" in resp:
                print(f"ERROR: {resp['error'][:100]}")
                metrics["errors"] += 1
                rnd_err = True
                continue

            p_tok, c_tok, elapsed = resp["prompt_tokens"], resp["completion_tokens"], resp["elapsed"]
            content = resp.get("content", "")
            tc = resp.get("tool_calls")
            tr = []

            if tc:
                print(f"→ {len(tc)} tool(s):")
                text, ep, ec, et, tr = process_tools(agent, messages, tc, metrics)
                p_tok += ep; c_tok += ec; elapsed += et
                if text: content = text
                for t in tr:
                    metrics["tool_calls_total"] += 1
                    metrics["agents"][i]["tools"] += 1
                    if t["tool"] == "write_file":
                        metrics["agents"][i]["files"] += 1

            if not content or len(content.strip()) < 10:
                print("  (empty)")
                continue

            tps = round(c_tok / elapsed, 1) if elapsed > 0 else 0
            print(f"  {c_tok} tok, {tps} t/s, {elapsed:.0f}s, tools:{len(tr)}")

            history.append({
                "role": "assistant", "content": content,
                "round": rnd, "agent": agent["name"], "model": agent["model_label"],
                "timestamp": datetime.now().isoformat(),
                "m": {"p": p_tok, "c": c_tok, "tps": tps, "t": elapsed, "tc": len(tr)},
            })

            metrics["agents"][i]["comp"] += c_tok
            metrics["agents"][i]["prompt"] += p_tok
            metrics["agents"][i]["time"] += elapsed
            metrics["total_comp"] += c_tok
            metrics["total_prompt"] += p_tok
            metrics["total_time"] += elapsed

        errs = errs + 1 if rnd_err else 0
        metrics["rounds"] = rnd

        if rnd % 5 == 0:
            _save(rpath, topic, rnd, metrics, history)
            _stats(metrics, rnd)

        rnd += 1

    metrics["finished"] = datetime.now().isoformat()
    metrics["stop_reason"] = stop or "errors"
    _save(rpath, topic, rnd - 1, metrics, history)
    if os.path.exists(STOP_FILE): os.remove(STOP_FILE)
    _final(metrics, rpath)


def _save(p, topic, rnd, m, h):
    with open(p, "w") as f:
        json.dump({"topic": topic["title"], "last_round": rnd, "metrics": m, "history": h}, f, indent=2, ensure_ascii=False)

def _stats(m, rnd):
    n = sum(1 for _ in Path(OUTPUT_DIR).rglob("*.py")) if os.path.exists(OUTPUT_DIR) else 0
    h = m["total_time"]/3600 if m["total_time"]>0 else 0
    print(f"\n  ┌─ Round {rnd} ─────────────────────────────")
    print(f"  │ Comp:      {m['total_comp']:>10,}")
    print(f"  │ Prompt:    {m['total_prompt']:>10,}")
    print(f"  │ Memories:  {m['memories_stored']:>10,}")
    print(f"  │ Tools:     {m['tool_calls_total']:>10,}")
    print(f"  │ .py files: {n:>10,}")
    print(f"  │ Errors:    {m['errors']:>10,}")
    print(f"  │ Time:      {m['total_time']:>8.0f}s ({h:.2f}h)")
    print(f"  └──────────────────────────────────────────")

def _final(m, rp):
    n = sum(1 for _ in Path(OUTPUT_DIR).rglob("*.py")) if os.path.exists(OUTPUT_DIR) else 0
    h = m["total_time"]/3600 if m["total_time"]>0 else 0
    print(f"\n{'='*70}")
    print(f"  DONE — {m.get('stop_reason','?')}")
    print(f"  Rounds:{m['rounds']}  Comp:{m['total_comp']:,}  Mem:{m['memories_stored']}  Files:{n}  Err:{m['errors']}")
    print(f"  Time: {m['total_time']:.0f}s ({h:.2f}h)")
    for a in m["agents"]:
        avg = a["comp"]/a["time"] if a["time"]>0 else 0
        print(f"  {a['name']:12s}: {a['comp']:>8,}tok {avg:.0f}t/s tools:{a['tools']} files:{a['files']}")
    print(f"  Results: {rp}")
    print(f"{'='*70}\n")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--topic", required=True)
    p.add_argument("--resume", default=None)
    a = p.parse_args()
    run(a.topic, a.resume)

if __name__ == "__main__":
    main()
