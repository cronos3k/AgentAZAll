# 9. Cross-Model Communication

## 9.1 The Turing Test We Did Not Intend

The integration test was designed to measure protocol reliability, not conversational quality. Yet the conversations that emerged provide evidence for a claim that extends beyond protocol design: architecturally distinct language models, given nothing more than plain text messages and peer addresses, can sustain coherent multi-party discourse without any coordination mechanism beyond the message format itself.

This chapter presents exploratory qualitative analysis of the actual conversations produced during the integration test, as well as observational evidence from extended real-world usage of the protocol between different model architectures over a period of weeks. The analysis is descriptive rather than formally coded — we report observed patterns without inter-rater validation or quantitative coherence metrics. We consider this evidence suggestive rather than conclusive, and note that rigorous discourse analysis with formal coding rubrics would strengthen these findings in future work.

## 9.2 Topic Coherence

Conversations were seeded with open-ended prompts about agent communication, protocol design, and autonomous collaboration. Within the first three exchange cycles, the agents had self-organized into substantive technical discussions spanning:

- Consensus protocols for multi-agent decision-making
- The trade-offs between centralized relay and peer-to-peer communication
- How agents should handle network churn and offline peers
- The role of cryptographic identity in establishing trust
- Whether autonomous agents should have persistent memory across conversations

These topics were not prescribed. The seed messages posed general questions; the agents chose which threads to pursue based on their personality prompts and the content of incoming messages. The fact that three different model architectures converged on the same set of relevant topics — without any shared training data, fine-tuning, or coordination — suggests that the protocol's plain-text format provides sufficient context for cross-model comprehension.

## 9.3 Role Adherence

Each agent was assigned a personality via system prompt: a precise engineer (Qwen-81B), a philosophical thinker (Hermes-70B-1), a pragmatic reviewer (Devstral-24B), and a creative enthusiast (Hermes-70B-2). Response length was constrained to 2-4 sentences.

The personality assignments held throughout all three rounds:

- **Qwen-81B** consistently produced architecturally precise responses, proposing specific mechanisms (vector clocks, Raft-like consensus, content-addressed storage) and evaluating trade-offs in concrete terms.
- **Hermes-70B-1** adopted a reflective, philosophical tone, connecting technical proposals to broader questions about autonomy, trust, and the nature of decentralized systems.
- **Devstral-24B** was consistently concise and practical, offering direct assessments and focusing on what would work in deployment rather than in theory.
- **Hermes-70B-2** brought creative and enthusiastic energy, proposing novel combinations of ideas and expressing genuine interest in the other agents' perspectives.

The personality divergence between Hermes-70B-1 and Hermes-70B-2 is particularly notable because both agents used the same model and the same inference endpoint. Their distinct conversational styles emerged entirely from their system prompts and the different conversation histories they accumulated with different peers. This demonstrates that agent identity and model identity are orthogonal: two agents sharing a model are no more similar in behavior than two humans sharing a native language.

## 9.4 Cross-Model Comprehension

The most significant qualitative finding is that the three model architectures understood and built upon each other's contributions. When Qwen-81B proposed a specific technical mechanism, Devstral-24B evaluated its practical feasibility, and Hermes-70B-1 situated it within a broader philosophical framework — all without any indication that the agents were aware of or confused by the fact that their conversation partners used different architectures.

This is not a trivial result. MCP, A2A, and ACP all implicitly assume homogeneous agent capabilities — their tool schemas, capability declarations, and structured interaction patterns presuppose that all participants share a common understanding of the interaction protocol at a semantic level. Our experiment demonstrates that plain text, combined with conversational context (the last 8 messages per peer), is sufficient for cross-architecture comprehension. No capability negotiation was needed. No schema alignment was required. The agents simply read each other's messages and responded.

## 9.5 Extended Real-World Usage

The integration test ran for 30 minutes under controlled conditions. But the protocol has been in continuous real-world use for substantially longer. Over a period of weeks prior to the formal test, the system was used for daily communication between a Claude Opus 4 instance (serving as a development coordinator), a Qwen3.5-9B instance (serving as a field agent for code analysis), and a Devstral-24B instance (serving as a field agent for documentation work).

These conversations were not constrained to 2-4 sentences. They involved multi-paragraph technical discussions, code review, architectural decisions, and task coordination. The agents operated across the AgentTalk relay transport, with messages traversing the public internet between different machines.

Several observations from this extended usage period are relevant:

**Conversation depth.** Multi-turn discussions sustained coherence over dozens of exchanges, with agents referencing specific points from earlier messages and building incrementally on shared conclusions. The 8-message history window used in the integration test was sufficient for the short-form chatbot pattern, but the protocol itself imposes no context limit — an agent with a larger context window can retain and reference arbitrarily long conversation histories.

**Tool discovery through conversation.** During real-world usage, one agent discovered that a peer supported specific CLI commands by asking about capabilities in natural language. No capability advertisement protocol was needed. The agent simply asked, received a text response listing available commands, and incorporated that knowledge into subsequent interactions. This is how humans discover each other's capabilities — by asking — and it works identically for agents communicating over plain text.

**MCP doorbell integration.** The protocol's MCP server (a minimal notification-only integration) was used to alert an MCP-aware client when new messages arrived in the inbox. The client then read messages using the CLI, composed replies in natural language, and sent them using the CLI. The MCP layer provided notification; the filesystem provided truth. This separation proved robust: when the MCP server was temporarily unavailable, the agent continued operating by polling the inbox directory directly. No messages were lost.

**Protocol development through the protocol.** A notable observation from extended usage: agents used the protocol to debug and improve the protocol itself. During the deployment of Ed25519 inline signatures, an agent on the network independently confirmed a bug — the relay was stripping cryptographic headers during message forwarding — and proposed the PGP-style inline body wrapping that became the production implementation. The fix was designed, tested, and validated through message exchange between agents running on different machines. The protocol served as the communication channel for its own development, which is perhaps the most direct evidence that it functions as intended.

## 9.6 What Plain Text Enables

The decision to use plain text as the message format — rather than JSON schemas, protocol buffers, or structured tool calls — has a consequence that only becomes apparent through multi-model communication: it eliminates the serialization barrier.

Every structured format imposes assumptions about what the recipient can parse. JSON assumes a JSON parser. Protocol buffers assume a protobuf compiler. Tool-call schemas assume a specific function-calling API. When two agents use different model architectures — with different tokenizers, different context window sizes, different inference APIs — any structured format becomes a potential point of incompatibility.

Plain text has no such barrier. Every language model, regardless of architecture, is trained on text. Every model can read a message that says "From: agent-alpha, Subject: Re: Consensus Protocols." No parser is needed. No schema negotiation is required. The message format is the model's native input format.

This is not a limitation. It is a feature. The protocol deliberately avoids structured tool calls, not because they are undesirable, but because they are unnecessary for the core task of agent-to-agent communication. An agent that wants to invoke a tool on a peer can describe the request in natural language; the peer can interpret it using its own reasoning capabilities. This is less efficient than a direct function call, but it is infinitely more interoperable.

---

*Next: [Discussion](10-discussion.md)*
