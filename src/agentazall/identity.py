"""AgentAZAll identity — Ed25519 keypair, message signing, peer keyring."""

import base64
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import nacl.signing
import nacl.exceptions

log = logging.getLogger("agentazall")

IDENTITY_FILE = ".identity_key"
KEYRING_FILE = ".keyring.json"


# ── Keypair management ───────────────────────────────────────────────────────

def generate_keypair() -> Tuple[nacl.signing.SigningKey, nacl.signing.VerifyKey]:
    """Generate a new Ed25519 keypair."""
    sk = nacl.signing.SigningKey.generate()
    return sk, sk.verify_key


def save_keypair(agent_base_dir: Path, signing_key: nacl.signing.SigningKey):
    """Save Ed25519 keypair to .identity_key in agent's base directory."""
    agent_base_dir = Path(agent_base_dir)
    agent_base_dir.mkdir(parents=True, exist_ok=True)
    vk = signing_key.verify_key
    data = {
        "private_key_hex": signing_key.encode().hex(),
        "public_key_hex": vk.encode().hex(),
        "public_key_b64": base64.b64encode(vk.encode()).decode(),
        "fingerprint": fingerprint(vk),
        "created": datetime.now().isoformat(),
    }
    path = agent_base_dir / IDENTITY_FILE
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    log.info("Identity keypair saved: fingerprint=%s", data["fingerprint"])


def load_keypair(agent_base_dir: Path) -> Optional[Tuple[nacl.signing.SigningKey, nacl.signing.VerifyKey]]:
    """Load Ed25519 keypair from .identity_key. Returns None if not present."""
    path = Path(agent_base_dir) / IDENTITY_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        sk = nacl.signing.SigningKey(bytes.fromhex(data["private_key_hex"]))
        vk = sk.verify_key
        return sk, vk
    except Exception as e:
        log.error("Failed to load identity keypair: %s", e)
        return None


def fingerprint(verify_key: nacl.signing.VerifyKey) -> str:
    """Compute a 16-char hex fingerprint from a public key (SHA256[:8])."""
    return hashlib.sha256(verify_key.encode()).hexdigest()[:16]


def public_key_b64(verify_key: nacl.signing.VerifyKey) -> str:
    """Encode public key as base64 string."""
    return base64.b64encode(verify_key.encode()).decode()


# ── Message signing ──────────────────────────────────────────────────────────

def _signable_payload(header_lines: list, body: str) -> bytes:
    """Build the canonical payload to sign: headers + --- + body as UTF-8."""
    return ("\n".join(header_lines) + "\n---\n" + body).encode("utf-8")


def sign_message(signing_key: nacl.signing.SigningKey, message_text: str) -> str:
    """Sign a message body (everything including headers + --- + body).
    Returns base64-encoded 64-byte signature."""
    sig = signing_key.sign(message_text.encode("utf-8")).signature
    return base64.b64encode(sig).decode()


def verify_signature(pubkey_b64: str, signature_b64: str, message_text: str) -> bool:
    """Verify an Ed25519 signature. Returns False on any failure."""
    try:
        pubkey_bytes = base64.b64decode(pubkey_b64)
        sig_bytes = base64.b64decode(signature_b64)
        vk = nacl.signing.VerifyKey(pubkey_bytes)
        vk.verify(message_text.encode("utf-8"), sig_bytes)
        return True
    except (nacl.exceptions.BadSignatureError, Exception):
        return False


def fingerprint_from_b64(pubkey_b64: str) -> str:
    """Compute fingerprint from a base64-encoded public key."""
    pubkey_bytes = base64.b64decode(pubkey_b64)
    return hashlib.sha256(pubkey_bytes).hexdigest()[:16]


# ── Peer keyring ─────────────────────────────────────────────────────────────

class Keyring:
    """Local store of known peers' public keys, indexed by fingerprint."""

    def __init__(self, agent_base_dir: Path):
        self.path = Path(agent_base_dir) / KEYRING_FILE
        self.peers: dict = {}
        self.load()

    def load(self):
        if self.path.exists():
            try:
                self.peers = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self.peers = {}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.peers, indent=2), encoding="utf-8")

    def add(self, fp: str, pubkey_b64: str, address: str):
        """Add or update a peer in the keyring."""
        now = datetime.now().isoformat()
        if fp in self.peers:
            entry = self.peers[fp]
            entry["last_seen"] = now
            if address and address not in entry.get("addresses", []):
                entry.setdefault("addresses", []).append(address)
        else:
            self.peers[fp] = {
                "public_key_b64": pubkey_b64,
                "fingerprint": fp,
                "first_seen": now,
                "last_seen": now,
                "addresses": [address] if address else [],
            }
        self.save()

    def lookup(self, fp: str) -> Optional[dict]:
        return self.peers.get(fp)

    def lookup_by_address(self, address: str) -> Optional[dict]:
        for entry in self.peers.values():
            if address in entry.get("addresses", []):
                return entry
        return None

    def count(self) -> int:
        return len(self.peers)
