"""AgentAZClaw — Orchestrator.

Memory-first multi-agent orchestrator. Only the last round goes
into context. Everything else is a tool call away. Period.
"""

import json
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .agent import Agent
from .llm import strip_think
from .tools import ToolRegistry, build_default_registry
from .topic import Topic


@dataclass
class RunStats:
    """Aggregate stats for the entire run."""
    rounds: int = 0
    total_comp: int = 0
    total_prompt: int = 0
    total_time: float = 0.0
    memories_stored: int = 0
    tool_calls: int = 0
    files_written: int = 0
    errors: int = 0
    started: str = ""
    finished: str = ""


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


class Orchestrator:
    """Memory-first multi-agent orchestrator.

    Usage:
        orch = Orchestrator(agents=[a, b, c])
        orch.set_task("Build a REST API")
        orch.run(max_rounds=30)
    """

    def __init__(
        self,
        agents: list[Agent],
        topic: Topic | str | None = None,
        output_dir: str = "./output",
        log_dir: str = "./logs",
        source_dirs: list[str] | None = None,
        registry: ToolRegistry | None = None,
        max_tool_result: int = 12000,
    ):
        self.agents = agents
        self.output_dir = os.path.abspath(output_dir)
        self.log_dir = os.path.abspath(log_dir)
        self.source_dirs = source_dirs or ["."]
        self.registry = registry or build_default_registry()
        self.max_tool_result = max_tool_result
        self.stats = RunStats()

        # Load topic
        if isinstance(topic, str):
            # Try as file path first, then as topics dir
            if os.path.exists(topic):
                self.topic = Topic.from_file(topic)
            elif os.path.exists(os.path.join("topics", f"{topic}.json")):
                self.topic = Topic.from_file(os.path.join("topics", f"{topic}.json"))
            else:
                self.topic = Topic.from_task(topic)
        elif isinstance(topic, Topic):
            self.topic = topic
        else:
            self.topic = Topic.from_task("Collaborate on the task at hand.")

        self._history: list[dict] = []
        self._shutdown = False
        self._stop_file = os.path.join(os.getcwd(), "STOP")
        self._checkpoint_path: str | None = None

    def set_task(self, task: str, max_rounds: int | None = None):
        """Set a simple task. max_rounds=None means run until STOP."""
        self.topic = Topic.from_task(task, max_rounds or 999999)

    def run(self, max_rounds: int | None = None, resume: str | None = None):
        """Run the orchestrator until completion or STOP."""
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.log_dir, exist_ok=True)
        if os.path.exists(self._stop_file):
            os.remove(self._stop_file)

        # Signal handlers
        prev_term = signal.getsignal(signal.SIGTERM)
        prev_int = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        # Set up log file (mirrors stdout to file)
        log_name = f"{self.topic.title[:40].replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        log_path = os.path.join(self.log_dir, log_name)
        self._log_file = open(log_path, "w", encoding="utf-8")

        # Resume from checkpoint if provided
        start_round = 1
        if resume and os.path.exists(resume):
            start_round = self._load_checkpoint(resume)
        else:
            self.stats.started = datetime.now().isoformat()

        # Checkpoint path
        self._checkpoint_path = os.path.join(
            self.log_dir,
            f"{self.topic.title[:40].replace(' ', '_')}_checkpoint.json",
        )

        if max_rounds is not None:
            limit = max_rounds
        elif self.topic.max_round < 999999:
            limit = self.topic.max_round + 50
        else:
            limit = 999999  # effectively indefinite

        # Health checks
        self._log(f"\n{'='*60}")
        self._log(f"  AgentAZClaw — Memory-First Orchestrator")
        self._log(f"  Topic: {self.topic.title}")
        self._log(f"  Agents: {len(self.agents)}")
        self._log(f"  Log: {log_path}")
        self._log(f"  Stop: touch {self._stop_file}")
        self._log(f"{'='*60}\n")

        for a in self.agents:
            ok = a.is_healthy()
            w = " [WRITES]" if a.can_write else ""
            self._log(f"  {'OK' if ok else '!!'} {a.name}{w} -> {a.endpoint}")
            if not ok:
                self._log(f"  ERROR: {a.name} endpoint not reachable. Aborting.")
                self._log_file.close()
                return

        # Initialize agent identities in AgentAZAll
        for a in self.agents:
            self._init_agent_identity(a)

        # Seed history with initial prompt
        if not self._history:
            self._history.append({
                "role": "user",
                "content": self.topic.initial_prompt,
                "round": 0, "agent": "system",
                "timestamp": datetime.now().isoformat(),
            })

        self._log(f"\n  Running. Output -> {self.output_dir}\n")
        consecutive_errors = 0

        for rnd in range(start_round, limit + 1):
            if self._should_stop():
                break
            if consecutive_errors >= 15:
                print(f"\n  >> {consecutive_errors} consecutive errors. Stopping.")
                break

            phase = self.topic.get_phase(rnd)
            pname = phase["name"] if phase else "Open"

            print(f"\n{'-'*60}")
            print(f"  Round {rnd} [{pname}]")
            print(f"{'-'*60}")

            # Coherence probe
            probe = self.topic.get_probe(rnd)
            if probe:
                print(f"  * PROBE: {probe[:80]}...")
                self._history.append({
                    "role": "user",
                    "content": f"[COHERENCE CHECK — Round {rnd}] {probe}",
                    "round": rnd, "agent": "probe",
                    "timestamp": datetime.now().isoformat(),
                })

            last_round = self._build_last_round(rnd)
            round_had_error = False

            for agent in self.agents:
                self.registry.reset_dedup(agent.name)

                sys_prompt = self._build_system_prompt(agent, rnd, phase)
                chat = self._format_for_api(last_round, agent.name, probe)
                messages = [{"role": "system", "content": sys_prompt}] + chat

                ctx_k = sum(_estimate_tokens(m["content"]) for m in messages) // 1000
                sys.stdout.write(f"  [{agent.name:10s}] ({ctx_k}K ctx) ")
                sys.stdout.flush()

                # Get tool schemas for this agent
                tool_schemas = self.registry.get_schemas(
                    allowed=agent.tools, capabilities=agent.capabilities
                )

                # LLM call
                resp = agent.chat(messages, tools=tool_schemas)

                if "error" in resp:
                    print(f"ERROR: {resp['error'][:100]}")
                    self.stats.errors += 1
                    round_had_error = True
                    continue

                content = resp.get("content", "")
                tool_calls = resp.get("tool_calls")
                p_tok = resp.get("prompt_tokens", 0)
                c_tok = resp.get("completion_tokens", 0)
                elapsed = resp.get("elapsed", 0)
                tool_results = []

                # Process tool calls
                if tool_calls:
                    print(f"-> {len(tool_calls)} tool(s):")
                    content, extra_p, extra_c, extra_t, tool_results = self._process_tools(
                        agent, messages, tool_calls
                    )
                    p_tok += extra_p
                    c_tok += extra_c
                    elapsed += extra_t

                if not content or len(content.strip()) < 10:
                    print("  (empty)")
                    continue

                tps = round(c_tok / elapsed, 1) if elapsed > 0 else 0
                print(f"  {c_tok} tok, {tps} t/s, {elapsed:.0f}s, tools:{len(tool_results)}")

                # Record in history
                self._history.append({
                    "role": "assistant", "content": content,
                    "round": rnd, "agent": agent.name,
                    "timestamp": datetime.now().isoformat(),
                    "m": {"p": p_tok, "c": c_tok, "tps": tps, "t": elapsed,
                          "tc": len(tool_results)},
                })

                # Update stats
                self.stats.total_comp += c_tok
                self.stats.total_prompt += p_tok
                self.stats.total_time += elapsed
                self.stats.tool_calls += len(tool_results)
                agent.stats.tool_calls += len(tool_results)
                agent.stats.rounds += 1

            consecutive_errors = consecutive_errors + 1 if round_had_error else 0
            self.stats.rounds = rnd

            # Prune history to prevent unbounded memory growth
            # Keep last 10 rounds — everything else is in AgentAZAll memories
            if len(self._history) > 200:
                cutoff_round = rnd - 10
                self._history = [
                    m for m in self._history
                    if m.get("round", 0) >= cutoff_round or m.get("round", 0) == 0
                ]

            if rnd % 5 == 0:
                self._print_stats(rnd)
                self._save_checkpoint(rnd)

        # Finalize
        self.stats.finished = datetime.now().isoformat()
        self._print_final()
        self._save_checkpoint(self.stats.rounds)

        # Close log file
        if hasattr(self, '_log_file') and self._log_file:
            self._log_file.close()

        # Restore signal handlers
        signal.signal(signal.SIGTERM, prev_term)
        signal.signal(signal.SIGINT, prev_int)

    def _log(self, msg: str):
        """Print to stdout AND write to log file."""
        print(msg)
        if hasattr(self, '_log_file') and self._log_file:
            self._log_file.write(msg + "\n")
            self._log_file.flush()

    def _init_agent_identity(self, agent: Agent):
        """Set agent identity in AgentAZAll (whoami)."""
        try:
            env = os.environ.copy()
            env["AGENTAZALL_ROOT"] = agent.root
            path_dirs = os.path.expanduser("~/.local/bin")
            env["PATH"] = path_dirs + os.pathsep + env.get("PATH", "")

            subprocess.run(
                ["agentazall", "whoami", "--set",
                 f"I am {agent.name}. {agent.role[:100]}"],
                capture_output=True, text=True, timeout=10, env=env,
            )
            self._log(f"  Init: {agent.name}")
        except FileNotFoundError:
            # agentazall CLI not available — use direct file write
            whoami_dir = os.path.join(agent.root, "data", "who_am_i")
            os.makedirs(whoami_dir, exist_ok=True)
            with open(os.path.join(whoami_dir, "identity.txt"), "w") as f:
                f.write(f"I am {agent.name}. {agent.role}")
            self._log(f"  Init (direct): {agent.name}")
        except Exception as e:
            self._log(f"  Init warn: {agent.name}: {e}")

    def _save_checkpoint(self, rnd: int):
        """Save state to JSON for resume capability."""
        if not self._checkpoint_path:
            return
        state = {
            "topic_title": self.topic.title,
            "last_round": rnd,
            "stats": {
                "rounds": self.stats.rounds,
                "total_comp": self.stats.total_comp,
                "total_prompt": self.stats.total_prompt,
                "total_time": self.stats.total_time,
                "memories_stored": self.stats.memories_stored,
                "tool_calls": self.stats.tool_calls,
                "files_written": self.stats.files_written,
                "errors": self.stats.errors,
                "started": self.stats.started,
            },
            "agents": [
                {
                    "name": a.name,
                    "comp": a.stats.completion_tokens,
                    "prompt": a.stats.prompt_tokens,
                    "time": a.stats.elapsed,
                    "tools": a.stats.tool_calls,
                    "files": a.stats.files_written,
                }
                for a in self.agents
            ],
            "history": self._history[-100:],  # last 100 messages
        }
        try:
            with open(self._checkpoint_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception:
            pass  # don't crash on checkpoint save failure

    def _load_checkpoint(self, path: str) -> int:
        """Load state from checkpoint. Returns starting round."""
        with open(path, "r") as f:
            state = json.load(f)
        self._history = state.get("history", [])
        s = state.get("stats", {})
        self.stats.rounds = s.get("rounds", 0)
        self.stats.total_comp = s.get("total_comp", 0)
        self.stats.total_prompt = s.get("total_prompt", 0)
        self.stats.total_time = s.get("total_time", 0)
        self.stats.memories_stored = s.get("memories_stored", 0)
        self.stats.tool_calls = s.get("tool_calls", 0)
        self.stats.files_written = s.get("files_written", 0)
        self.stats.errors = s.get("errors", 0)
        self.stats.started = s.get("started", datetime.now().isoformat())
        # Restore per-agent stats
        for agent_state in state.get("agents", []):
            for a in self.agents:
                if a.name == agent_state["name"]:
                    a.stats.completion_tokens = agent_state.get("comp", 0)
                    a.stats.prompt_tokens = agent_state.get("prompt", 0)
                    a.stats.elapsed = agent_state.get("time", 0)
                    a.stats.tool_calls = agent_state.get("tools", 0)
                    a.stats.files_written = agent_state.get("files", 0)
        return state.get("last_round", 0) + 1

    def _handle_signal(self, signum, frame):
        self._shutdown = True
        self._log("\n  >> Signal received. Finishing round...")

    def _should_stop(self) -> bool:
        return self._shutdown or os.path.exists(self._stop_file)

    def _build_last_round(self, rnd: int) -> list[dict]:
        """ONLY messages from previous round."""
        prev = rnd - 1
        return [m for m in self._history
                if m.get("round") == prev or (rnd == 1 and m.get("round") == 0)]

    def _build_system_prompt(self, agent: Agent, rnd: int,
                             phase: dict | None) -> str:
        """Lean system prompt. No memories — agents use recall tool."""
        role = self.topic.get_role(agent.name.lower())

        phase_sec = ""
        if phase:
            phase_sec = (
                f"\n=== PHASE: {phase['name']} "
                f"(Rounds {phase['rounds'][0]}-{phase['rounds'][1]}) ===\n"
                f"Focus: {phase.get('focus', '')}\n"
            )
            for key in ("cobol_files", "source_files", "files"):
                if phase.get(key):
                    phase_sec += "Files to examine:\n"
                    phase_sec += "".join(f"  - {f}\n" for f in phase[key])
                    break
            if phase.get("copybooks"):
                phase_sec += "Copybooks/headers:\n"
                phase_sec += "".join(f"  - {f}\n" for f in phase["copybooks"])
        else:
            phase_sec = "\n=== OPEN DISCUSSION ===\nContinue.\n"

        if agent.can_write:
            write_doc = (
                "- write_file(path, content): Write files to output/ — "
                "YOU ARE THE ONLY AGENT WHO CAN DO THIS\n"
                "- run_python(code): Validate code\n"
            )
            write_rule = (
                "You are the ONLY agent who writes code. Others tell you "
                "WHAT to build. You implement."
            )
        else:
            write_doc = ""
            write_rule = (
                "You CANNOT write files. Describe what you want implemented. "
                "Be specific: file paths, class names, method signatures."
            )

        return (
            f"{self.topic.system_context}\n\n"
            f"ROLE: {role}\n\n"
            f"Round: {rnd}\n{phase_sec}\n"
            f"=== TOOLS ===\n"
            f"- read_file(path): Read source or output files\n"
            f"- list_files(dir): List files in directories\n"
            f"{write_doc}"
            f"- recall(query): Search persistent memories — "
            f"call ONCE at start with '' to get index\n"
            f"- remember(text, title): Store decisions permanently\n\n"
            f"=== RULES ===\n"
            f"1. Call recall('') ONCE at start. Do NOT call it repeatedly.\n"
            f"2. {write_rule}\n"
            f"3. Store EVERY architectural decision with remember().\n"
            f"4. NEVER contradict a prior decision without explaining why.\n"
            f"5. Do NOT call the same tool with same arguments twice.\n"
        )

    def _format_for_api(self, msgs: list, agent_name: str,
                        probe: str | None = None) -> list[dict]:
        """Convert history messages to API format."""
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

        # Ensure valid alternation
        if merged and merged[-1]["role"] == "assistant":
            merged.append({"role": "user", "content": "Continue. recall('') first."})
        if merged and merged[0]["role"] == "assistant":
            merged.insert(0, {"role": "user", "content": "Continue."})
        if not merged:
            merged.append({"role": "user", "content": "Begin. Call recall('') first."})

        return merged

    def _process_tools(self, agent: Agent, messages: list,
                       tool_calls: list) -> tuple:
        """Process tool calls with dedup and multi-round support."""
        all_results = []
        total_p = total_c = 0
        total_t = 0.0
        content = ""

        # Build context for tool execution
        ctx = {
            "agent_root": agent.root,
            "output_dir": self.output_dir,
            "source_dirs": self.source_dirs,
            "max_tool_result": self.max_tool_result,
        }

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

                result = self.registry.execute(
                    name, args,
                    capabilities=agent.capabilities,
                    context=ctx,
                    agent_name=agent.name,
                )

                if result is None:  # skipped (duplicate)
                    print(f"    -> {name}({json.dumps(args)[:70]}) = SKIPPED (dup)")
                    continue

                new_calls += 1
                all_results.append({"tool": name, "len": len(result)})
                print(f"    -> {name}({json.dumps(args)[:70]}) = {len(result)}ch")

                if name == "remember":
                    self.stats.memories_stored += 1
                if name == "write_file" and not result.startswith("[ERROR"):
                    self.stats.files_written += 1
                    agent.stats.files_written += 1

                if len(result) > self.max_tool_result:
                    result = result[:self.max_tool_result] + "\n... [truncated]"
                parts.append(f"=== {name} ===\n{result}")

            # All calls were duplicates — force content generation
            if new_calls == 0:
                messages.append({"role": "assistant",
                                 "content": "I've already retrieved this info."})
                messages.append({"role": "user",
                                 "content": "Analyze the data you have. "
                                 "Do NOT call the same tools again."})
                tool_schemas = self.registry.get_schemas(
                    allowed=agent.tools, capabilities=agent.capabilities
                )
                resp = agent.chat(messages, tools=tool_schemas)
                total_p += resp.get("prompt_tokens", 0)
                total_c += resp.get("completion_tokens", 0)
                total_t += resp.get("elapsed", 0)
                content = resp.get("content", "")
                return (content or "[no response after dedup]",
                        total_p, total_c, total_t, all_results)

            messages.append({"role": "assistant",
                             "content": f"Calling {len(tool_calls)} tool(s)."})
            messages.append({"role": "user",
                             "content": "Tool results:\n\n" + "\n\n".join(parts) +
                             "\n\nContinue. Store decisions with remember. "
                             "Do NOT re-call tools you already used."})

            tool_schemas = self.registry.get_schemas(
                allowed=agent.tools, capabilities=agent.capabilities
            )
            resp = agent.chat(messages, tools=tool_schemas)
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

    def _print_stats(self, rnd: int):
        n = sum(1 for _ in Path(self.output_dir).rglob("*.py")) if os.path.exists(self.output_dir) else 0
        h = self.stats.total_time / 3600 if self.stats.total_time > 0 else 0
        print(f"\n  +-- Round {rnd} ----------------------------")
        print(f"  | Comp:      {self.stats.total_comp:>10,}")
        print(f"  | Prompt:    {self.stats.total_prompt:>10,}")
        print(f"  | Memories:  {self.stats.memories_stored:>10,}")
        print(f"  | Tools:     {self.stats.tool_calls:>10,}")
        print(f"  | .py files: {n:>10,}")
        print(f"  | Errors:    {self.stats.errors:>10,}")
        print(f"  | Time:      {self.stats.total_time:>8.0f}s ({h:.2f}h)")
        print(f"  +------------------------------------------")

    def _print_final(self):
        n = sum(1 for _ in Path(self.output_dir).rglob("*.py")) if os.path.exists(self.output_dir) else 0
        h = self.stats.total_time / 3600 if self.stats.total_time > 0 else 0
        print(f"\n{'='*60}")
        print(f"  DONE")
        print(f"  Rounds:{self.stats.rounds}  Comp:{self.stats.total_comp:,}  "
              f"Mem:{self.stats.memories_stored}  Files:{n}  Err:{self.stats.errors}")
        print(f"  Time: {self.stats.total_time:.0f}s ({h:.2f}h)")
        for a in self.agents:
            print(f"  {a.name:12s}: {a.stats.completion_tokens:>8,}tok "
                  f"{a.stats.avg_speed:.0f}t/s tools:{a.stats.tool_calls} "
                  f"files:{a.stats.files_written}")
        print(f"{'='*60}\n")
