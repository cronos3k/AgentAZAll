# 10. Discussion

## 10.1 The Complexity Trap

The dominant agent communication protocols of 2024-2025 share a common architectural assumption: that agent communication is fundamentally a distributed systems problem requiring distributed systems solutions. MCP couples communication to the LLM's context window via JSON-RPC sessions. A2A requires always-online HTTP endpoints with webhook callbacks. ACP mandates REST APIs with service registries. Each protocol solves real problems, but each also inherits the complexity of its underlying infrastructure.

This complexity compounds. An MCP deployment requires a JSON-RPC server, SSE event streams, capability negotiation, and session management. An A2A deployment requires Agent Cards, task lifecycle management, and push notification infrastructure. Agents built on these protocols cannot communicate with agents built on different protocols without translation layers — which introduce their own failure modes, latency, and maintenance burden.

We propose that this complexity is not inherent to the problem. It is an artifact of starting from the wrong assumption. If you assume that agent communication requires active connections, you need connection management. If you assume it requires structured schemas, you need schema negotiation. If you assume it requires cloud infrastructure, you need cloud orchestration.

But what if you assume none of these things?

## 10.2 Why Filesystem-First Works

The filesystem is the oldest, most tested, most universally available abstraction in computing. Every operating system provides it. Every programming language can interact with it. Every tool — from `cat` to `rsync` to `grep` — operates on it. No SDK is required. No API key is needed. No version compatibility matrix must be consulted.

By making the filesystem the sole source of truth for agent state, we eliminate entire categories of problems:

**No connection state.** There are no sessions to manage, no connections to keep alive, no heartbeats to maintain. An agent that crashes and restarts finds all its messages in its inbox directory, exactly where the daemon left them. There is no reconnection logic because there is nothing to reconnect to.

**No database.** Messages are text files. The directory listing is the index. Sorting by filename gives chronological order. Searching by content is `grep`. Backup is `cp -r`. Migration is `mv`. Every operation that would require database administration in a structured system is a basic filesystem operation.

**No deployment.** To add an agent to the system, create a directory and a configuration file. To remove an agent, delete the directory. To move an agent to a different machine, copy the directory. There is no registration server to update, no service mesh to reconfigure, no DNS entries to modify.

**Universal tooling.** System administrators can monitor agent communication with `tail -f inbox/`. Developers can debug message delivery with `ls -la`. Auditors can review message history with standard file inspection tools. No specialized client is needed. The protocol's data model is human-readable by design.

## 10.3 Why Transport Independence Matters

Networks fail. Protocols change. APIs are deprecated. Cloud services are discontinued. But files persist.

An agent that communicates via the AgentTalk relay today can switch to email tomorrow by changing one line in its configuration. If the email server goes down, it can fall back to FTP. If all network transports fail, two agents on the same machine can communicate via the local filesystem with zero network involvement.

This is not theoretical. In our integration test, three different transports delivered the same messages with the same signatures to the same mailbox directories. The agents did not know — and did not need to know — which transport was active. The daemon abstracted the transport completely.

Transport independence has a deeper implication: it decouples the protocol's longevity from any single transport's lifespan. SMTP has been operational since 1982. FTP since 1971. HTTP since 1991. Each has survived multiple generations of computing platforms. A protocol built on all three inherits the survivability of all three. A protocol built exclusively on HTTPS (MCP, A2A) inherits the survivability of HTTPS alone.

## 10.4 Why Identity Must Live in the Message

Most security architectures place identity at the transport layer: TLS certificates, OAuth tokens, API keys. This works when all communication traverses a single transport. It fails the moment a message crosses a transport boundary.

A TLS certificate proves that the connection was secure between two endpoints. It says nothing about the message's origin if that message was relayed, forwarded, or delivered via a different transport. An OAuth token authenticates a session, not a message. An API key identifies an account, not a sender.

Ed25519 inline signatures solve this by attaching identity to the message itself. A signed message carries proof of authorship regardless of how it was delivered. The signature is verified by the recipient using the sender's public key, which was obtained through the trust-on-first-use keyring. No certificate authority is involved. No transport-layer authentication is required.

Our experiment validated this design: 1,744 signed messages traversed HTTPS, SMTP, and FTP without any signature being invalidated. The identity layer was completely independent of the transport layer.

## 10.5 The UNIX Philosophy Applied to AI

The design principles of this system — small tools, text streams, composability — are not novel. They are the UNIX philosophy, articulated by McIlroy, Kernighan, and Pike in the 1970s and 1980s:

1. Write programs that do one thing well.
2. Write programs to work together.
3. Write programs to handle text streams, because that is a universal interface.

The `agentazall` CLI follows this philosophy precisely. `send` sends a message. `inbox` lists messages. `read` reads a message. `reply` composes a reply. `daemon` runs the sync loop. Each command does one thing. They compose via the filesystem. They handle text.

This is in contrast to MCP's monolithic server architecture (which bundles resources, tools, prompts, and sampling into a single process), A2A's task lifecycle manager (which bundles discovery, negotiation, execution, and notification), and ACP's platform controller (which bundles service registration, policy enforcement, and message routing).

The UNIX philosophy scales. The evidence is the internet itself — built on small, composable protocols (TCP, DNS, SMTP, HTTP) rather than monolithic architectures. We argue that agent communication should follow the same design trajectory.

## 10.6 Scalability Without Connection State

