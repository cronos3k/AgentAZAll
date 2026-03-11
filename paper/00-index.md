# The Mailbox Principle

## Filesystem-First Communication for Autonomous AI Agents

**Gregor H. Max Koch, MSc**

*Independent Researcher*

March 2026

---

### Abstract

Contemporary agent communication protocols — MCP, A2A, ACP — share an unexamined assumption: that AI agents require specialized, connection-oriented infrastructure to exchange messages. We challenge this assumption by presenting AgentAZAll, a system built on a different premise: an agent's mailbox is a directory, a message is a text file, and the transport is irrelevant.

We describe a filesystem-first architecture where all agent state — messages, memory, identity — exists as plain text files organized by date. Three interchangeable transport backends (HTTPS relay, SMTP/IMAP email, FTP) deliver messages into this filesystem without the agent needing to know which one was used. Every message carries an Ed25519 signature embedded in the message body itself, surviving any relay, forward, or copy operation.

We validate this design empirically. In a controlled integration test, four autonomous LLM instances spanning three distinct model architectures (Qwen3-Coder 81B, Hermes-4 70B, Devstral 24B) exchanged 1,744 cryptographically signed messages across all three transports over 30 minutes, with zero protocol failures and a 98.8% inference success rate. Separately, agents running Claude Opus 4, Qwen 3.5 9B, and Devstral 24B communicated over this protocol in production for multiple weeks, discovering and resolving integration issues through the protocol itself.

The result suggests that for asynchronous, loosely coupled agent messaging, the communication problem has been overcomplicated. The simplest design — files in directories, signed and delivered — provides a robust and practical alternative to connection-oriented protocols.

---

### Table of Contents

1. [Introduction — The Question Nobody Asks](01-introduction.md)
2. [Related Work — The Protocol Landscape](02-related-work.md)
3. [Design Principles — Five Axioms](03-design-principles.md)
4. [System Architecture](04-architecture.md)
5. [Cryptographic Identity](05-cryptographic-identity.md)
6. [The Transport Layer — Three Protocols, One Interface](06-transport-layer.md)
7. [Experimental Design](07-experimental-design.md)
8. [Results](08-results.md)
9. [Cross-Model Discourse Analysis](09-cross-model-communication.md)
10. [Discussion — Why Simplicity Scales](10-discussion.md)
11. [Conclusion](11-conclusion.md)
12. [References](12-references.md)

---

*Correspondence: github.com/cronos3k/AgentAZAll*
