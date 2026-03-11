"""AgentAZAll message format — compose & parse plain-text messages."""

from pathlib import Path
from typing import Optional, Tuple

from .helpers import generate_id, now_str

# ── Inline signature markers ────────────────────────────────────────────────
# PGP-style inline signing that survives any transport (relay, email, FTP,
# even copy-paste).  The signature is embedded in the message body itself,
# so relays/mail servers that only forward the body text cannot strip it.

SIG_BEGIN = "---BEGIN AGENTAZALL SIGNED MESSAGE---"
SIG_END = "---END AGENTAZALL SIGNED MESSAGE---"
SIG_BLOCK_BEGIN = "---BEGIN AGENTAZALL SIGNATURE---"
SIG_BLOCK_END = "---END AGENTAZALL SIGNATURE---"


def wrap_signed_body(body: str, signing_key, pk_b64: str, fp: str) -> str:
    """Wrap a message body with inline Ed25519 signature.

    Returns body text with PGP-style signature markers that survive
    any transport.  Signature covers the original body text only.
    """
    from .identity import sign_message
    sig = sign_message(signing_key, body)
    return (
        f"{SIG_BEGIN}\n"
        f"Fingerprint: {fp}\n"
        f"Public-Key: {pk_b64}\n"
        f"\n"
        f"{body}\n"
        f"{SIG_END}\n"
        f"{SIG_BLOCK_BEGIN}\n"
        f"{sig}\n"
        f"{SIG_BLOCK_END}"
    )


def unwrap_signed_body(body: str) -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
    """Extract original body, public key, fingerprint, and signature from inline-signed body.

    Returns (original_body, public_key_b64, fingerprint, signature_b64).
    If the body is not inline-signed, returns (body, None, None, None).
    """
    if SIG_BEGIN not in body:
        return body, None, None, None

    try:
        # Extract content between SIG_BEGIN and SIG_END
        after_begin = body.split(SIG_BEGIN, 1)[1]
        signed_content, after_sig_end = after_begin.split(SIG_END, 1)

        # Parse metadata lines (Fingerprint:, Public-Key:) then blank line then body
        meta_lines = []
        body_lines = []
        in_body = False
        for line in signed_content.strip().split("\n"):
            if not in_body:
                if line.strip() == "":
                    in_body = True
                else:
                    meta_lines.append(line)
            else:
                body_lines.append(line)

        # Parse metadata
        fp = None
        pk_b64 = None
        for ml in meta_lines:
            if ml.startswith("Fingerprint:"):
                fp = ml.split(":", 1)[1].strip()
            elif ml.startswith("Public-Key:"):
                pk_b64 = ml.split(":", 1)[1].strip()

        # Extract signature between SIG_BLOCK_BEGIN and SIG_BLOCK_END
        sig_b64 = None
        if SIG_BLOCK_BEGIN in after_sig_end:
            sig_section = after_sig_end.split(SIG_BLOCK_BEGIN, 1)[1]
            sig_b64 = sig_section.split(SIG_BLOCK_END, 1)[0].strip()

        original_body = "\n".join(body_lines)
        return original_body, pk_b64, fp, sig_b64
    except (IndexError, ValueError):
        return body, None, None, None


def format_message(from_a, to_a, subject, body, msg_id=None, attachments=None,
                   signing_key=None, public_key_b64=None) -> Tuple[str, str]:
    """Build a plain-text message string. Returns (content, msg_id).

    If signing_key and public_key_b64 are provided, the message body
    is wrapped with inline PGP-style Ed25519 signature markers that
    survive any transport (relay, email, FTP, copy-paste).
    """
    if not msg_id:
        msg_id = generate_id(from_a, to_a, subject)

    # Sign body inline if we have keys
    if signing_key and public_key_b64:
        from .identity import fingerprint_from_b64
        fp = fingerprint_from_b64(public_key_b64)
        body = wrap_signed_body(body, signing_key, public_key_b64, fp)

    lines = [
        f"From: {from_a}",
        f"To: {to_a}",
        f"Subject: {subject}",
        f"Date: {now_str()}",
        f"Message-ID: {msg_id}",
        "Status: new",
    ]
    if attachments:
        lines.append(f"Attachments: {', '.join(Path(a).name for a in attachments)}")
    lines += ["", "---", body]
    return "\n".join(lines), msg_id


def parse_message(path) -> Tuple[Optional[dict], Optional[str]]:
    """Parse a message file into (headers_dict, body_text)."""
    p = Path(path)
    if not p.exists():
        return None, None
    text = p.read_text(encoding="utf-8", errors="replace")
    headers: dict = {}
    body_lines: list = []
    in_body = False
    for line in text.split("\n"):
        if not in_body:
            if line.strip() == "---":
                in_body = True
                continue
            if ":" in line:
                k, _, v = line.partition(":")
                headers[k.strip()] = v.strip()
        else:
            body_lines.append(line)
    return headers, "\n".join(body_lines)


def parse_headers_only(path) -> dict:
    """Parse only message headers (faster — stops at '---')."""
    headers = {}
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.strip() == "---":
                break
            if ":" in line:
                k, _, v = line.partition(":")
                headers[k.strip()] = v.strip()
    return headers


def verify_message(headers: dict, body: str) -> Optional[bool]:
    """Verify a parsed message's Ed25519 signature.

    Checks for inline body signatures first (v1.0.18+), then falls
    back to header-based signatures (v1.0.17 legacy).

    Returns True if valid, False if invalid, None if unsigned.
    """
    from .identity import verify_signature

    # 1. Check inline body signature (transport-agnostic, preferred)
    original_body, pk_b64, fp, sig_b64 = unwrap_signed_body(body)
    if pk_b64 and sig_b64:
        return verify_signature(pk_b64, sig_b64, original_body)

    # 2. Fallback: header-based signature (v1.0.17 legacy, may be stripped by relay)
    pubkey = headers.get("Public-Key")
    sig = headers.get("Signature")
    if not pubkey or not sig:
        return None  # unsigned message
    header_lines = []
    for k, v in headers.items():
        if k == "Signature":
            continue
        header_lines.append(f"{k}: {v}")
    signable = "\n".join(header_lines) + "\n---\n" + body
    return verify_signature(pubkey, sig, signable)
