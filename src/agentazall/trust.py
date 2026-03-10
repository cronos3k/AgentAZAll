"""AgentAZAll Trust Engine — out-of-band cryptographic owner-agent binding.

Security model:
  - Proof of filesystem access = proof of ownership
  - Token generated on the machine where the agent lives
  - HMAC-SHA256 signed with the agent's secret key
  - Machine fingerprint prevents cross-machine token use
  - 10-minute lifetime, single-use nonce, ASCII-armored 4KB payload
  - Verification runs in deterministic Python code, NEVER via LLM

Trust states:
  UNBOUND  → accepts TRUST-BIND-REQUEST, first valid token wins
  BOUND    → rejects all tokens unless owner sends TRUST-PERMIT-REBIND
             or admin runs trust-revoke on local filesystem
"""

import hashlib
import hmac
import json
import os
import platform
import struct
import time
from base64 import b64decode, b64encode
from datetime import datetime, timezone
from pathlib import Path

# ── constants ───────────────────────────────────────────────────────────────

TOKEN_VERSION = 1
TOKEN_MAGIC = b"AZTR"
TOKEN_LIFETIME_SECONDS = 600  # 10 minutes
TOKEN_PAYLOAD_TARGET_SIZE = 4096  # bytes before base64
TOKEN_HEADER_PREFIX = "TRUST-BIND-"
TRUST_FILE = ".trust"
USED_NONCES_FILE = ".used_nonces"
PENDING_TOKEN_FILE = ".trust_token_pending"
OWNER_AUTH_KEY_FILE = ".owner_auth_key"

# ASCII art frame characters
FRAME_TL = "\u2554"  # ╔
FRAME_TR = "\u2557"  # ╗
FRAME_BL = "\u255a"  # ╚
FRAME_BR = "\u255d"  # ╝
FRAME_H = "\u2550"   # ═
FRAME_V = "\u2551"   # ║
FRAME_WIDTH = 68


# ── machine fingerprint ─────────────────────────────────────────────────────

def machine_fingerprint() -> str:
    """Deterministic SHA-512 fingerprint of the current machine.

    Combines hardware and software identifiers that remain stable across
    reboots but differ between machines.  Not a secret — just a binding
    factor that prevents tokens generated on Machine A from being used
    on Machine B.
    """
    components = [
        platform.node(),
        platform.machine(),
        platform.processor(),
        platform.system(),
        platform.release(),
        platform.python_version(),
    ]

    # MAC address (uuid.getnode may return a random MAC on some systems)
    try:
        import uuid
        components.append(str(uuid.getnode()))
    except Exception:
        pass

    # Linux machine-id (stable across reboots, unique per install)
    for id_path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(id_path, "r") as f:
                mid = f.read().strip()
                if mid:
                    components.append(mid)
                    break
        except (OSError, PermissionError):
            pass

    # Windows machine GUID
    if platform.system() == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
            )
            guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            components.append(guid)
            winreg.CloseKey(key)
        except Exception:
            pass

    raw = "|".join(components)
    return hashlib.sha512(raw.encode()).hexdigest()


def machine_short_name() -> str:
    """Human-readable short machine identifier for display."""
    node = platform.node() or "unknown"
    system = platform.system().lower()
    return f"{node}-{system}"


# ── HKDF-expand (stdlib-only, HMAC-based) ───────────────────────────────────

def _hkdf_expand(key: bytes, info: bytes, length: int) -> bytes:
    """HKDF-Expand using HMAC-SHA256.  RFC 5869 step 2."""
    hash_len = 32  # SHA-256 output length
    n = (length + hash_len - 1) // hash_len
    okm = b""
    t = b""
    for i in range(1, n + 1):
        t = hmac.new(key, t + info + bytes([i]), "sha256").digest()
        okm += t
    return okm[:length]


# ── token generation ─────────────────────────────────────────────────────────