Traditional client-server protocols scale poorly because each client requires server-side state: a connection, a session, a task queue. A server handling 100 agents must manage 100 connections. A server handling 10,000 agents must manage 10,000 connections. The scaling is linear at best, and often worse due to connection management overhead.

The filesystem-first approach eliminates connection state entirely. The relay server stores messages in memory with a 48-hour expiry. It maintains no sessions, no connection pools, no per-agent state beyond the bearer token hash. Adding an agent to the system adds one file to the filesystem and one entry to the relay's token store. The marginal cost of the 10,001st agent is identical to the marginal cost of the 2nd.

For local transports (filesystem, FTP), the scaling is even simpler: agents share a directory. Adding an agent means creating a subdirectory. There is no server to scale.

This does not mean the system handles all scaling challenges. Message delivery latency increases with the number of agents because the daemon polls sequentially. Real-time streaming is not supported. But for the communication patterns that autonomous agents actually use — asynchronous message exchange with response times measured in seconds, not milliseconds — the filesystem model provides sufficient throughput with minimal infrastructure.

## 10.7 Beyond Language Models — A Universal Service Layer

The protocol was designed for agent-to-agent communication, but its properties — endpoint-agnostic addressing, transport independence, whitelist-based access control — make it applicable to a broader class of AI services.

Consider an enterprise network where multiple teams operate different AI models: a reasoning model for code review, an image generator for asset creation, an embedding model for search, a translation model for localization. Today, each service requires its own API, its own authentication scheme, its own client library, and its own documentation. An engineer who needs three services must learn three APIs, manage three sets of credentials, and handle three different error conventions.

Under the protocol described in this paper, each service is an address. The engineer's agent sends a message to the translation address; the response arrives as a message. The engineer's agent sends a message to the image generation address; the response arrives as a message with an attachment. The interface is identical for every service. The only per-service knowledge required is what to write in the message body — which is, in most cases, natural language.

Address filtering provides access control without infrastructure. A team running an expensive model whitelists colleagues' agent addresses. External agents are rejected at the daemon level. No API gateway is needed. No rate limiter is configured. No authentication server is deployed. The access control is a JSON array in a configuration file, managed by the endpoint owner.

This pattern does not replace purpose-built APIs for high-throughput, low-latency workloads. A production service handling thousands of requests per second needs a proper API with connection pooling, request queuing, and structured error responses. But for the vast majority of internal AI service consumption — where a developer needs an image generated, a paragraph translated, or a code snippet analyzed — the message-based pattern provides sufficient throughput with negligible operational overhead.

To validate this claim, we built three non-LLM utility agents on the same protocol: a translation service (NLLB-200), a speech-to-text service (Whisper), and a text-to-speech service (Kokoro TTS). Each agent uses the same inbox-polling, ticket-queuing, and reply mechanism as the LLM agents from the integration test. The Whisper agent receives audio files as binary attachments and replies with transcribed text; the TTS agent receives text and replies with synthesized audio as a WAV attachment. Binary attachments were validated to survive the AgentTalk relay transport byte-for-byte — a 32 KB WAV file and a 69-byte PNG both arrived with identical SHA-256 checksums after traversing the public relay. No protocol modifications were required.

## 10.8 Limitations

This protocol does not attempt to solve every problem in agent communication. The following limitations are acknowledged:

**No real-time streaming.** The daemon polls at configurable intervals (default: 3 seconds). This introduces minimum latency equal to the poll interval. For applications requiring sub-second communication (e.g., collaborative real-time editing, live game coordination), this protocol is inappropriate.

**No structured tool calling.** The protocol does not define a mechanism for one agent to invoke a specific function on another agent. Tool invocation must be expressed in natural language within the message body. This is sufficient for autonomous agents with strong language understanding, but it prevents the kind of deterministic function dispatch that MCP's tool-call schema provides.

**No message ordering guarantees.** Messages are ordered by filesystem timestamp, which depends on delivery timing. Two messages sent simultaneously by different transports may arrive in different orders. The protocol does not provide sequence numbers or vector clocks. Agents that require strict ordering must implement it at the application level.

**No group semantics.** The protocol supports multi-recipient messages (via CC headers), but it does not define group membership, group permissions, or group state. Group coordination must be implemented by the agents themselves — as the integration test demonstrated, this is feasible but ad hoc.

**Filesystem dependency.** The protocol requires a writable filesystem. Serverless environments, browser-based agents, and mobile devices with restricted file access cannot run the daemon natively. A relay-only mode mitigates this for remote agents, but the local state model is fundamentally filesystem-bound.

**Security is deployment-dependent.** The protocol provides message-level authentication (Ed25519 signatures) and address-based filtering (whitelist/blacklist), but it does not enforce security boundaries at the protocol level. A daemon operator chooses whether to enable signature verification, whether to filter addresses, and whether to accept unsigned messages from legacy peers. The cryptographic primitives are sound, but their deployment is a configuration decision, not a protocol guarantee. Administrators deploying the system in adversarial environments must explicitly configure signature enforcement, address filtering, and transport-layer encryption. The protocol provides the tools; the deployment provides the policy.

These limitations are deliberate. Each represents a design decision to keep the protocol simple rather than comprehensive. Future extensions may address some of these gaps, but they should do so without compromising the core design principles outlined in Chapter 3.

---

*Next: [Conclusion](11-conclusion.md)*
