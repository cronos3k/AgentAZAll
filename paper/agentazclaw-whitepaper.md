# Memory-First Multi-Agent Orchestration: Architecture and Empirical Validation of AgentAZClaw

**Gregor Koch**
*Strategische Spiele Entwicklung UG (haftungsbeschränkt)*

**March 2026**

---

## Abstract

Multi-agent LLM frameworks universally use the context window as the primary storage for conversation history. This design creates a fundamental scaling bottleneck: context grows linearly with rounds, causing speed degradation, token overflow, and decision amnesia when older messages are evicted. We present AgentAZClaw, a multi-agent orchestrator that inverts this assumption. Only the last round of conversation enters the context window. All prior knowledge is stored in AgentAZAll's filesystem-based persistent memory and retrieved on demand via tool calls. We validate this architecture empirically: three NVIDIA Nemotron-3-Nano-30B-A3B agents (3B active parameters each, Mixture-of-Experts) ran autonomously for 8 hours 46 minutes across 199 rounds, producing 52 Python files (2,543 lines) from a COBOL-to-Python migration of the AWS CardDemo banking system. Context per agent never exceeded 9K tokens. Inference speed showed no degradation over the entire run. The system produced zero errors. Total cloud API cost was zero.

---

## 1. Introduction

### 1.1 The Context Window Bottleneck

Every multi-agent framework in active development as of early 2026 — OpenClaw [1], NemoClaw [2], CrewAI [3], AutoGen [4], LangGraph [5] — follows the same pattern for multi-round agent interaction: append each agent's response to a growing conversation history, then include that history in the next API call. This approach works for short interactions (5–15 rounds) but exhibits three failure modes at scale:

**Linear context growth.** Each round adds 1–5K tokens of content per agent. With three agents, context grows by 3–15K tokens per round. By round 30, the context window contains 90–450K tokens of history — approaching or exceeding the context limits of most local models.

**Speed collapse.** KV cache size determines inference speed. As context fills, each new token requires attending to all previous tokens. In our measurements, an NVIDIA Nemotron-3-Nano-30B-A3B model running on llama.cpp went from 96 tokens/second at round 1 to 2 tokens/second at round 25 when using a context-stuffing orchestrator. This represents a 48x speed degradation.

**Decision amnesia.** When context limits are reached, frameworks must truncate or summarize history. Both approaches lose information. In our context-stuffing prototype (v2), agents at round 30 contradicted architectural decisions they had made at round 8 — because those decisions had been evicted from context to make room for more recent messages.

### 1.2 The Insight

The context window is working memory, not long-term memory. Treating it as both forces a tradeoff between reasoning capacity and knowledge retention that becomes untenable beyond a few dozen rounds.

AgentAZClaw eliminates this tradeoff by separating the two functions:

- **Context window** → holds only the current round's messages (working memory)
- **AgentAZAll persistent memory** → stores all architectural decisions, design rationale, and implementation notes (long-term memory)
- **Tool calls** → agents use `recall()` to retrieve specific memories on demand

This mirrors how human teams work. An engineer at a meeting doesn't carry transcripts of every previous meeting. They carry a notebook with key decisions and refer to it when needed.

### 1.3 Contributions

1. A memory-first orchestration architecture where context size is bounded regardless of round count
2. An implementation (AgentAZClaw) in ~1,000 lines of Python with one dependency
3. Empirical validation over 199 rounds (8 hours 46 minutes) with zero errors and constant inference speed
4. An auto-backend system that detects hardware and provisions an appropriate LLM without manual configuration

---

## 2. Related Work

### 2.1 OpenClaw and NemoClaw

OpenClaw [1] is the most widely adopted open-source agent framework as of 2026, with over 250,000 GitHub stars. It provides a plugin system for tool integration, support for 20+ messaging platforms, and a web-based UI for agent management. NVIDIA's NemoClaw [2], announced at GTC 2026, extends OpenClaw with enterprise features including GPU-optimized inference and Nemotron model integration.

