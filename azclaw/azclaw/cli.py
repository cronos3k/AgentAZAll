"""AgentAZClaw — CLI entry point.

Usage:
    azclaw run --topic carddemo-migration
    azclaw run --task "Build a FastAPI todo app"
    azclaw stop
    azclaw status
"""

import argparse
import os
import sys


def cmd_run(args):
    from .agent import Agent
    from .orchestrator import Orchestrator
    from .topic import Topic

    if args.topic:
        # Load topic file
        topic_path = args.topic
        if not topic_path.endswith(".json"):
            topic_path = os.path.join("topics", f"{topic_path}.json")
        if not os.path.exists(topic_path):
            print(f"Topic not found: {topic_path}")
            sys.exit(1)
        topic = Topic.from_file(topic_path)
    elif args.task:
        topic = Topic.from_task(args.task, max_rounds=args.max_rounds or 50)
    else:
        print("Provide --topic or --task")
        sys.exit(1)

    # Parse agent configs from --agents or use defaults
    if args.agents:
        agents = _parse_agents(args.agents)
    else:
        endpoint = args.endpoint or "http://localhost:8080/v1/chat/completions"
        agents = [
            Agent("architect", role="Design the solution.", endpoint=endpoint),
            Agent("developer", role="Write the code.", endpoint=endpoint,
                  can_write=True),
            Agent("reviewer", role="Review the code.", endpoint=endpoint),
        ]

    source_dirs = args.source.split(",") if args.source else ["."]

    orch = Orchestrator(
        agents=agents,
        topic=topic,
        output_dir=args.output or "./output",
        source_dirs=source_dirs,
    )
    orch.run(max_rounds=args.max_rounds, resume=getattr(args, 'resume', None))


def cmd_stop(args):
    stop_file = os.path.join(os.getcwd(), "STOP")
    with open(stop_file, "w") as f:
        f.write("stop")
    print(f"STOP file created: {stop_file}")


def _parse_agents(spec: str):
    """Parse agent spec: 'name:endpoint,name:endpoint,...'"""
    from .agent import Agent
    agents = []
    for part in spec.split(","):
        parts = part.strip().split(":")
        name = parts[0]
        endpoint = ":".join(parts[1:]) if len(parts) > 1 else "http://localhost:8080/v1/chat/completions"
        can_write = name.lower() in ("developer", "dev", "coder")
        agents.append(Agent(name, endpoint=endpoint, can_write=can_write))
    return agents


def main():
    p = argparse.ArgumentParser(
        prog="azclaw",
        description="AgentAZClaw — Memory-first multi-agent orchestrator",
    )
    sub = p.add_subparsers(dest="command")

    # run
    run_p = sub.add_parser("run", help="Run the orchestrator")
    run_p.add_argument("--topic", help="Topic JSON file or name in topics/")
    run_p.add_argument("--task", help="Simple task description")
    run_p.add_argument("--endpoint", help="Default LLM endpoint")
    run_p.add_argument("--agents", help="Agent spec: name:endpoint,name:endpoint")
    run_p.add_argument("--output", help="Output directory", default="./output")
    run_p.add_argument("--source", help="Source directories (comma-separated)")
    run_p.add_argument("--max-rounds", type=int, help="Maximum rounds")
    run_p.add_argument("--resume", help="Resume from checkpoint JSON file")

    # stop
    sub.add_parser("stop", help="Create STOP file for graceful shutdown")

    args = p.parse_args()
    if args.command == "run":
        cmd_run(args)
    elif args.command == "stop":
        cmd_stop(args)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
