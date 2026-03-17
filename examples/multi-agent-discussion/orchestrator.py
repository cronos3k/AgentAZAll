#!/usr/bin/env python3
"""
Multi-Agent Discussion Orchestrator
====================================
Coordinates 3 LLM agents (Architect, Developer, Reviewer) in a structured
multi-round discussion using local llama-server instances and AgentAZAll
for persistent memory and inter-agent messaging.

Usage:
    python3 orchestrator.py --topic rust-game-engine --rounds 5
    python3 orchestrator.py --topic cobol-migration --rounds 5
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
AGENTS_DIR = BASE_DIR / "agents"
RESULTS_DIR = BASE_DIR / "results"
TOPICS_DIR = BASE_DIR / "topics"
AGENTAZALL_BIN = os.path.expanduser("~/.local/bin/agentazall")

AGENTS = {
    "architect": {
        "name": "Architect",
        "model_url": "http://localhost:8190/v1/chat/completions",
        "model_name": "NVIDIA-Nemotron-3-Nano-30B-A3B-Q8_0",
        "root": str(AGENTS_DIR / "architect"),
        "role": (
            "You are the Architect. Your job is to design high-level system "
            "architecture, make strategic technical decisions, define module "
            "boundaries, and ensure the overall design is coherent, scalable, "
            "and maintainable. Be concrete and specific. Propose actual data "
            "structures, interfaces, and module layouts. When you disagree "
            "with another agent, explain why with technical reasoning."
        ),
    },
    "developer": {
        "name": "Developer",
        "model_url": "http://localhost:8180/v1/chat/completions",
        "model_name": "Qwen3-Coder-Next-Q8_0",
        "root": str(AGENTS_DIR / "developer"),
        "role": (
            "You are the Developer. Your job is to focus on implementation "
            "details, write concrete code snippets, identify APIs and libraries, "
            "solve technical problems, and translate architecture into working "
            "code. Be practical. Show real code when possible. Point out where "
            "the Architect's design needs more detail or where the Reviewer's "
            "concerns can be addressed with specific implementations."
        ),
    },
    "reviewer": {
        "name": "Reviewer",
        "model_url": "http://localhost:8192/v1/chat/completions",
        "model_name": "Qwen3.5-9B-Q4_K_M",
        "root": str(AGENTS_DIR / "reviewer"),
        "role": (
            "You are the Reviewer. Your job is to identify problems, risks, "
            "missing requirements, performance bottlenecks, and suggest "
            "improvements. Challenge assumptions constructively. Ask probing "
            "questions. Point out edge cases. Ensure the team does not "
            "over-engineer or under-engineer. Be specific about what could "
            "go wrong and propose mitigations."
        ),
    },
}

# Turn order per round
TURN_ORDER = ["architect", "developer", "reviewer"]


# ---------------------------------------------------------------------------
# LLM API
# ---------------------------------------------------------------------------

def call_llm(url: str, messages: list, max_tokens: int = 2048,
             temperature: float = 0.7) -> dict:
    """Call an OpenAI-compatible /v1/chat/completions endpoint."""
    payload = json.dumps({
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }).encode()

    req = Request(url, data=payload, headers={"Content-Type": "application/json"})
    t0 = time.monotonic()
    try:
        with urlopen(req, timeout=300) as resp:
            body = json.loads(resp.read())
    except URLError as exc:
        return {"error": str(exc), "elapsed": time.monotonic() - t0}

    elapsed = time.monotonic() - t0
    choice = body.get("choices", [{}])[0]
    message = choice.get("message", {})
    content = message.get("content", "")

    # Strip <think>...</think> blocks from thinking models
    if "<think>" in content:
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

    usage = body.get("usage", {})
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    tokens_per_sec = completion_tokens / elapsed if elapsed > 0 else 0

    return {
        "content": content,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "tokens_per_sec": round(tokens_per_sec, 2),
        "elapsed": round(elapsed, 3),
        "model": body.get("model", "unknown"),
    }


# ---------------------------------------------------------------------------
# AgentAZAll helpers
# ---------------------------------------------------------------------------

def agentazall(agent_key: str, *args: str) -> str:
    """Run an agentazall CLI command for a specific agent."""
    env = os.environ.copy()
    env["AGENTAZALL_ROOT"] = AGENTS[agent_key]["root"]
    env["PATH"] = os.path.expanduser("~/.local/bin") + ":" + env.get("PATH", "")
    try:
        result = subprocess.run(
            [AGENTAZALL_BIN] + list(args),
            env=env, capture_output=True, text=True, timeout=30,
        )
        return result.stdout.strip()
    except Exception as exc:
        return f"[agentazall error: {exc}]"


def agent_remember(agent_key: str, text: str, title: str) -> str:
    return agentazall(agent_key, "remember", "--text", text, "--title", title)


def agent_send(from_key: str, to_key: str, subject: str, body: str) -> str:
    """Send a message from one agent to another via local mailbox."""
    to_name = AGENTS[to_key]["name"]
    return agentazall(from_key, "send", "--to", f"{to_name}@local",
                      "-s", subject, "-b", body)


def agent_inbox(agent_key: str) -> str:
    return agentazall(agent_key, "inbox")


# ---------------------------------------------------------------------------
# Topic loader
# ---------------------------------------------------------------------------

def load_topic(topic_name: str) -> dict:
    topic_file = TOPICS_DIR / f"{topic_name}.json"
    if not topic_file.exists():
        print(f"ERROR: Topic file not found: {topic_file}")
        sys.exit(1)
    with open(topic_file) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Discussion engine
# ---------------------------------------------------------------------------

def run_discussion(topic_name: str, num_rounds: int) -> dict:
    topic = load_topic(topic_name)
    print(f"\n{'='*72}")
    print(f"  MULTI-AGENT DISCUSSION: {topic['title']}")
    print(f"  Rounds: {num_rounds}  |  Agents: {', '.join(a['name'] for a in AGENTS.values())}")
    print(f"{'='*72}\n")

    discussion_start = time.monotonic()
    transcript = []
    metrics = {
        "topic": topic_name,
        "title": topic["title"],
        "num_rounds": num_rounds,
        "agents": {},
        "rounds": [],
    }

    # Initialize per-agent metrics
    for key, cfg in AGENTS.items():
        metrics["agents"][key] = {
            "name": cfg["name"],
            "model": cfg["model_name"],
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_time": 0.0,
            "turns": 0,
        }

    # Build the conversation history as a shared context
    conversation_history = []

    for round_num in range(1, num_rounds + 1):
        round_start = time.monotonic()
        round_data = {"round": round_num, "turns": []}
        print(f"--- Round {round_num}/{num_rounds} ---")

        for agent_key in TURN_ORDER:
            cfg = AGENTS[agent_key]
            agent_name = cfg["name"]

            # Build messages for this agent
            system_prompt = (
                f"{topic['system_context']}\n\n"
                f"{cfg['role']}\n\n"
                f"Discussion topic: {topic['title']}\n"
                f"Current round: {round_num}/{num_rounds}\n\n"
                f"Guidelines:\n"
                f"- Keep responses focused and under 400 words.\n"
                f"- Build on what others have said.\n"
                f"- Be concrete: propose specific solutions, not vague ideas.\n"
                f"- If this is the final round, summarize key decisions and action items."
            )

            messages = [{"role": "system", "content": system_prompt}]

            # Add conversation history
            for entry in conversation_history:
                messages.append({
                    "role": "user" if entry["agent"] != agent_key else "assistant",
                    "content": f"[{entry['agent_name']}, Round {entry['round']}]: {entry['content']}"
                })

            # Add turn prompt
            if round_num == 1 and agent_key == TURN_ORDER[0]:
                messages.append({
                    "role": "user",
                    "content": (
                        f"Begin the discussion. What is your initial proposal "
                        f"for: {topic['title']}?"
                    ),
                })
            elif round_num == num_rounds:
                messages.append({
                    "role": "user",
                    "content": (
                        "This is the FINAL round. Summarize the key decisions made, "
                        "list concrete action items, and note any unresolved disagreements."
                    ),
                })
            else:
                messages.append({
                    "role": "user",
                    "content": "Continue the discussion. Respond to the points raised by others.",
                })

            # Call the LLM
            print(f"  [{agent_name}] generating...", end="", flush=True)
            result = call_llm(cfg["model_url"], messages)

            if "error" in result:
                print(f" ERROR: {result['error']}")
                content = f"[Error: {result['error']}]"
                result["content"] = content
                result["prompt_tokens"] = 0
                result["completion_tokens"] = 0
                result["total_tokens"] = 0
                result["tokens_per_sec"] = 0
            else:
                content = result["content"]
                print(
                    f" done ({result['completion_tokens']} tokens, "
                    f"{result['tokens_per_sec']} t/s, {result['elapsed']}s)"
                )

            # Add to shared conversation history
            conversation_history.append({
                "agent": agent_key,
                "agent_name": agent_name,
                "round": round_num,
                "content": content,
            })

            # Store as AgentAZAll memory
            memory_title = f"{topic_name}-r{round_num}-{agent_key}"
            summary = content[:200] + "..." if len(content) > 200 else content
            agent_remember(agent_key, summary, memory_title)

            # Record turn data
            turn_data = {
                "agent": agent_key,
                "agent_name": agent_name,
                "model": cfg["model_name"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "content": content,
                "prompt_tokens": result.get("prompt_tokens", 0),
                "completion_tokens": result.get("completion_tokens", 0),
                "total_tokens": result.get("total_tokens", 0),
                "tokens_per_sec": result.get("tokens_per_sec", 0),
                "elapsed_seconds": result.get("elapsed", 0),
            }
            round_data["turns"].append(turn_data)
            transcript.append(turn_data)

            # Update agent metrics
            am = metrics["agents"][agent_key]
            am["total_prompt_tokens"] += turn_data["prompt_tokens"]
            am["total_completion_tokens"] += turn_data["completion_tokens"]
            am["total_time"] += turn_data["elapsed_seconds"]
            am["turns"] += 1

        round_elapsed = time.monotonic() - round_start
        round_data["elapsed_seconds"] = round(round_elapsed, 3)
        metrics["rounds"].append(round_data)
        print(f"  Round {round_num} completed in {round_elapsed:.1f}s\n")

    # Compute summary metrics
    total_elapsed = time.monotonic() - discussion_start
    total_prompt = sum(m["total_prompt_tokens"] for m in metrics["agents"].values())
    total_completion = sum(m["total_completion_tokens"] for m in metrics["agents"].values())

    for key in metrics["agents"]:
        am = metrics["agents"][key]
        if am["total_time"] > 0:
            am["avg_tokens_per_sec"] = round(
                am["total_completion_tokens"] / am["total_time"], 2
            )

    metrics["summary"] = {
        "total_elapsed_seconds": round(total_elapsed, 3),
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "total_tokens": total_prompt + total_completion,
        "total_messages": len(transcript),
        "avg_completion_tokens_per_sec": round(
            total_completion / total_elapsed if total_elapsed > 0 else 0, 2
        ),
    }

    # Save results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_file = RESULTS_DIR / f"{topic_name}_{timestamp}.json"

    output = {
        "meta": {
            "topic": topic_name,
            "title": topic["title"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "num_rounds": num_rounds,
        },
        "metrics": metrics,
        "transcript": transcript,
    }

    with open(result_file, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*72}")
    print(f"  DISCUSSION COMPLETE")
    print(f"  Total time: {total_elapsed:.1f}s")
    print(f"  Total messages: {len(transcript)}")
    print(f"  Total tokens: {total_prompt + total_completion}")
    print(f"  Results saved to: {result_file}")
    print(f"{'='*72}")

    # Print per-agent summary
    print(f"\n  Per-Agent Summary:")
    for key, am in metrics["agents"].items():
        avg_tps = am.get("avg_tokens_per_sec", 0)
        print(
            f"    {am['name']:12s} | model: {am['model']:40s} | "
            f"turns: {am['turns']} | completion: {am['total_completion_tokens']:5d} tokens | "
            f"avg: {avg_tps:6.1f} t/s | time: {am['total_time']:6.1f}s"
        )

    return output


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Multi-Agent Discussion Orchestrator"
    )
    parser.add_argument(
        "--topic", required=True,
        help="Topic name (matches topics/<name>.json)"
    )
    parser.add_argument(
        "--rounds", type=int, default=5,
        help="Number of discussion rounds"
    )
    args = parser.parse_args()

    # Verify all models are healthy
    print("Checking model health...")
    for key, cfg in AGENTS.items():
        health_url = cfg["model_url"].replace("/v1/chat/completions", "/health")
        try:
            with urlopen(health_url, timeout=10) as resp:
                data = json.loads(resp.read())
                if data.get("status") == "ok":
                    print(f"  {cfg['name']:12s} ({cfg['model_name']}): OK")
                else:
                    print(f"  {cfg['name']:12s}: UNHEALTHY - {data}")
                    sys.exit(1)
        except Exception as exc:
            print(f"  {cfg['name']:12s}: UNREACHABLE - {exc}")
            sys.exit(1)

    print("All models healthy.\n")
    run_discussion(args.topic, args.rounds)


if __name__ == "__main__":
    main()