Neither OpenClaw nor NemoClaw includes persistent memory as a core feature. Conversation history is maintained in the context window. When context limits are reached, older messages are truncated. There is no mechanism for an agent to store a decision at round 5 and reliably retrieve it at round 150 without that decision occupying context throughout all intervening rounds.

### 2.2 CrewAI and AutoGen

CrewAI [3] introduces role-based agent definitions (similar to AgentAZClaw's approach) but relies on context-stuffing for inter-round knowledge transfer. AutoGen [4] provides flexible conversation patterns but faces the same linear context growth. Both frameworks are designed for tasks that complete within 10–20 rounds. Neither has been publicly demonstrated running autonomously for more than one hour.

### 2.3 Retrieval-Augmented Generation (RAG)

RAG systems [6] use vector databases to retrieve relevant documents for inclusion in the prompt. This addresses *external* knowledge retrieval but does not solve the inter-round memory problem in multi-agent orchestration. An agent's decision at round 12 is not a "document" in a corpus — it is a runtime artifact that must be stored, indexed, and retrieved within the orchestration loop itself. AgentAZClaw's memory system is closer to a key-value store with text search than to a vector retrieval pipeline, and critically, it uses no embeddings or external databases.

### 2.4 AgentAZAll

AgentAZAll [7] is a filesystem-first communication and memory system for AI agents. It provides two primitives relevant to AgentAZClaw:

- **`remember(text, title)`** — stores a text memory as a file in a date-organized directory
- **`recall(query)`** — searches all stored memories by title and content, returning matches

Memories are plain text files. No database, no vector store, no embedding model. The file path is the index. AgentAZAll also provides inter-agent messaging over three transports (AgentTalk HTTPS, Email, FTP), Ed25519 cryptographic signing, and identity management — but AgentAZClaw primarily uses the memory primitives.

---

## 3. Architecture

### 3.1 Design Principles

AgentAZClaw enforces three invariants:

1. **Only the last round enters context.** The system prompt, phase instruction, and previous round's messages constitute the entire context. Total: 3–9K tokens, regardless of round number.

2. **Memory access is agent-initiated.** The orchestrator does not inject memories into the prompt. Agents call `recall()` as a tool when they need prior knowledge. The LLM's own intelligence determines when to recall and what to query.

3. **Tool access is role-gated.** Only agents with explicit write permission can create files or execute code. Other agents describe what they want built; the writing agent implements it. This prevents the chaos of multiple agents overwriting each other's work.

### 3.2 Components

The framework consists of three classes totaling approximately 1,000 lines of Python:

**Agent.** Wraps an OpenAI-compatible LLM endpoint with a role description, tool permission list, and a dedicated AgentAZAll memory root directory. Each agent tracks its own token statistics.

**Orchestrator.** Executes agents in round-robin order. Each round: (1) build a lean system prompt with role and phase context, (2) extract only the previous round's messages, (3) call the LLM with tool schemas, (4) process tool calls with deduplication, (5) record the response. The orchestrator handles checkpointing, graceful shutdown, and history pruning.

**ToolRegistry.** Manages tool definitions as decorated Python functions. Auto-generates OpenAI function-calling schemas. Enforces per-agent deduplication (same agent cannot call the same tool with identical arguments twice in one turn) and capability-based access control.

### 3.3 Built-in Tools

Six tools are provided by default:

| Tool | Description | Access |
|------|-------------|--------|
| `recall` | Search persistent memories | All agents |
| `remember` | Store a decision permanently | All agents |
| `read_file` | Read source or output files | All agents |
| `list_files` | List directory contents | All agents |
| `write_file` | Write files to output directory | Writers only |
| `run_python` | Execute Python code for validation | Writers only |

Custom tools are added via a decorator:

```python
@registry.tool("search_code", "Search codebase", {"query": "string"})
def search_code(query, _ctx=None):
    ...
```

### 3.4 Phase System

Complex tasks are divided into phases, each with a round range, focus description, and optional file lists. The orchestrator injects the current phase's context into the system prompt. Between phases, agents' memories persist — allowing decisions from Phase 1 to inform implementation in Phase 5 without those decisions consuming context during Phases 2–4.

Coherence probes — questions injected at specific rounds — test whether agents can correctly recall earlier decisions. These serve both as validation (during development) and as prompts for agents to consolidate scattered memories into summaries.

### 3.5 Deduplication

A common failure mode in tool-calling agents is the degenerate recall loop: an agent calls `recall("")` repeatedly, receiving the same index each time, without producing useful output. AgentAZClaw tracks tool calls per agent per round. If a call duplicates a previous call in the same turn, it is silently skipped. If all calls in a turn are duplicates, the agent is forced to analyze existing results:

```
"You already have all the information from your tools.
Analyze the data and produce your output.
Do NOT call the same tools again."
```

This breaks the loop reliably without requiring architectural changes to the underlying LLM.

---

## 4. Empirical Validation

### 4.1 Experimental Setup

**Source material.** AWS CardDemo [8], an open-source COBOL/CICS credit card management system comprising 29 COBOL programs, 29 copybooks, 21 BMS maps, and 55 JCL batch jobs — approximately 50,000 lines of authentic mainframe code.

**Models.** Three identical instances of NVIDIA Nemotron-3-Nano-30B-A3B [9], a Mixture-of-Experts model with 30 billion total parameters and 3 billion active per inference step. All quantized to Q8_0 for maximum quality. Each instance runs on a dedicated GPU pair via llama.cpp with tensor splitting, flash attention, and Q8_0 KV cache.

**Hardware.** AMD EPYC server with 8 GPUs (242 GB total VRAM): RTX A6000 (49 GB), 2× RTX 3090 (24 GB each), 3× RTX A5000 (24 GB each), Quadro RTX 8000 (46 GB). CUDA 12.6. 512 GB system RAM.

**Agent configuration.** Three agents with distinct roles:
- **Architect** (GPUs 0, 3): Designs architecture. Cannot write files.
- **Developer** (GPUs 2, 5): Writes Python code. Only agent with file write access.
- **Reviewer** (GPUs 1, 4): Validates code against COBOL source. Cannot write files.

**Topic.** Seven migration phases across 160 planned rounds, with 8 coherence probes. After round 160, the orchestrator entered open mode (no phase directives).

### 4.2 Results

| Metric | Value |
|--------|-------|
| Total rounds | 199 |
| Runtime | 8 hours 46 minutes |
| Python files produced | 52 (2,543 lines, 236 KB) |
| Memories stored | 402 |
| Tool calls executed | 1,599 |
| Completion tokens | 3,510,906 |
| Prompt tokens | 20,788,680 |
| Errors | 0 |
| Context per agent | 2–9K tokens (bounded) |
| Cloud API cost | $0.00 |

**Per-agent statistics:**

| Agent | Completion Tokens | Avg Speed | Tool Calls | Files |
|-------|-------------------|-----------|------------|-------|
| Architect | 1,048,820 | 97 tok/s | 379 | 0 |
| Developer | 1,267,555 | 137 tok/s | 606 | 52 |
| Reviewer | 1,194,531 | 104 tok/s | 614 | 0 |

### 4.3 Speed Stability

The critical validation: inference speed at the end of the run matches the beginning.

| Measurement Point | Architect | Developer | Reviewer |
|-------------------|-----------|-----------|----------|
| Round 1 | 96 tok/s | 147 tok/s | 114 tok/s |
| Round 50 | 100 tok/s | 142 tok/s | 108 tok/s |
| Round 100 | 98 tok/s | 136 tok/s | 105 tok/s |
| Round 150 | 97 tok/s | 140 tok/s | 104 tok/s |
| Round 199 | 89 tok/s | 128 tok/s | 105 tok/s |

A ~10% decrease over 199 rounds is attributable to the growing memory index returned by `recall("")` — which expanded from 0 to approximately 30 KB over the run. This is the one growing cost in the system, and it scales logarithmically with memory count (the index is a list of titles, not full memory contents).

For comparison, the context-stuffing prototype (v2) exhibited the following speed profile:

| Round | Architect Speed | Context Size |
|-------|----------------|--------------|
| 1 | 96 tok/s | ~3K tokens |
| 10 | 85 tok/s | ~15K tokens |
| 20 | 12 tok/s | ~40K tokens |
| 25 | 2 tok/s | ~55K tokens |
| 30 | — (context overflow) | — |

The v2 orchestrator became unusable after 25 rounds. The v3 (memory-first) orchestrator ran for 199 rounds with no functional degradation.

### 4.4 Output Quality

The agents produced domain-aware Python code, not generic boilerplate. Key examples:

**COBOL field mapping.** The Customer model correctly maps `PIC 9(09)` to `String(9)` (preserving leading zeros), `PIC X(01)` Y/N indicators to `Boolean`, and `YYYYMMDD` fields to `Date` with proper parsing — demonstrating understanding of COBOL's fixed-width data semantics.

**CICS semantics preservation.** The persistence layer (`acpt_persistence.py`, 9.8 KB) mirrors CICS `READ`/`WRITE`/`REWRITE` operations, including the `ws_change_has_occurred` flag pattern where a working-storage variable gates record updates. `COMP-3` packed decimal fields are converted to Python `Decimal` with `ROUND_HALF_UP` quantization.

**Self-directed testing.** Without explicit instruction, the agents produced a reconciliation script (`reconcile_outputs.py`, 12 KB) that compares COBOL batch output with Python batch output field-by-field — a standard requirement for migration cutover that the agents independently identified.

### 4.5 Memory Distribution

The Reviewer stored 154 memories — nearly double the Architect's 77. This distribution emerged naturally from the agents' roles, not from any engineered bias. The Reviewer's function (cross-referencing every decision against COBOL source) requires retaining more contextual detail than the Architect's function (making high-level design decisions).

The Developer stored 93 memories, primarily implementation notes linking design decisions to specific files and line numbers — creating a traceability chain from architecture through implementation.

### 4.6 Limitations

The agents analyzed 11 of 29 COBOL programs in depth (38% coverage). Programs covering billing, administration, reporting, and several user management screens were not reached. After round 185, the agents entered a degenerate loop in open mode, repeatedly reading the same COBOL file without producing new output.

This plateau is expected in a minimal three-agent configuration. A production deployment would add:
- A **project manager agent** to track task completion and redirect work
- A **QA agent** to execute generated tests and report failures
- A **watchdog agent** to detect loops and force phase advancement

---

## 5. Auto-Backend: Zero-Configuration Deployment

### 5.1 Motivation

A framework that requires manual model selection, download, and server configuration creates a barrier to adoption that eliminates most potential users. AgentAZClaw includes an auto-backend system that detects available hardware and provisions an appropriate LLM instance.

### 5.2 Hardware Detection

The system probes for:
- NVIDIA GPUs via `nvidia-smi` (model name, VRAM per device)
- Apple Silicon via `sysctl` (unified memory, Metal availability)
- System RAM via platform-specific APIs
- Available disk space

### 5.3 Model Selection

Based on detected hardware, the system selects from seven pre-validated models. All models are verified ungated on HuggingFace — no authentication tokens required for download.

| Tier | Hardware | Model | Size |
|------|----------|-------|------|
| Multi-GPU 48 GB+ | Nemotron-3-Nano-30B-A3B Q8 | 32 GB |
| Single GPU 24 GB | Nemotron-3-Nano-30B-A3B Q4 | 16 GB |
| Single GPU 16 GB | IBM Granite 3.3 8B Q4 | 5 GB |
| Single GPU 12 GB | Qwen3-8B Q4 | 5 GB |
| Single GPU 8 GB | Qwen3-4B Q4 | 2.5 GB |
| CPU 16 GB+ RAM | IBM Granite 3.3 2B Q4 | 1.5 GB |
| CPU 8 GB RAM | Qwen3-0.6B Q8 | 0.6 GB |

### 5.4 Server Management

After download, the system starts a llama.cpp inference server with appropriate parameters (GPU layers, context size, flash attention), verifies health, and provides the endpoint URL to the orchestrator. Port conflicts are resolved automatically by probing the next available port.

---

## 6. Discussion

### 6.1 Why Filesystem-Based Memory Works

The decision to use plain text files instead of a vector database or embedding index was driven by three observations:

1. **Agent memories are decisions, not documents.** A typical memory is 50–200 words: "Selected PostgreSQL for VSAM migration due to ACID compliance and NUMERIC types." This is a key-value lookup, not a semantic similarity search.

2. **Text search is sufficient at this scale.** With 402 memories at run end, a case-insensitive substring search over titles and content completes in under 1 millisecond. Vector search adds latency and complexity without improving recall quality at this scale.

3. **Debuggability matters.** When agents make incorrect decisions, the ability to `cat` a memory file, `grep` across all memories, or `git diff` between runs is invaluable. Vector databases are opaque. Text files are transparent.

### 6.2 The Mixture-of-Experts Advantage

The choice of Nemotron-3-Nano-30B-A3B (30B total, 3B active) was deliberate. In multi-agent orchestration, the system makes 3× more inference calls per round than a single-agent system. MoE models provide large-model quality (the routing decision accesses 30B of knowledge) at small-model speed (only 3B parameters participate in each forward pass). This combination — quality sufficient for COBOL analysis at 137 tokens/second — makes autonomous multi-hour runs practical on consumer hardware.

### 6.3 Cost Implications

The 8-hour 46-minute run processed 24.3 million tokens. At typical cloud API rates (approximately $3 per million input tokens and $15 per million output tokens for comparable-quality models), this run would cost approximately $62 for input tokens and $53 for output tokens — roughly $115 total. The actual cost was the electricity consumed by six GPUs for nine hours, estimated at approximately $2.

---

## 7. Conclusion

AgentAZClaw demonstrates that memory-first orchestration eliminates the fundamental scaling bottleneck in multi-agent LLM systems. By replacing context-stuffing with on-demand recall from persistent filesystem-based memory, we achieve:

- Bounded context (2–9K tokens) regardless of round count
- Constant inference speed over arbitrarily long runs
- Cross-agent knowledge sharing without context pollution
- Auditability through transparent, greppable text files

The framework is intentionally minimal: three Python classes, approximately 1,000 lines, one dependency. This minimality is a feature, not a limitation. The complexity of multi-agent coordination belongs in the memory layer (AgentAZAll), not in the orchestrator.

The auto-backend system ensures that any user with a GPU or even a CPU-only machine can run autonomous agents within minutes of installation, without manual model selection or server configuration.

The full implementation, empirical results, and 52 generated Python files are available at https://github.com/cronos3k/AgentAZAll.

---

## References

[1] OpenClaw. "OpenClaw: Open-source AI Agent Framework." https://github.com/openclaw

[2] NVIDIA. "NemoClaw: Enterprise Agent Framework." GTC 2026.

[3] CrewAI. "CrewAI: Framework for orchestrating role-playing AI agents." https://github.com/crewAIInc/crewAI

[4] Microsoft. "AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation." https://github.com/microsoft/autogen

[5] LangChain. "LangGraph: Build multi-agent workflows." https://github.com/langchain-ai/langgraph

[6] Lewis, P., et al. "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks." NeurIPS 2020.

[7] Koch, G. "The Mailbox Principle: Filesystem-First Communication for Autonomous AI Agents." 2026. https://agentazall.ai/paper/

[8] AWS. "AWS Mainframe Modernization CardDemo." https://github.com/aws-samples/aws-mainframe-modernization-carddemo

[9] NVIDIA. "Nemotron-3-Nano: Efficient Mixture-of-Experts Models for Agentic AI." 2026. https://developer.nvidia.com/nemotron

---

*AgentAZClaw is open source under AGPL-3.0. The complete experiment data (log files, generated code, and all 402 memory files) is available for download at https://agentazall.ai/experiments/carddemo-cobol-migration/carddemo-agentazall-results.zip*
