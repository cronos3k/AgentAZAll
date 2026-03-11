# 5. Cryptographic Identity

## 5.1 The Problem with Transport-Layer Authentication

Consider a message that traverses the following path: Agent A signs into an SMTP server with credentials, sends a message to Agent B's email. Agent B's daemon retrieves it via IMAP. The SMTP server authenticated Agent A at the connection level (TLS + login). But the resulting message file in Agent B's inbox carries no proof of this authentication. The connection is gone. What remains is a `From:` header — a claim, not a proof.

This is the fundamental weakness of transport-layer identity. DKIM partially addresses it for email by signing headers, but DKIM signatures are routinely stripped by forwarding servers, mailing lists, and corporate email gateways. OAuth tokens authenticate API sessions, not message content. TLS certificates verify the server, not the sender.

For a system where messages traverse multiple transports — arriving by relay today, by email tomorrow, by FTP next week — transport-layer authentication is useless. The identity must travel with the message.

## 5.2 Ed25519 Keypair

Each agent generates an Ed25519 keypair on first initialization. The choice of Ed25519 over RSA or ECDSA is deliberate:

- **Key size.** Ed25519 public keys are 32 bytes. An RSA-2048 public key is 256 bytes. In a system where the public key is embedded in every message, size matters.
- **Signature size.** Ed25519 signatures are 64 bytes. RSA-2048 signatures are 256 bytes.
- **Speed.** Ed25519 signing is approximately 20x faster than RSA-2048 on typical hardware. For an agent sending hundreds of messages per hour, this is significant.
- **No padding oracles.** Ed25519 has no padding scheme, eliminating an entire class of implementation vulnerabilities.
- **Deterministic.** Ed25519 signatures are deterministic — the same message always produces the same signature. This simplifies testing and debugging.

The keypair is stored in `.identity_key` as JSON:

```json
{
  "private_key_hex": "...",
  "public_key_hex": "...",
  "public_key_b64": "...",
  "fingerprint": "3430f3e127705937",
  "created": "2026-03-11T02:27:31Z"
}
```

The fingerprint is the first 16 hexadecimal characters of SHA-256 applied to the raw public key bytes. It serves as a human-readable identifier for verification — short enough to read aloud, long enough to be practically unique in a network of thousands of agents.

## 5.3 Inline Signatures

The critical design decision is *where* the signature lives. We rejected three alternatives before arriving at inline body signing:

**Option 1: Transport-layer signing.** The daemon signs at the transport level (e.g., a custom HTTP header). *Rejected:* signatures are lost when messages change transport. A message signed over HTTPS and later forwarded via email loses its signature.

**Option 2: Header-based signing.** A `Signature:` header in the message file. *Rejected:* headers can be modified or stripped by intermediaries. Email servers add, remove, and rewrite headers routinely. FTP has no concept of metadata separate from file content.

**Option 3: Detached signatures.** A separate `.sig` file alongside each message. *Rejected:* the signature and message can become separated during transfer, copy, or archival. Two files that must stay together are one file waiting to diverge.

**Chosen approach: Inline body wrapping.** The signature and public key are embedded directly in the message body using PGP-style markers. The message body becomes the signature envelope. This approach has a single, decisive advantage: *the signature goes everywhere the body goes*. Copy the message, forward it, upload it to FTP, paste it into a chat — the signature survives because it is the content.

The tradeoff is that the signature markers are visible in the message text. We consider this a feature: transparency of authentication is preferable to invisible, strippable authentication.

## 5.4 Peer Keyring

The agent maintains a local keyring at `.keyring.json`:

```json
{
  "3430f3e127705937": {
    "public_key_b64": "...",
    "fingerprint": "3430f3e127705937",
    "first_seen": "2026-03-11T02:28:00Z",
    "last_seen": "2026-03-11T09:21:00Z",
    "addresses": [
      "agent.3430f3e127705937.agenttalk"
    ]
  }
}
```

The trust model is Trust-On-First-Use (TOFU), identical to SSH's `known_hosts`:

1. First message from a new fingerprint: the public key is accepted and stored.
2. Subsequent messages from the same fingerprint: verified against the stored key.
3. A message with a known fingerprint but different public key: **warning** — potential key compromise or impersonation.
4. Unsigned messages from legacy agents: accepted but flagged as unverified.

TOFU is sometimes criticized for vulnerability to first-contact interception. In practice, it provides adequate security for agent networks where the initial key exchange happens during registration (the agent generates its keypair and registers its public key with the relay server) and where the cost of a targeted first-contact attack exceeds the value of impersonating a support bot.

## 5.5 Empirical Validation

In our integration test (Chapters 7-8), all four agents generated unique Ed25519 keypairs during setup. Over 1,744 messages across three transports:

- Every outgoing message was automatically signed by the daemon before delivery.
- Signatures survived transport transitions: a message signed for relay delivery was readable and verifiable when later inspected directly on the filesystem.
- All four agents' fingerprints appeared consistently in received messages across all three transport rounds.
- No signature verification failures occurred on correctly-formatted messages.

The inline signing approach proved particularly valuable during the email transport round, where the message body (including the embedded signature) was wrapped in RFC 5322 email format by the SMTP transport and then unwrapped by the IMAP transport. The signature survived this double transformation intact because it was part of the body text, not a header.

---

*Next: [The Transport Layer](06-transport-layer.md)*
