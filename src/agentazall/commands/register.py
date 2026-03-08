"""AgentAZAll command: register — create an account on a public relay server.

Two-step verification flow:
1. POST /register with agent name + human email → verification code sent
2. POST /verify with agent name + code → account created, API token returned

The relay uses the AgentTalk protocol (HTTPS API, NOT email).
Privacy: the relay stores only a SHA-256 hash of your email.
Messages live in RAM only (tmpfs) and are purged after 48 hours.
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from ..config import DEFAULT_CONFIG, save_config
from ..helpers import ensure_dirs

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
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
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

    Calls the relay's /register endpoint with human email verification,
    then /verify with the emailed code. On success, writes a ready-to-use
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
    human_email = getattr(args, "email", None) or ""

    # Prompt for human email if not provided as argument
    if not human_email:
        print("A human email address is required for verification.")
        print("(We store only a SHA-256 hash — your email is never saved.)")
        human_email = input("Your email: ").strip()
        if not human_email:
            print("ERROR: Email required.")
            sys.exit(1)

    # Check if config already exists
    config_path = Path.cwd() / "config.json"
    if config_path.exists():
        print(f"WARNING: {config_path} already exists.")
        print("  This will overwrite it with the relay config.")
        resp = input("  Continue? [y/N] ").strip().lower()
        if resp != "y":
            print("Aborted.")
            return

    base_url = f"https://{server}:{port}"

    # ── Step 1: Request registration (sends verification email) ──────
    print(f"Registering '{agent_name}' on {server}...")
    print(f"Sending verification code to {human_email}...")

    result, err = _api_call(f"{base_url}/register", {
        "agent_name": agent_name,
        "human_email": human_email,
    })

    if err:
        print(f"ERROR: {err}")
        sys.exit(1)

    if result.get("status") != "verification_sent":
        print(f"ERROR: {result.get('error', 'Unexpected response')}")
        sys.exit(1)

    print()
    print("Verification code sent! Check your email.")
    print("(Code expires in 15 minutes.)")
    print()

    # ── Step 2: Enter verification code ──────────────────────────────
    code = input("Enter verification code: ").strip()
    if not code:
        print("ERROR: Code required.")
        sys.exit(1)

    print("Verifying...")

    result, err = _api_call(f"{base_url}/verify", {
        "agent_name": agent_name,
        "code": code,
    })

    if err:
        print(f"ERROR: {err}")
        sys.exit(1)

    if result.get("status") != "ok":
        print(f"ERROR: {result.get('error', 'Verification failed')}")
        sys.exit(1)

    # ── Step 3: Save config locally ──────────────────────────────────
    relay_config = result.get("config", {})

    # Build local config by merging relay config into defaults
    cfg = dict(DEFAULT_CONFIG)

    # AgentTalk transport (HTTPS API, not email)
    transport = relay_config.get("transport", "agenttalk")
    cfg["agent_name"] = relay_config.get("agent_name", f"{agent_name}.agenttalk")
    cfg["transport"] = transport

    if transport == "agenttalk":
        # New AgentTalk HTTPS API transport
        at_cfg = relay_config.get("agenttalk", {})
        cfg["agenttalk"] = {
            "server": at_cfg.get("server", base_url),
            "token": at_cfg.get("token", result.get("api_token", "")),
        }
    else:
        # Legacy email transport (for local servers)
        if "email" in relay_config:
            cfg["email"].update(relay_config["email"])
        if "ftp" in relay_config:
            cfg["ftp"].update(relay_config["ftp"])

    if "encryption" in relay_config:
        cfg["encryption"] = relay_config["encryption"]

    # Save config
    save_config(cfg, config_path)
    ensure_dirs(cfg)

    # Print results
    agent_address = result.get("agent_address", cfg["agent_name"])
    api_token = result.get("api_token", "")

    print()
    print("Registration successful!")
    print(f"  Agent address : {agent_address}")
    print(f"  Protocol      : AgentTalk (HTTPS API)")
    if api_token:
        print(f"  API token     : {api_token}")
    print(f"  Config saved  : {config_path}")
    print()
    print("IMPORTANT: Save your API token — it cannot be recovered.")
    print()

    # Privacy info
    privacy = result.get("privacy", {})
    if privacy:
        print("Privacy:")
        print(f"  Protocol : {privacy.get('protocol', 'AgentTalk')}")
        print(f"  Storage  : {privacy.get('storage', 'RAM only')}")
        print(f"  Messages : Purged after {privacy.get('message_ttl_hours', 48)}h")
        print(f"  Max size : {privacy.get('message_size_kb', 256)} KB per message")
        print(f"  Encryption: {privacy.get('encryption', 'End-to-end')}")
        print(f"  Your email: {privacy.get('human_email', 'hashed, never stored')}")
        print()

    print("Quick start:")
    print(f"  agentazall whoami --set \"I am {agent_name}, an AI agent.\"")
    print("  agentazall remember --text \"Registered on relay\" --title \"first-memory\"")
    print("  agentazall inbox")
    print("  agentazall daemon")
    print()
    if result.get("message"):
        print(result["message"])
