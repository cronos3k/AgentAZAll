# 2. Related Work — The Protocol Landscape

## 2.1 Historical Foundations

The problem of agent communication predates large language models by three decades.

**KQML** (Knowledge Query and Manipulation Language), developed in the early 1990s under DARPA's Knowledge Sharing Effort, introduced the concept of *performatives* — semantic message types based on speech act theory [1]. A message was not just data; it was an assertion, a query, a request, or a denial. This semantic layer enabled agents with no shared codebase to coordinate through shared meaning.

**FIPA ACL** (Foundation for Intelligent Physical Agents, Agent Communication Language), standardized in the late 1990s, refined KQML with approximately twenty communicative acts grounded in BDI (Beliefs, Desires, Intentions) mental state models [2]. FIPA ACL achieved formal standardization through IEEE but saw limited adoption outside academic multi-agent systems research.

Both KQML and FIPA ACL got one thing right: agent communication is fundamentally about exchanging *meaningful messages*, not about the transport mechanism. Neither prescribed how messages should be delivered. Both disappeared from industry practice when the agent systems they served failed to reach production.

The core insight — that transport is orthogonal to communication semantics — would prove durable.

## 2.2 Model Context Protocol (MCP)

Anthropic's Model Context Protocol [3], released in November 2024, addresses the integration between LLM applications and external tools. MCP uses JSON-RPC 2.0 over stdio (local) or HTTP with Server-Sent Events (remote) to expose three primitive types: **Tools** (model-invoked capabilities), **Resources** (application-provided data), and **Prompts** (user-controlled templates).

MCP is well-designed for its purpose: bridging an LLM's context window with external functionality. However, it carries structural limitations when applied to inter-agent communication:

**Context window coupling.** Every registered tool's description is injected into the model's prompt. As the number of tools grows, context budget shrinks — creating a direct tradeoff between capability and reasoning capacity.

**Connection dependency.** MCP requires persistent connections (stdio pipes or SSE streams). If the connection drops, the server's state is lost. This makes MCP unsuitable for asynchronous, offline, or intermittent communication.

**No identity layer.** MCP authenticates at the transport level (tokens, OAuth). There is no mechanism for a message to carry self-authenticating proof of origin that survives forwarding or relay.

**Unidirectional design.** MCP is a client-server protocol. The model calls tools on a server. Two agents cannot use MCP to talk to each other without an intermediary that translates one agent's tool calls into another agent's resources — a pattern that adds complexity without adding capability.

## 2.3 Agent-to-Agent Protocol (A2A)

Google's A2A protocol [4], released in April 2025 and subsequently donated to the Linux Foundation, directly addresses peer-to-peer agent communication. Agents publish **Agent Cards** — JSON metadata documents at `/.well-known/agent.json` — declaring their capabilities, skills, endpoints, and authentication methods. Communication uses JSON-RPC 2.0 over HTTP/HTTPS, with SSE for streaming and webhooks for asynchronous notifications.

A2A represents genuine progress toward agent interoperability:

**Discovery.** Agent Cards provide a standardized way for agents to advertise their capabilities. This is conceptually elegant and draws on the well-known URI pattern from web standards.

**Stateful tasks.** A2A introduces a task model with unique identifiers, status tracking, and artifact history — acknowledging that agent interactions are conversations, not single request-response pairs.

**DID support.** Decentralized Identifiers (DIDs) are supported for identity verification, pointing toward cryptographic trust without centralized authorities.

However, A2A inherits the assumptions of its web origins:

**Always-online requirement.** Agent Cards must be served at HTTP endpoints. Webhook callbacks require reachable URLs. An agent behind a firewall, on a local network, or running offline cannot participate without proxy infrastructure.

**Network-centric state.** Task state lives on the responding agent's server. If that server is unavailable, the task's history is inaccessible. The protocol has no mechanism for state to survive server restarts or network partitions.

**Transport lock-in.** Despite its flexibility, A2A is fundamentally an HTTP protocol. Agents cannot communicate over email, FTP, or local filesystem — transports that exist in every computing environment regardless of network configuration.

## 2.4 Agent Communication Protocol (ACP)

IBM's Agent Communication Protocol [5], released in March 2025, takes a REST-native approach to agent orchestration. ACP distinguishes itself by explicit support for air-gapped enterprise environments and asynchronous multi-part MIME streaming.

ACP is the closest existing protocol to our design philosophy. It recognizes that enterprise environments cannot always guarantee persistent connections, that REST calls should be debuggable with `curl`, and that agent metadata belongs with the agent rather than in a central registry.

The gap remains: ACP is still API-first. The data model is HTTP requests and responses, not files. An agent's state lives in API endpoints, not on the filesystem. While ACP can operate in air-gapped networks, it still requires HTTP infrastructure within that network.

## 2.5 OpenAI's Position

As of early 2026, OpenAI has not published a dedicated agent-to-agent protocol. Their approach treats agent communication as a routing problem within their API: agents call the Assistants API, which manages threads, runs, and tool use internally [6]. OpenAI participates in the Agentic AI Foundation (AAIF) standardization effort and supports MCP integration, but their practical stance is that agent interoperability is best solved at the platform level rather than the protocol level.

This is a reasonable position for a cloud-first vendor. It is not a solution for agents that need to communicate outside any single vendor's platform.

## 2.6 The Gap

The following table summarizes the landscape:

| Property | KQML/FIPA | MCP | A2A | ACP | **This work** |
|----------|-----------|-----|-----|-----|---------------|
| Peer-to-peer | Yes | No | Yes | Brokered | Yes |
| Offline capable | Yes | No | No | Partial | **Yes** |
| Transport independent | Yes | No | No | No | **Yes** |
| Cryptographic signing | No | No | Transport | Transport | **Message-level** |
| Model agnostic | Yes | No | Yes | Yes | **Yes** |
| No external dependencies | Yes | No | No | No | **Yes** |
| Inspectable (plain text) | Partial | No | No | Partial | **Yes** |
| Empirically validated | Limited | N/A | N/A | N/A | **1,744 messages** |

None of the contemporary protocols treat the filesystem as the primary data model. None achieve true transport independence — the ability for the same message, in the same format, to be delivered by HTTPS, SMTP, FTP, or a USB drive. None embed cryptographic signatures at the message level rather than the transport level.

This is the gap we fill.

---

*Next: [Design Principles](03-design-principles.md)*
