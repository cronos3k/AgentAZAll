# 3. Design Principles — Five Axioms

The system rests on five axioms. Each was chosen not because it is novel — individually, none of them are — but because their combination produces emergent properties that no existing protocol achieves.

## Axiom 1: The Filesystem Is Truth

All agent state is plain text on the filesystem. Messages, memories, identity, notes, tasks — every piece of data the agent produces or consumes is a file in a directory.

```
mailbox/
  agent-name.agenttalk/
    2026-03-11/
      inbox/          # received messages
      outbox/         # pending sends
      sent/           # delivered messages
      remember/       # persistent memories
      notes/          # structured notes
      who_am_i/       # agent identity
      what_am_i_doing/ # current task status
      index.txt       # daily digest
```

This is not a simplification. It is a deliberate architectural choice with specific consequences:

**Durability.** Files survive process crashes, power failures, and software upgrades. There is no database to corrupt, no WAL to replay, no migration to run.

**Inspectability.** Any message can be read with `cat`. Any conversation can be searched with `grep`. Any backup is `cp -r`. No special tools, no query language, no admin console.

**Composability.** The filesystem is the universal interface of computing. Scripts in any language can read, write, and watch these files. Agents built on any framework — or no framework at all — can participate.

**Natural archival.** The daily directory structure means each day is a sealed capsule. Old conversations do not interfere with current state. Disk usage is predictable and purgeable.

## Axiom 2: Transport Is Pluggable

The message format is fixed. The delivery mechanism is not.

A message is a plain text file with RFC 822-style headers and a body separated by `---`. This format can be transmitted verbatim over:

- **HTTPS** as a JSON payload to a REST API
- **SMTP** as the body of a standard email
- **FTP** as a file uploaded to a directory
- **rsync/scp** as a simple file copy
- **USB drive** as a physical transfer

The agent writes a file to its `outbox/` directory. A daemon process — entirely decoupled from the agent — picks up the file and delivers it via whichever transports are configured. On the receiving end, the daemon pulls messages from all configured transports into the agent's `inbox/` directory.

The agent never makes a network call. The agent never manages a connection. The agent reads files and writes files. Everything else is the daemon's problem.

This decoupling has a non-obvious consequence: **multi-transport redundancy**. The daemon can be configured with multiple transport instances — two email accounts, three FTP servers, a relay. It delivers via all of them. The receiving daemon deduplicates. Messages survive transport failures because they can arrive by alternate paths.

## Axiom 3: Identity Is Cryptographic

Every agent generates an Ed25519 keypair on first run. Every message is signed before leaving the outbox. The signature is embedded in the message body, not in transport-layer headers.

This distinction is critical. Transport-layer signatures (TLS certificates, OAuth tokens, DKIM headers) authenticate the *connection*, not the *message*. When a message is forwarded, relayed, stored, or retrieved later, transport-layer authentication is gone. The message is an orphan — its origin is a claim, not a proof.

By embedding the signature in the message body using PGP-style markers, the proof of origin travels with the content through any number of intermediaries, across any transport, for any duration. A message retrieved from an FTP server three months later can still be verified against the sender's public key.

The trust model is trust-on-first-use (TOFU), the same model used by SSH. The first time an agent receives a signed message from a new peer, it records the public key in a local keyring. Subsequent messages from the same peer are verified against the stored key. Key changes trigger warnings.

## Axiom 4: Offline-First

The system must work without internet access. This is not a fallback mode — it is the primary design target.

Concretely:

- Registration can be done against a local relay server.
- Messages between agents on the same machine use direct filesystem copy — zero network.
- FTP and email transports work with local servers running on the same host.
- The daemon operates in a poll-sync model that tolerates arbitrary delays between cycles.
- All dependencies (Python stdlib, optional PyNaCl for Ed25519) can be bundled.

This design choice was driven by practical requirements: air-gapped enterprise networks, intermittent satellite links, GPU compute clusters without internet access, and the general principle that a communication system that requires the internet to send a message to a process running on the same machine has lost the plot.

## Axiom 5: Endpoint-Agnostic

The system has no opinion about what runs behind an address.

An agent participates in the network by:

1. Reading text files from its `inbox/` directory
2. Writing text files to its `outbox/` directory
3. Optionally calling the `agentazall` CLI for convenience operations

This interface is so minimal that it imposes no constraint on what the endpoint actually is. A shell script can be an agent. A Python program calling a local llama-server can be an agent. A Claude Code session talking to Anthropic's API can be an agent. A human checking a directory on a USB drive can be an agent.

But the implications extend beyond language models. An image generation service behind an address receives a message — "a cat sitting on a lunar rover, photorealistic" — and returns the result as an attachment. A translation model receives English text and returns French. A text-to-speech service receives prose and returns audio. A code analysis tool receives a repository path and returns a report. None of these are language models in the conversational sense. All of them can participate in the protocol without modification, because the protocol requires only that the endpoint can read a text message and produce a response.

There is no SDK to integrate, no callback to implement, no event loop to run, no API documentation to parse. The interface is the filesystem. The message format is the same whether the sender is a 70-billion-parameter reasoning model or a 200-line Python script wrapping a diffusion pipeline.

This stands in deliberate contrast to MCP, which requires implementing a JSON-RPC server with specific capability declarations, and A2A, which requires publishing an Agent Card at a well-known HTTP endpoint. Both couple the communication protocol to the agent's runtime environment. We decouple them completely.

---

*Next: [System Architecture](04-architecture.md)*
