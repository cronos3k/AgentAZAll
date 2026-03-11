# 8. Results

## 8.1 Aggregate Performance

Three transport rounds were executed sequentially, each running for 600 seconds (10 minutes). All four bot instances operated autonomously after initial seeding. No human intervention occurred during any round.

**Table 1. Per-Round Message Volume**

| Round | Transport | Messages Sent | Messages Received | LLM Calls | LLM Errors | Success Rate |
|-------|-----------|:------------:|:-----------------:|:---------:|:----------:|:------------:|
| 1 | AgentTalk Relay | 281 | 278 | 145 | 1 | 99.3% |
| 2 | Local Email | 598 | 582 | 310 | 4 | 98.7% |
| 3 | Local FTP | 865 | 847 | 382 | 5 | 98.7% |
| **Total** | **All** | **1,744** | **1,707** | **837** | **10** | **98.8%** |

The difference between sent and received counts (37 messages, 2.1%) reflects timing: messages deposited in outboxes in the final seconds of each round were not yet delivered before the processes terminated. No messages were lost due to protocol failure.

## 8.2 Per-Bot Performance

**Table 2. Per-Bot Aggregate Across All Rounds**

| Designation | Model | Parameters | Messages Sent | Avg LLM Latency | GPU Config |
|-------------|-------|:----------:|:------------:|:----------------:|------------|
| Qwen-81B | Qwen3-Coder-Next | 81B | 577 | 2,500 ms | 3 GPUs (dedicated) |
| Devstral-24B | Devstral-Small | 24B | 605 | 1,650 ms | 1 GPU (dedicated) |
| Hermes-70B-1 | Hermes-4-70B | 70B | 295 | 10,100 ms | 3 GPUs (shared) |
| Hermes-70B-2 | Hermes-4-70B | 70B | 267 | 10,100 ms | 3 GPUs (shared) |

**Table 3. Per-Bot Per-Round Breakdown**

| Bot | Round 1 (Relay) | Round 2 (Email) | Round 3 (FTP) |
|-----|:--------------:|:---------------:|:-------------:|
| Qwen-81B | 96 sent, 2413 ms | 199 sent, 2386 ms | 282 sent, 2709 ms |
| Devstral-24B | 96 sent, 1588 ms | 210 sent, 1803 ms | 299 sent, 1651 ms |
| Hermes-70B-1 | 43 sent, ~8800 ms | 96 sent, 8835 ms | 156 sent, 13493 ms |
| Hermes-70B-2 | 43 sent, ~8800 ms | 93 sent, 8650 ms | 128 sent, 13475 ms |

## 8.3 Key Findings

### Finding 1: All Transports Delivered Reliably

Zero protocol-level failures were observed across any transport in any round. Every message that was sent was received by the intended recipient, provided the round did not terminate before delivery completed. The protocol's message format survived serialization and deserialization across HTTPS JSON payloads, SMTP/IMAP email bodies, and FTP file transfers without modification.

This is the central result. The same message, carrying the same inline Ed25519 signature, was delivered identically by three fundamentally different transport mechanisms. The message format required no transport-specific adaptation.

### Finding 2: Transport Latency Dominates Throughput

The FTP round produced 3.1x the message volume of the relay round (865 vs. 281), despite identical bot configurations, inference parameters, and duration. The only variable was transport latency.

| Transport | Per-Message Overhead | Messages/10 min |
|-----------|---------------------|:--------------:|
| AgentTalk Relay | ~100-200 ms (internet round-trip) | 281 |
| Local Email | ~50-100 ms (SMTP handshake) | 598 |
| Local FTP | ~10-20 ms (file I/O) | 865 |

This ordering is predictable: local file operations are faster than local TCP protocol handshakes, which are faster than internet round-trips. The relevant observation is that the protocol itself imposed no additional overhead — the bottleneck was always the transport or the inference engine, never the message format.

### Finding 3: Model Size Does Not Predict Throughput

Devstral-24B (the smallest model at 24 billion parameters) was the most prolific agent, producing 605 messages — more than either 70B instance and more than the 81B instance. Its average inference latency (1,650 ms) was 1.5x faster than Qwen-81B (2,500 ms) and 6x faster than the Hermes-70B instances (10,100 ms).

This result has practical implications for multi-agent system design. In a communication-intensive workload where agents exchange short messages (2-4 sentences, constrained by `max_tokens=384`), a smaller model on dedicated hardware outperforms a larger model. The communication protocol should not assume or prefer any particular model scale.

### Finding 4: Shared GPU Contention Is the Real Bottleneck

Hermes-70B-1 and Hermes-70B-2 shared the same inference endpoint (port 8181) and the same three GPUs. Together they produced 562 messages. Qwen-81B, with dedicated access to three different GPUs, produced 577 messages alone.

The Hermes instances' average latency increased from ~8,800 ms in Round 2 to ~13,400 ms in Round 3, as higher message volumes created more frequent inference contention. Meanwhile, Qwen-81B's latency remained stable across rounds (2,413 ms to 2,709 ms), and Devstral-24B's latency was essentially flat (1,588 ms to 1,803 ms).

This confirms that GPU contention, not protocol overhead, is the dominant scalability constraint. The filesystem-based protocol contributes negligible overhead compared to the cost of a single LLM inference call.

### Finding 5: Inference Reliability

Across 837 inference calls, 10 resulted in errors (1.2%). Error causes included HTTP timeouts on the shared Hermes endpoint during contention peaks. No inference errors were caused by message format issues — the protocol's plain-text messages were trivially parseable by all three model architectures.

The 98.8% LLM success rate was achieved without retry logic, circuit breakers, or error recovery mechanisms in the bot script. Failed inference calls simply resulted in no reply for that cycle; the next cycle processed the message successfully.

### Finding 6: Cryptographic Signatures Survived All Transports

All 1,744 sent messages contained inline Ed25519 signatures. These signatures were embedded in the message body using a PGP-style ASCII armor format. The signatures traversed:

- HTTPS JSON serialization and deserialization (AgentTalk relay)
- SMTP encoding, IMAP storage, and POP3 retrieval (email)
- FTP file upload and download (FTP)

In all cases, the signature block was preserved byte-for-byte. This validates the design decision to embed signatures in the message body rather than in transport-specific headers: body content is the one thing that all transports are designed to preserve.

## 8.4 Efficiency Analysis

The protocol's overhead can be estimated by comparing the time spent on communication versus inference:

| Component | Time per Message (approx.) |
|-----------|:-------------------------:|
| LLM inference | 1,650 - 13,400 ms |
| Message serialization | < 1 ms |
| Filesystem write | < 1 ms |
| Transport delivery | 10 - 200 ms |
| Message parsing | < 1 ms |

The protocol's contribution to per-message latency is under 5 ms for local transports and under 200 ms for relay transport. In all cases, this is less than 10% of the total cycle time, with inference consuming 90-99% of each cycle.

This ratio is the correct design target. A communication protocol for LLM agents should be invisible — its overhead should be negligible compared to the inference cost that dominates every agent interaction.

---

*Next: [Cross-Model Communication](09-cross-model-communication.md)*
