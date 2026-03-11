"""AgentAZAll message format — compose & parse plain-text messages."""

from pathlib import Path
from typing import Optional, Tuple

from .helpers import generate_id, now_str


def format_message(from_a, to_a, subject, body, msg_id=None, attachments=None,
                   signing_key=None, public_key_b64=None) -> Tuple[str, str]:
    """Build a plain-text message string. Returns (content, msg_id).

    If signing_key and public_key_b64 are provided, the message is
    cryptographically signed with Ed25519 and Public-Key / Signature
    headers are appended.  Signature covers all headers (except
    Signature itself) + ``---`` + body.
    """
    if not msg_id:
        msg_id = generate_id(from_a, to_a, subject)
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
    if public_key_b64:
        lines.append(f"Public-Key: {public_key_b64}")

    # Build signable payload: all headers so far + --- + body
    if signing_key and public_key_b64:
        from .identity import sign_message
        signable = "\n".join(lines) + "\n---\n" + body
        sig = sign_message(signing_key, signable)
        lines.append(f"Signature: {sig}")

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

    Returns True if valid, False if invalid, None if unsigned.
    """
    pubkey = headers.get("Public-Key")
    sig = headers.get("Signature")
    if not pubkey or not sig:
        return None  # unsigned message — legacy agent
    # Reconstruct signable payload: all headers except Signature + --- + body
    header_lines = []
    for k, v in headers.items():
        if k == "Signature":
            continue
        header_lines.append(f"{k}: {v}")
    signable = "\n".join(header_lines) + "\n---\n" + body
    from .identity import verify_signature
    return verify_signature(pubkey, sig, signable)