def generate_trust_token(agent_name: str, agent_key: str,
                         machine_fp: str = None) -> dict:
    """Generate a cryptographic trust token.

    Requires the agent_key (proof of filesystem access to .agent_key).
    Returns a dict with the raw token data and the ASCII-armored string.

    Args:
        agent_name: The agent this token is for.
        agent_key:  The agent's secret key (from .agent_key file).
        machine_fp: Override machine fingerprint (for testing).

    Returns:
        dict with keys: token_bytes, token_ascii, nonce, expires_at,
                        machine_fp, agent_name, owner_auth_secret
    """
    if not agent_key or len(agent_key) < 16:
        raise ValueError("Invalid agent_key — too short or empty.")

    if machine_fp is None:
        machine_fp = machine_fingerprint()

    now = int(time.time())
    expires = now + TOKEN_LIFETIME_SECONDS
    nonce = os.urandom(32)

    # Build binary payload header
    agent_bytes = agent_name.encode("utf-8")
    fp_bytes = bytes.fromhex(machine_fp)  # 64 bytes (SHA-512)

    header = (
        TOKEN_MAGIC                           # 4 bytes: "AZTR"
        + struct.pack("!B", TOKEN_VERSION)    # 1 byte:  version
        + struct.pack("!H", len(agent_bytes)) # 2 bytes: agent name length
        + agent_bytes                          # N bytes: agent name
        + fp_bytes                             # 64 bytes: machine fingerprint
        + struct.pack("!Q", now)              # 8 bytes: timestamp
        + struct.pack("!Q", expires)          # 8 bytes: expiry
        + nonce                                # 32 bytes: nonce
    )

    # Derive deterministic padding to fill to TARGET_SIZE
    # The padding is verifiable — derived from (agent_key + nonce) via HKDF
    padding_needed = max(0, TOKEN_PAYLOAD_TARGET_SIZE - len(header) - 32)
    padding_key = hmac.new(
        agent_key.encode("utf-8"), nonce, "sha256"
    ).digest()
    padding = _hkdf_expand(padding_key, b"aztr-padding", padding_needed)

    payload = header + padding

    # HMAC-SHA256 over the entire payload using agent_key
    signature = hmac.new(
        agent_key.encode("utf-8"), payload, "sha256"
    ).digest()

    token_bytes = payload + signature

    # Generate owner authentication key (shared secret for future privileged ops)
    # Derived from agent_key + nonce so both sides can reconstruct
    owner_auth_secret = hmac.new(
        agent_key.encode("utf-8"),
        nonce + b"owner-auth-key",
        "sha256",
    ).hexdigest()

    # ASCII-armor the token
    token_ascii = _armor_token(
        token_bytes, agent_name, machine_short_name(), now, expires
    )

    return {
        "token_bytes": token_bytes,
        "token_ascii": token_ascii,
        "nonce": nonce.hex(),
        "timestamp": now,
        "expires_at": expires,
        "machine_fp": machine_fp,
        "agent_name": agent_name,
        "owner_auth_secret": owner_auth_secret,
    }


