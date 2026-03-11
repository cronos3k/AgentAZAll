# 1. Introduction — The Question Nobody Asks

## 1.1 The Paradox

In 2026, large language models can write compilers, prove theorems, and hold nuanced conversations across languages. Yet when two AI agents need to send each other a message, the industry reaches for connection-oriented protocols that assume persistent network links, cloud infrastructure, and specific runtime environments.

The Model Context Protocol (MCP) injects tool descriptions into the LLM's context window, consuming tokens that could be spent reasoning. The Agent-to-Agent protocol (A2A) requires agents to publish discovery documents at well-known HTTP endpoints. The Agent Communication Protocol (ACP) mandates REST API registration with central brokers. Each assumes that agent communication is fundamentally an API design problem.

We question that assumption.

## 1.2 The Question

What if we discard every assumption about how AI agents should communicate and start from first principles?

A human checks their email. The email is a file. It arrived via SMTP, or maybe IMAP, or maybe someone dropped it on a USB drive. The human does not care. They read the file. They write a reply. The reply leaves by whatever transport happens to be available.

This is the mental model we propose for AI agents. An agent's mailbox is a directory on a filesystem. A message is a plain text file with headers and a body. The agent reads its inbox by listing files. It sends a reply by writing a file to its outbox. A daemon process — entirely separate from the agent — handles the transport: pushing outbox files to recipients via HTTPS, SMTP, or FTP, and pulling new files into the inbox from the same.

The agent never knows which transport was used. It never needs to.

## 1.3 The Thesis

We argue that for asynchronous, loosely coupled agent communication under weak infrastructure assumptions, the simplest possible design — plain text files in dated directories, signed with Ed25519, delivered by interchangeable transports — is a strong and often preferable design point compared to purpose-built protocols. It is preferable because:

- It requires no active network connections. Agents communicate asynchronously through the filesystem, which works offline, over air gaps, and across unreliable networks.
- It is model-agnostic. Any system that can read a text file and execute a command-line tool can participate — no SDK, no library, no API binding required.
- It is transport-agnostic. The same message format works over HTTPS, SMTP/IMAP, FTP, local filesystem copy, or any future transport without modification.
- It is cryptographically self-authenticating. Ed25519 signatures are embedded in the message body, not in transport-layer headers that can be stripped by intermediaries.
- It is inspectable. Every message is a human-readable text file. Debugging is `cat`. Search is `grep`. Backup is `rsync`.

## 1.4 Contribution

AgentAZAll is not a proposed architecture awaiting implementation. It is a working, open-source system — published as a Python package (`pip install agentazall`), hosted on GitHub, and operating on a public relay server that anyone can use for testing. The claims in this paper can be verified by installing the package and running the included integration tests. Everything described here already exists, already runs, and is already being used.

This paper presents the design and validates it empirically:

1. **Architecture**: A complete filesystem-first agent communication system with three interchangeable transport backends, inline cryptographic signatures, and a unified sync daemon. The entire core runs on Python's standard library with zero external dependencies.

2. **Integration test**: Four autonomous LLM instances — Qwen3-Coder-Next (81B parameters), Hermes-4-70B, and Devstral-Small (24B) — exchanged 1,744 cryptographically signed messages across all three transports in 30 minutes of autonomous operation, with zero protocol failures.

3. **Field deployment**: The system was used in production for weeks of inter-agent communication between models from three different vendors (Anthropic, Alibaba, Mistral), with agents discovering and resolving integration issues through the protocol itself.

4. **Analysis**: We present quantitative results on message throughput, inference latency, and cross-model discourse coherence, and qualitative analysis of emergent conversational behaviors between architecturally distinct language models.

## 1.5 Paper Structure

Chapter 2 surveys the current protocol landscape. Chapter 3 states our five design axioms. Chapters 4-6 describe the system architecture, cryptographic identity, and transport layer. Chapter 7 details the experimental setup. Chapter 8 presents quantitative results. Chapter 9 analyzes cross-model discourse. Chapter 10 discusses implications and limitations. Chapter 11 concludes.

---

*Next: [Related Work](02-related-work.md)*
