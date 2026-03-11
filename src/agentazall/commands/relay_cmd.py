"""AgentAZAll commands: identity (crypto) + relay add/remove/list."""

import json
import sys
from pathlib import Path

from ..config import load_config, save_config
from ..helpers import agent_base
from ..identity import (
    generate_keypair, save_keypair, load_keypair,
    fingerprint, public_key_b64,
)


def cmd_crypto_identity(args):
    """Show or generate the agent's Ed25519 cryptographic identity."""
    cfg = load_config(getattr(args, "config", None))
    base = agent_base(cfg)

    existing = load_keypair(base)
    if existing:
        sk, vk = existing
    else:
        print("No identity keypair found — generating one now...")
        sk, vk = generate_keypair()
        save_keypair(base, sk)

    fp = fingerprint(vk)
    pk = public_key_b64(vk)
    print(f"Agent      : {cfg['agent_name']}")
    print(f"Fingerprint: {fp}")
    print(f"Public key : {pk}")
    print(f"Key file   : {base / '.identity_key'}")


def cmd_relay(args):
    """Manage relay server connections: add, remove, list."""
    action = getattr(args, "relay_action", None)
    if not action:
        print("Usage: agentazall relay {add|remove|list}")
        return

    cfg = load_config(getattr(args, "config", None))
    config_path = Path(getattr(args, "config", None) or "config.json")

    if action == "list":
        _relay_list(cfg)
    elif action == "add":
        url = getattr(args, "url", None)
        token = getattr(args, "token", None) or ""
        address = getattr(args, "address", None) or ""
        if not url:
            print("ERROR: --url required")
            sys.exit(1)
        _relay_add(cfg, config_path, url, token, address)
    elif action == "remove":
        url = getattr(args, "url", None)
        if not url:
            print("ERROR: --url required")
            sys.exit(1)
        _relay_remove(cfg, config_path, url)


def _relay_list(cfg):
    """List all configured relay servers."""
    relays = cfg.get("relays", [])
    # Also show the legacy single agenttalk config
    at = cfg.get("agenttalk", {})
    if at.get("server") and not relays:
        relays = [{"server": at["server"], "token": at.get("token", "")}]

    if not relays:
        print("No relay servers configured.")
        print("  Use: agentazall relay add --url https://relay.example.com:8443")
        return

    print(f"Configured relays ({len(relays)}):")
    for i, r in enumerate(relays, 1):
        server = r.get("server", "?")
        token = r.get("token", "")
        address = r.get("address", "")
        token_display = f"{token[:8]}..." if len(token) > 8 else token or "(none)"
        print(f"  {i}. {server}")
        if address:
            print(f"     Address: {address}")
        print(f"     Token  : {token_display}")


def _relay_add(cfg, config_path, url, token, address):
    """Add a relay server to the config."""
    relays = cfg.setdefault("relays", [])

    # Check if already present
    for r in relays:
        if r.get("server") == url:
            print(f"Relay {url} already configured — updating token/address.")
            if token:
                r["token"] = token
            if address:
                r["address"] = address
            save_config(cfg, config_path)
            return

    entry = {"server": url}
    if token:
        entry["token"] = token
    if address:
        entry["address"] = address
    relays.append(entry)

    # Also update legacy single agenttalk config to the first relay
    if len(relays) == 1 or not cfg.get("agenttalk", {}).get("server"):
        cfg["agenttalk"] = {"server": url, "token": token}

    save_config(cfg, config_path)
    print(f"Added relay: {url}")
    print(f"  Total relays: {len(relays)}")


def _relay_remove(cfg, config_path, url):
    """Remove a relay server from the config."""
    relays = cfg.get("relays", [])
    before = len(relays)
    relays = [r for r in relays if r.get("server") != url]

    if len(relays) == before:
        print(f"Relay {url} not found in config.")
        return

    cfg["relays"] = relays

    # Update legacy single agenttalk to first remaining relay
    if relays:
        cfg["agenttalk"] = {
            "server": relays[0]["server"],
            "token": relays[0].get("token", ""),
        }
    else:
        cfg["agenttalk"] = {"server": "", "token": ""}

    save_config(cfg, config_path)
    print(f"Removed relay: {url}")
    print(f"  Remaining relays: {len(relays)}")