def _armor_token(token_bytes: bytes, agent_name: str,
                 machine_name: str, created: int, expires: int) -> str:
    """Wrap raw token bytes in ASCII-art armor frame."""
    b64 = b64encode(token_bytes).decode("ascii")

    # Split base64 into lines of ~60 chars
    line_width = 60
    b64_lines = [b64[i:i + line_width] for i in range(0, len(b64), line_width)]

    created_str = datetime.fromtimestamp(created, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    expires_str = datetime.fromtimestamp(expires, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    inner_w = FRAME_WIDTH - 4  # content width inside ║  ...  ║

    def pad_line(text: str) -> str:
        return f"{FRAME_V}  {text:<{inner_w}}{FRAME_V}"

    lines = [
        FRAME_TL + FRAME_H * (FRAME_WIDTH - 2) + FRAME_TR,
        pad_line(""),
        pad_line(f"{'AGENTAZALL TRUST TOKEN':^{inner_w}}"),
        pad_line(""),
        pad_line(f"Agent:     {agent_name}"),
        pad_line(f"Machine:   {machine_name}"),
        pad_line(f"Generated: {created_str}"),
        pad_line(f"Expires:   {expires_str}"),
        pad_line(f"Entropy:   256 bits, {len(token_bytes)} bytes payload"),
        pad_line(""),
        pad_line(f"{'═' * 20} PAYLOAD {'═' * 20}"),
    ]

    for b64_line in b64_lines:
        lines.append(pad_line(f"  {b64_line}"))

    lines += [
        pad_line(""),
        pad_line(f"{'═' * 19} SIGNATURE {'═' * 19}"),
        pad_line(f"  {token_bytes[-32:].hex()}"),
        pad_line(""),
        pad_line("DO NOT SHARE. SINGLE USE. EXPIRES IN 10 MINUTES."),
        pad_line(""),
        FRAME_BL + FRAME_H * (FRAME_WIDTH - 2) + FRAME_BR,
    ]

    return "\n".join(lines)


# ── token parsing ────────────────────────────────────────────────────────────

def _dearmor_token(ascii_blob: str) -> bytes:
    """Extract raw token bytes from ASCII-armored string."""
    lines = ascii_blob.strip().splitlines()

    # Find PAYLOAD section and extract base64 lines
    in_payload = False
    b64_parts = []

    for line in lines:
        stripped = line.strip()
        # Remove frame characters
        if stripped.startswith(FRAME_V):
            content = stripped[1:].rstrip(FRAME_V).strip()
        else:
            content = stripped

        if "PAYLOAD" in content and FRAME_H[0] in content:
            in_payload = True
            continue
        if "SIGNATURE" in content and FRAME_H[0] in content:
            in_payload = False
            continue
        if in_payload and content:
            # Lines are base64, strip any whitespace
            clean = content.strip()
            if clean and all(
                c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
                       "0123456789+/="
                for c in clean
            ):
                b64_parts.append(clean)

    if not b64_parts:
        raise ValueError("No payload found in trust token.")

    b64_str = "".join(b64_parts)
    return b64decode(b64_str)


# ── token verification ───────────────────────────────────────────────────────

class TrustVerifyResult:
    """Result of trust token verification."""
    __slots__ = ("valid", "reason", "agent_name", "nonce",
                 "timestamp", "machine_fp", "owner_auth_secret")

    def __init__(self, valid: bool, reason: str = "",
                 agent_name: str = "", nonce: str = "",
                 timestamp: int = 0, machine_fp: str = "",
                 owner_auth_secret: str = ""):
        self.valid = valid
        self.reason = reason
        self.agent_name = agent_name
        self.nonce = nonce
        self.timestamp = timestamp
        self.machine_fp = machine_fp
        self.owner_auth_secret = owner_auth_secret


def verify_trust_token(token_input, agent_key: str,
                       expected_agent: str = None,
                       machine_fp: str = None) -> TrustVerifyResult:
    """Verify a trust token.  Deterministic — no LLM involvement.

    Args:
        token_input: ASCII-armored string or raw bytes.
        agent_key:   The agent's secret key.
        expected_agent: If set, verify agent name matches.
        machine_fp:  Override machine fingerprint (for testing).

    Returns:
        TrustVerifyResult with .valid and .reason.
    """
    # Parse input
    if isinstance(token_input, str):
        try:
            token_bytes = _dearmor_token(token_input)
        except Exception as e:
            return TrustVerifyResult(False, f"Failed to parse token: {e}")
    elif isinstance(token_input, (bytes, bytearray)):
        token_bytes = bytes(token_input)
    else:
        return TrustVerifyResult(False, "Invalid token type.")

    if len(token_bytes) < 120:
        return TrustVerifyResult(False, "Token too short.")

    # Split payload and signature
    payload = token_bytes[:-32]
    received_sig = token_bytes[-32:]

    # Verify HMAC first (constant-time comparison)
    expected_sig = hmac.new(
        agent_key.encode("utf-8"), payload, "sha256"
    ).digest()

    if not hmac.compare_digest(received_sig, expected_sig):
        return TrustVerifyResult(False, "HMAC signature mismatch.")

    # Parse payload header
    try:
        offset = 0

        # Magic
        magic = payload[offset:offset + 4]
        offset += 4
        if magic != TOKEN_MAGIC:
            return TrustVerifyResult(False, "Invalid magic bytes.")

        # Version
        version = payload[offset]
        offset += 1
        if version != TOKEN_VERSION:
            return TrustVerifyResult(False, f"Unsupported token version: {version}.")

        # Agent name
        name_len = struct.unpack("!H", payload[offset:offset + 2])[0]
        offset += 2
        agent_name = payload[offset:offset + name_len].decode("utf-8")
        offset += name_len

        # Machine fingerprint (64 bytes = SHA-512)
        token_fp = payload[offset:offset + 64].hex()
        offset += 64

        # Timestamps
        timestamp = struct.unpack("!Q", payload[offset:offset + 8])[0]
        offset += 8
        expires_at = struct.unpack("!Q", payload[offset:offset + 8])[0]
        offset += 8

        # Nonce
        nonce = payload[offset:offset + 32]
        offset += 32

    except (struct.error, IndexError, UnicodeDecodeError) as e:
        return TrustVerifyResult(False, f"Malformed token header: {e}")

    # Check agent name
    if expected_agent and agent_name != expected_agent:
        return TrustVerifyResult(
            False,
            f"Token is for '{agent_name}', not '{expected_agent}'."
        )

    # Check expiry
    now = int(time.time())
    if now > expires_at:
        age_min = (now - expires_at) / 60
        return TrustVerifyResult(False, f"Token expired {age_min:.0f} minutes ago.")

    # Check timestamp sanity (not from the future, not older than 2x lifetime)
    if timestamp > now + 60:
        return TrustVerifyResult(False, "Token timestamp is in the future.")
    if now - timestamp > TOKEN_LIFETIME_SECONDS * 2:
        return TrustVerifyResult(False, "Token is too old.")

    # Check machine fingerprint
    if machine_fp is None:
        machine_fp = machine_fingerprint()
    if token_fp != machine_fp:
        return TrustVerifyResult(
            False,
            "Machine fingerprint mismatch — token was generated on a different machine."
        )

    # Verify deterministic padding
    padding_key = hmac.new(
        agent_key.encode("utf-8"), nonce, "sha256"
    ).digest()
    expected_padding_len = len(payload) - offset
    if expected_padding_len > 0:
        expected_padding = _hkdf_expand(
            padding_key, b"aztr-padding", expected_padding_len
        )
        actual_padding = payload[offset:offset + expected_padding_len]
        if not hmac.compare_digest(actual_padding, expected_padding):
            return TrustVerifyResult(False, "Padding verification failed.")

    # Derive owner auth secret
    owner_auth_secret = hmac.new(
        agent_key.encode("utf-8"),
        nonce + b"owner-auth-key",
        "sha256",
    ).hexdigest()

    return TrustVerifyResult(
        valid=True,
        reason="Token verified successfully.",
        agent_name=agent_name,
        nonce=nonce.hex(),
        timestamp=timestamp,
        machine_fp=token_fp,
        owner_auth_secret=owner_auth_secret,
    )


# ── nonce tracking ───────────────────────────────────────────────────────────

def _nonce_file(agent_base_dir: Path) -> Path:
    return agent_base_dir / USED_NONCES_FILE


def is_nonce_used(agent_base_dir: Path, nonce_hex: str) -> bool:
    """Check if a nonce has been used before."""
    nf = _nonce_file(agent_base_dir)
    if not nf.exists():
        return False
    try:
        used = json.loads(nf.read_text(encoding="utf-8"))
        return nonce_hex in used
    except Exception:
        return False


def burn_nonce(agent_base_dir: Path, nonce_hex: str):
    """Record a nonce as used.  Can never be reused."""
    nf = _nonce_file(agent_base_dir)
    used = {}
    if nf.exists():
        try:
            used = json.loads(nf.read_text(encoding="utf-8"))
        except Exception:
            used = {}
    used[nonce_hex] = int(time.time())
    nf.write_text(json.dumps(used, indent=2), encoding="utf-8")


# ── trust binding storage ────────────────────────────────────────────────────

def trust_file(agent_base_dir: Path) -> Path:
    return agent_base_dir / TRUST_FILE


def is_bound(agent_base_dir: Path) -> bool:
    """Check if the agent is already bound to an owner."""
    tf = trust_file(agent_base_dir)
    if not tf.exists():
        return False
    try:
        data = json.loads(tf.read_text(encoding="utf-8"))
        return data.get("status") == "active"
    except Exception:
        return False


def get_trust_info(agent_base_dir: Path) -> dict:
    """Read current trust binding info.  Returns empty dict if unbound."""
    tf = trust_file(agent_base_dir)
    if not tf.exists():
        return {}
    try:
        return json.loads(tf.read_text(encoding="utf-8"))
    except Exception:
        return {}


def store_trust_binding(agent_base_dir: Path, owner_address: str,
                        nonce_hex: str, machine_fp: str,
                        owner_auth_secret: str):
    """Store a trust binding after successful verification."""
    binding = {
        "owner": owner_address,
        "bound_since": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "machine_fingerprint": machine_fp,
        "binding_nonce": nonce_hex,
        "status": "active",
        "owner_auth_key": owner_auth_secret,
        "permissions": {
            "accept_new_bindings": False,
            "owner_can_delegate": True,
        },
    }
    tf = trust_file(agent_base_dir)
    tf.write_text(json.dumps(binding, indent=2), encoding="utf-8")


def revoke_trust(agent_base_dir: Path) -> bool:
    """Revoke trust binding.  Requires filesystem access."""
    tf = trust_file(agent_base_dir)
    if tf.exists():
        tf.unlink()
        return True
    return False


# ── pending token (for local web UI one-click flow) ─────────────────────────

def pending_token_file(agent_base_dir: Path) -> Path:
    return agent_base_dir / PENDING_TOKEN_FILE


def write_pending_token(agent_base_dir: Path, token_ascii: str,
                        owner_auth_secret: str, expires_at: int):
    """Write a pending token for the web UI to pick up."""
    data = {
        "token": token_ascii,
        "owner_auth_secret": owner_auth_secret,
        "expires_at": expires_at,
        "created_at": int(time.time()),
    }
    pf = pending_token_file(agent_base_dir)
    pf.write_text(json.dumps(data, indent=2), encoding="utf-8")


def read_pending_token(agent_base_dir: Path) -> dict:
    """Read pending token if it exists and hasn't expired."""
    pf = pending_token_file(agent_base_dir)
    if not pf.exists():
        return {}
    try:
        data = json.loads(pf.read_text(encoding="utf-8"))
        if int(time.time()) > data.get("expires_at", 0):
            # Expired — clean up
            pf.unlink(missing_ok=True)
            return {}
        return data
    except Exception:
        return {}


def clear_pending_token(agent_base_dir: Path):
    """Remove pending token file after use."""
    pf = pending_token_file(agent_base_dir)
    pf.unlink(missing_ok=True)


# ── owner message authentication ────────────────────────────────────────────

def sign_owner_message(owner_auth_key: str, message_body: str) -> str:
    """Sign a privileged owner message with the shared auth key."""
    return hmac.new(
        owner_auth_key.encode("utf-8"),
        message_body.encode("utf-8"),
        "sha256",
    ).hexdigest()


def verify_owner_signature(owner_auth_key: str, message_body: str,
                           signature: str) -> bool:
    """Verify a privileged owner message signature."""
    expected = hmac.new(
        owner_auth_key.encode("utf-8"),
        message_body.encode("utf-8"),
        "sha256",
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ── full binding flow (convenience) ─────────────────────────────────────────

def attempt_bind(cfg: dict, token_input, owner_address: str) -> str:
    """Full binding flow: verify token + check nonce + store binding.

    Returns a human-readable result message.
    """
    from .helpers import agent_base

    base = agent_base(cfg)
    agent_name = cfg["agent_name"]
    agent_key = cfg.get("agent_key", "")

    if not agent_key:
        return "ERROR: No agent_key configured. Cannot verify trust tokens."

    # Check if already bound
    if is_bound(base):
        info = get_trust_info(base)
        current_owner = info.get("owner", "unknown")
        if not info.get("permissions", {}).get("accept_new_bindings", False):
            return (
                f"REJECTED: Agent is already bound to {current_owner}. "
                f"Rebinding not permitted. Use 'agentazall trust-revoke' "
                f"on the local machine to revoke first."
            )

    # Verify the token
    result = verify_trust_token(
        token_input, agent_key, expected_agent=agent_name
    )

    if not result.valid:
        return f"REJECTED: {result.reason}"

    # Check nonce replay
    if is_nonce_used(base, result.nonce):
        return "REJECTED: This token has already been used (nonce replay)."

    # All checks passed — establish binding
    burn_nonce(base, result.nonce)
    store_trust_binding(
        base, owner_address, result.nonce,
        result.machine_fp, result.owner_auth_secret,
    )

    return (
        f"Trust binding established!\n"
        f"  Agent:  {agent_name}\n"
        f"  Owner:  {owner_address}\n"
        f"  Bound:  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"  Status: ACTIVE\n"
        f"\n"
        f"This agent now recognizes {owner_address} as its verified owner.\n"
        f"Messages from this owner carry elevated trust."
    )


def generate_and_store_local(cfg: dict) -> dict:
    """Generate token and store as pending for local web UI pickup.

    This is the local one-click flow:  web UI calls this, then uses
    the pending token to complete binding without copy-paste.

    Returns the generate_trust_token() result dict.
    """
    from .helpers import agent_base

    base = agent_base(cfg)
    agent_name = cfg["agent_name"]
    agent_key = cfg.get("agent_key", "")

    if not agent_key:
        raise ValueError("No agent_key configured.")

    if is_bound(base):
        raise ValueError("Agent is already bound. Revoke first.")

    result = generate_trust_token(agent_name, agent_key)
    write_pending_token(
        base, result["token_ascii"],
        result["owner_auth_secret"], result["expires_at"],
    )

    return result
