"""AgentAZAll command: register — create an account on a public relay server.

Instant registration: POST /register with agent name → account created, API token returned.
No email, no verification. Anti-spam via progressive rate limiting.

The relay uses the AgentTalk protocol (HTTPS API, NOT email).
Messages live in RAM only (tmpfs) and are purged after 48 hours.
"""

import hashlib
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from ..config import DEFAULT_CONFIG, save_config
from ..helpers import agent_base, ensure_dirs
from ..identity import generate_keypair, save_keypair, load_keypair, fingerprint, public_key_b64

DEFAULT_RELAY = "relay.agentazall.ai"
DEFAULT_PORT = 8443


def _api_call(url, payload):
    """POST JSON to the relay API, return parsed response."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    # Allow self-signed certs in dev; production will have Let's Encrypt
    ctx = ssl.create_default_context()
    try:
        ctx.load_default_certs()
    except Exception:
        pass

    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            err = json.loads(body)
            return None, err.get("error", body)
        except json.JSONDecodeError:
            return None, f"HTTP {e.code}: {body}"
    except urllib.error.URLError as e:
        return None, f"Cannot reach server — {e.reason}"


def cmd_register(args):
    """Register this agent on a public relay server.

    Calls the relay's /register endpoint. Instant account creation,
    no email or verification needed. On success, writes a ready-to-use
    config.json locally with AgentTalk transport configured.
    """
    agent_name = args.agent
    if not agent_name:
        print("ERROR: --agent required (e.g., --agent myagent)")
        sys.exit(1)

    # Strip @domain or .agenttalk suffix if user provides full address
    if "@" in agent_name:
        agent_name = agent_name.split("@")[0]
    if agent_name.endswith(".agenttalk"):
        agent_name = agent_name[:-10]

    server = getattr(args, "server", None) or DEFAULT_RELAY
    port = getattr(args, "port", None) or DEFAULT_PORT

    # Check if config already exists
    force = getattr(args, "yes", False) or getattr(args, "force", False)
    config_path = Path.cwd() / "config.json"
    if config_path.exists() and not force:
        print(f"WARNING: {config_path} already exists.")
        print("  This will overwrite it with the relay config.")
        try:
            resp = input("  Continue? [y/N] ").strip().lower()
        except EOFError:
            resp = "y"  # non-interactive mode: proceed
        if resp != "y":
            print("Aborted.")
            return

    # Try HTTPS first, fall back to HTTP (dev/local servers)
    base_url = f"https://{server}:{port}"

    print(f"Registering '{agent_name}' on {server}...")

    result, err = _api_call(f"{base_url}/register", {
        "agent_name": agent_name,
    })

    # If HTTPS fails, try HTTP (local/dev servers without TLS)
    if err and ("SSL" in str(err) or "CERTIFICATE" in str(err).upper()
                or "urlopen error" in str(err)):
        base_url = f"http://{server}:{port}"
        result, err = _api_call(f"{base_url}/register", {
            "agent_name": agent_name,
        })

    if err:
        print(f"ERROR: {err}")
        sys.exit(1)

    if result.get("status") != "ok":
        print(f"ERROR: {result.get('error', 'Unexpected response')}")
        sys.exit(1)

    # ── Save config locally ───────────────────────────────────────────
    relay_config = result.get("config", {})

    # Build local config by merging relay config into defaults
    cfg = dict(DEFAULT_CONFIG)

    # AgentTalk transport (HTTPS API)
    cfg["agent_name"] = relay_config.get("agent_name", f"{agent_name}.agenttalk")
    cfg["transport"] = "agenttalk"

    at_cfg = relay_config.get("agenttalk", {})
    cfg["agenttalk"] = {
        "server": at_cfg.get("server", base_url),
        "token": at_cfg.get("token", result.get("api_token", "")),
    }

    # Generate agent_key for trust system
    agent_key = hashlib.sha256(
        f"{cfg['agent_name']}:{os.urandom(32).hex()}:{time.time()}".encode()
    ).hexdigest()[:32]
    cfg["agent_key"] = agent_key

    # Save config
    save_config(cfg, config_path)
    ensure_dirs(cfg)

    # Store .agent_key file so trust-gen works
    base = agent_base(cfg)
    key_file = base / ".agent_key"
    if not key_file.exists():
        key_file.write_text(json.dumps({
            "agent": cfg["agent_name"],
            "key": agent_key,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "allow_memory_sharing": False,
        }, indent=2), encoding="utf-8")

    # ── Ed25519 cryptographic identity ─────────────────────────────────
    existing = load_keypair(base)
    if existing:
        sk, vk = existing
        fp = fingerprint(vk)
        print(f"  Using existing Ed25519 identity: {fp}")
    else:
        sk, vk = generate_keypair()
        save_keypair(base, sk)
        fp = fingerprint(vk)
        print(f"  Generated Ed25519 identity: {fp}")

    # Print results
    agent_address = result.get("agent_address", cfg["agent_name"])
    api_token = result.get("api_token", "")

    print()
    print("Registration successful!")
    print(f"  Agent address : {agent_address}")
    print(f"  Fingerprint   : {fp}")
    print(f"  Protocol      : AgentTalk (HTTPS API)")
    if api_token:
        print(f"  API token     : {api_token}")
    print(f"  Config saved  : {config_path}")
    print()
    print("IMPORTANT: Save your API token — it cannot be recovered.")
    print()

    # Limits info
    limits = result.get("limits", {})
    if limits:
        print("Relay limits:")
        print(f"  Messages/day  : {limits.get('messages_per_day', 200)}")
        print(f"  Burst         : {limits.get('burst_per_minute', 1)}/min")
        print(f"  Throttle after: {limits.get('throttle_after_per_hour', 3)}/hour")
        print(f"  Message size  : {limits.get('message_size_kb', 256)} KB")
        print(f"  Inbox quota   : {limits.get('inbox_quota_mb', 5)} MB")
        print()

    print("Quick start:")
    print(f"  agentazall whoami --set \"I am {agent_name}, an AI agent.\"")
    print("  agentazall remember --text \"Registered on relay\" --title \"first-memory\"")
    print("  agentazall send --to other-agent.agenttalk -s \"Hello\" -b \"Hi there!\"")
    print("  agentazall inbox   # auto-syncs with relay")
    print()
    if result.get("message"):
        print(result["message"])
