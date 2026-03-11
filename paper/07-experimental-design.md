# 7. Experimental Design

## 7.1 Objective

We designed an integration test to answer one question: can architecturally distinct language models, running autonomously with no shared code or coordination mechanism, sustain coherent multi-party conversations through this protocol across all three transport backends?

This is not a unit test. It is a live-fire exercise where four independent LLM instances are given mailbox directories, personalities, and peer addresses, and left to converse for ten minutes per transport round. The only human intervention is the initial seed message.

## 7.2 Hardware

All experiments ran on a single AMD EPYC server:

- **CPU:** AMD EPYC (64 cores)
- **GPUs:** 8 GPUs, 242 GB total VRAM
  - 2x RTX 3090 (24 GB each)
  - 3x RTX A5000 (24 GB each)
  - 1x RTX A6000 (49 GB)
  - 1x Quadro RTX 8000 (46 GB)
- **RAM:** 512 GB
- **Inference:** llama-server (llama.cpp), one instance per model, pinned to specific GPUs via `CUDA_VISIBLE_DEVICES`

All models run locally. No cloud API calls. The relay server for AgentTalk transport is the public relay at `relay.agentazall.ai`; the email and FTP servers run on the same machine (localhost).

## 7.3 Models

Four bot instances using three distinct model architectures:

| Designation | Model | Parameters | Port | GPU Assignment |
|-------------|-------|-----------|------|----------------|
| **Qwen-81B** | Qwen3-Coder-Next | 81B | 8180 | GPUs 2, 5, 7 |
| **Hermes-70B-1** | Hermes-4-70B | 70B | 8181 | GPUs 0, 3, 6 |
| **Devstral-24B** | Devstral-Small | 24B | 8184 | GPU 1 |
| **Hermes-70B-2** | Hermes-4-70B | 70B | 8181 | (shared with Hermes-70B-1) |

Hermes-70B-1 and Hermes-70B-2 share the same inference endpoint. This was intentional: it tests the protocol under GPU contention, where two agents compete for the same model's attention. It also demonstrates that model identity and agent identity are orthogonal — two agents using the same model are distinct entities with distinct personalities, mailboxes, and cryptographic identities.

## 7.4 Agent Configuration

Each agent was configured with:

- **Personality.** A system prompt defining a conversational role (precise engineer, philosophical thinker, pragmatic reviewer, creative enthusiast). Responses were constrained to 2-4 sentences to maintain conversational pace.
- **Conversation history.** The last 8 messages per peer were retained in context, providing multi-turn coherence without unbounded context growth.
- **Inference parameters.** `max_tokens=384`, `temperature=0.8`. Short outputs, moderate creativity.
- **Cycle interval.** 3 seconds between inbox polls.
- **Duration.** 600 seconds (10 minutes) per round, enforced by a timer in the bot process.
- **Whitelist.** Each agent accepted messages only from the other three agents and the monitoring agent. All other addresses were rejected at the daemon level.

## 7.5 Safety Containment

The test enforced multiple safety boundaries:

1. **Whitelist-only filtering.** Each bot's daemon rejected messages from any address not in the peer whitelist. Even if an LLM hallucinated a send to an arbitrary address, the recipient would reject it.
2. **No shell access.** The bot script interacted with the system exclusively through the `agentazall` CLI via subprocess calls. No arbitrary command execution.
3. **PID-based kill switch.** Each bot's process ID was recorded. A `kill_all.sh` script could terminate all bots instantly.
4. **Duration limit.** Each bot process self-terminated after 600 seconds, regardless of conversation state.
5. **Monitoring agent.** The orchestrating agent ("keel") was whitelisted on all bots, allowing it to send messages into the conversation if intervention was needed. In practice, intervention was never required.

## 7.6 Conversation Seeding

To initiate conversations, seed messages were sent using a mesh topology:

```
Qwen-81B      →  Hermes-70B-1, Devstral-24B, Hermes-70B-2
Hermes-70B-1  →  Devstral-24B, Hermes-70B-2
Devstral-24B  →  Hermes-70B-2
```

This produces 6 initial message pairs covering all bot-to-bot edges. Each seed message introduced the sender, listed all peers with addresses, and posed an opening question about agent communication, protocol design, or autonomous collaboration.

After seeding, the bots operated autonomously. No further human intervention occurred until the round ended.

## 7.7 Three Transport Rounds

**Round 1: AgentTalk Relay.**
Transport configured to `agenttalk`. Messages traverse the internet to `relay.agentazall.ai` and back. This round tests the highest-latency, most realistic deployment scenario.

**Round 2: Local Email.**
A built-in email server (Python asyncio SMTP/IMAP/POP3) was started on localhost. Each bot's config was updated to use email transport with `smtp_server: 127.0.0.1:2525`, `imap_server: 127.0.0.1:1143`. Agent addresses were used as email usernames.

**Round 3: Local FTP.**
A built-in FTP server (pyftpdlib) was started on localhost. Each bot's config was updated to use FTP transport with a shared FTP root directory. All bots used the same FTP credentials (the FTP transport creates per-agent directories within the root).

Between rounds, processed message IDs were cleared so each round started with a fresh conversation. Transport reconfiguration was done by updating `config.json` and restarting the bot processes.

## 7.8 Metrics

The following metrics were collected per bot per round:

- **Messages received:** count of files in `inbox/` at round end
- **Messages sent:** count of files in `sent/` and `outbox/` at round end
- **LLM calls:** count of successful inference requests (from bot logs)
- **LLM errors:** count of failed inference requests
- **Average LLM latency:** mean response time in milliseconds
- **Total tokens:** aggregate token usage across all inference calls
- **Signature presence:** count of messages with valid inline Ed25519 signatures
- **Errors:** any exceptions or transport failures logged during the round
- **Sample messages:** first and last three messages per bot for qualitative analysis

All metrics were collected by a post-round analysis script that parsed bot logs, scanned mailbox directories, and aggregated results into JSON and human-readable summary files.

---

*Next: [Results](08-results.md)*
