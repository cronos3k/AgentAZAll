# Changelog

## v0.1.0 (2026-03-22) — Initial Release

### Core Framework
- **Agent class** — wraps any OpenAI-compatible endpoint with role, tool permissions, and per-agent AgentAZAll memory root
- **Orchestrator** — memory-first round loop: only last round in context, everything else via `recall()`/`remember()` tools
- **ToolRegistry** — decorator-based tool registration with OpenAI function-calling schema auto-generation
- **6 built-in tools**: recall, remember, read_file, write_file, list_files, run_python
- **Topic/phase system** — JSON-based task configuration with phases, round ranges, and coherence probes

### Key Features
- **Per-agent dedup detection** — prevents agents from calling the same tool with same arguments repeatedly; forces content generation when all calls are duplicates
- **Role-based tool access** — only agents with `can_write=True` can use write_file and run_python
- **Checkpointing** — auto-saves state every 5 rounds; full resume from checkpoint with `--resume`
- **Log file mirroring** — all output written to both stdout and timestamped log file
- **History pruning** — keeps last 10 rounds in memory, prunes older entries to prevent unbounded growth
- **Graceful stop** — STOP file, SIGINT, SIGTERM all trigger clean shutdown after current round
- **Health checks** — verifies all LLM endpoints before starting (supports llama.cpp `/health` and LM Studio/vLLM `/v1/models`)
- **Agent identity init** — auto-sets AgentAZAll `whoami` for each agent at startup

### CLI
- `azclaw run --topic <file>` — run with phase-based topic configuration
- `azclaw run --task "description"` — run with simple task (auto-generates single-phase topic)
- `azclaw run --resume <checkpoint.json>` — resume interrupted run
- `azclaw stop` — create STOP file for graceful shutdown

### LLM Client
- urllib-only (zero external dependencies) — works with llama.cpp, vLLM, Ollama, LM Studio, OpenRouter
- `<think>` block stripping for reasoning models (Qwen, DeepSeek)

### Validated
- 9-hour autonomous run: 3x NVIDIA Nemotron-3-Nano-30B-A3B, 199 rounds, 52 Python files, 402 memories, 0 errors
- Local quickstart on LM Studio (Qwen3-Coder-30B)
- EPYC 8-GPU deployment via git clone
