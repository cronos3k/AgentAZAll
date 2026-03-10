"""CLI commands for trust token generation, verification, and management."""

import json
import sys
from pathlib import Path

from ..config import load_config
from ..helpers import agent_base


def cmd_trust_gen(args):
    """Generate a trust token for an agent."""
    from ..trust import (
        generate_trust_token,
        is_bound,
        machine_fingerprint,
        write_pending_token,
    )

    cfg = load_config()
    agent_name = args.agent or cfg["agent_name"]
    base = agent_base(cfg)
    agent_key = cfg.get("agent_key", "")

    if not agent_key:
        # Try to read from .agent_key file
        key_file = base / ".agent_key"
        if key_file.exists():
            try:
                data = json.loads(key_file.read_text(encoding="utf-8"))
                agent_key = data.get("key", "")
            except Exception:
                pass

    if not agent_key:
        print("ERROR: No agent_key found. Run 'agentazall setup' first.")
        sys.exit(1)

    if is_bound(base) and not args.force:
        from ..trust import get_trust_info
        info = get_trust_info(base)
        owner = info.get("owner", "unknown")
        print(f"Agent '{agent_name}' is already bound to {owner}.")
        print("Use --force to generate a token anyway (requires trust-revoke first).")
        sys.exit(1)

    result = generate_trust_token(agent_name, agent_key)

    # Always write pending file for local web UI pickup
    write_pending_token(
        base, result["token_ascii"],
        result["owner_auth_secret"], result["expires_at"],
    )

    if args.quiet:
        # Machine-readable: just the base64 token
        from base64 import b64encode
        print(b64encode(result["token_bytes"]).decode("ascii"))
    else:
        print(result["token_ascii"])
        print()
        print(f"Token generated for: {agent_name}")
        print(f"Expires in: 10 minutes")
        print(f"Pending file: {base / '.trust_token_pending'}")
        print()
        print("NEXT STEPS:")
        print("  Local web UI: Token will appear automatically in the Trust tab.")
        print("  Remote:       Copy the block above and paste into the Trust form.")


def cmd_trust_verify(args):
    """Verify a trust token (for testing)."""
    from ..trust import verify_trust_token

    cfg = load_config()
    agent_key = cfg.get("agent_key", "")

    if not agent_key:
        print("ERROR: No agent_key in config.")
        sys.exit(1)

    token_input = args.token
    if not token_input and args.file:
        token_input = Path(args.file).read_text(encoding="utf-8")
    elif not token_input:
        print("Reading token from stdin (paste and press Ctrl+D)...")
        token_input = sys.stdin.read()

    result = verify_trust_token(
        token_input, agent_key,
        expected_agent=cfg["agent_name"],
    )

    if result.valid:
        print(f"VALID: Token verified for {result.agent_name}")
        print(f"  Nonce:     {result.nonce[:16]}...")
        print(f"  Timestamp: {result.timestamp}")
        print(f"  Machine:   fingerprint matches")
    else:
        print(f"INVALID: {result.reason}")
        sys.exit(1)


def cmd_trust_bind(args):
    """Bind an agent to a human owner using a trust token."""
    from ..trust import attempt_bind

    cfg = load_config()

    token_input = args.token
    if not token_input and args.file:
        token_input = Path(args.file).read_text(encoding="utf-8")
    elif not token_input:
        print("Reading token from stdin (paste and press Ctrl+D)...")
        token_input = sys.stdin.read()

    owner = args.owner
    if not owner:
        print("ERROR: --owner is required (the human's address, e.g. gregor@localhost)")
        sys.exit(1)

    result = attempt_bind(cfg, token_input, owner)
    print(result)


def cmd_trust_status(args):
    """Show trust binding status."""
    from ..trust import get_trust_info, is_bound, machine_fingerprint, machine_short_name

    cfg = load_config()
    base = agent_base(cfg)
    agent_name = cfg["agent_name"]

    if not is_bound(base):
        print(f"Agent: {agent_name}")
        print(f"Trust: UNBOUND")
        print(f"  No owner has been bound to this agent.")
        print(f"  Run 'agentazall trust-gen' to create a trust token.")
        return

    info = get_trust_info(base)
    owner = info.get("owner", "unknown")
    bound_since = info.get("bound_since", "unknown")
    status = info.get("status", "unknown")
    stored_fp = info.get("machine_fingerprint", "")
    current_fp = machine_fingerprint()
    fp_match = stored_fp == current_fp

    print(f"Agent:   {agent_name}")
    print(f"Owner:   {owner}")
    print(f"Bound:   {bound_since}")
    print(f"Machine: {machine_short_name()} (fingerprint {'VALID' if fp_match else 'CHANGED'})")
    print(f"Status:  {status.upper()}")

    perms = info.get("permissions", {})
    rebind = "allowed" if perms.get("accept_new_bindings") else "locked"
    print(f"Rebind:  {rebind}")

    if not fp_match:
        print()
        print("WARNING: Machine fingerprint has changed since binding.")
        print("  This may happen after hardware or OS changes.")
        print("  Consider re-binding with 'agentazall trust-revoke' + 'trust-gen'.")


def cmd_trust_revoke(args):
    """Revoke trust binding (requires filesystem access)."""
    from ..trust import revoke_trust, get_trust_info, is_bound

    cfg = load_config()
    base = agent_base(cfg)
    agent_name = cfg["agent_name"]

    if not is_bound(base):
        print(f"Agent '{agent_name}' is not bound to any owner.")
        return

    info = get_trust_info(base)
    owner = info.get("owner", "unknown")

    if not args.yes:
        print(f"About to revoke trust binding:")
        print(f"  Agent: {agent_name}")
        print(f"  Owner: {owner}")
        print(f"  This will unbind the agent. A new trust token will be needed.")
        print()
        resp = input("Type 'REVOKE' to confirm: ")
        if resp.strip() != "REVOKE":
            print("Cancelled.")
            return

    if revoke_trust(base):
        print(f"Trust binding revoked for '{agent_name}'.")
        print(f"Agent is now UNBOUND and will accept new trust tokens.")
    else:
        print("Failed to revoke — .trust file not found.")


def cmd_trust_bind_local(args):
    """One-shot local trust binding — generate + bind in one command.

    No piping, no copy-paste, no encoding issues.  Just works.
    Requires filesystem access (proof of ownership).
    """
    from ..trust import (
        generate_trust_token,
        is_bound,
        get_trust_info,
        store_trust_binding,
        burn_nonce,
        machine_fingerprint,
    )

    cfg = load_config()
    base = agent_base(cfg)
    agent_name = cfg["agent_name"]
    agent_key = cfg.get("agent_key", "")

    if not agent_key:
        key_file = base / ".agent_key"
        if key_file.exists():
            try:
                data = json.loads(key_file.read_text(encoding="utf-8"))
                agent_key = data.get("key", "")
            except Exception:
                pass

    if not agent_key:
        print("ERROR: No agent_key found. Run 'agentazall setup' or 'agentazall register' first.")
        sys.exit(1)

    owner = args.owner
    if not owner:
        print("ERROR: --owner is required (e.g., --owner gregor@localhost)")
        sys.exit(1)

    if is_bound(base) and not args.force:
        info = get_trust_info(base)
        current_owner = info.get("owner", "unknown")
        print(f"Agent '{agent_name}' is already bound to {current_owner}.")
        print("Use --force to rebind (requires trust-revoke first).")
        sys.exit(1)

    fp = machine_fingerprint()
    result = generate_trust_token(agent_name, agent_key, machine_fp=fp)
    burn_nonce(base, result["nonce"])
    store_trust_binding(
        base, owner, result["nonce"], fp, result["owner_auth_secret"],
    )

    print(f"Trust binding established!")
    print(f"  Agent:  {agent_name}")
    print(f"  Owner:  {owner}")
    print(f"  Status: ACTIVE")
    print(f"  Rebind: locked")


def cmd_trust_bind_all(args):
    """Bind all local agents to an owner (local convenience shortcut)."""
    from ..trust import (
        generate_trust_token,
        is_bound,
        store_trust_binding,
        burn_nonce,
        machine_fingerprint,
    )

    cfg = load_config()
    owner = args.owner
    if not owner:
        print("ERROR: --owner is required.")
        sys.exit(1)

    mailbox_dir = Path(cfg["mailbox_dir"])
    if not mailbox_dir.exists():
        print("No mailbox directory found.")
        return

    fp = machine_fingerprint()
    bound_count = 0

    for agent_dir in sorted(mailbox_dir.iterdir()):
        if not agent_dir.is_dir():
            continue
        agent_name = agent_dir.name
        if agent_name.startswith("."):
            continue

        key_file = agent_dir / ".agent_key"
        if not key_file.exists():
            print(f"  SKIP {agent_name} — no .agent_key")
            continue

        if is_bound(agent_dir) and not args.force:
            from ..trust import get_trust_info
            info = get_trust_info(agent_dir)
            current_owner = info.get("owner", "?")
            print(f"  SKIP {agent_name} — already bound to {current_owner}")
            continue

        try:
            data = json.loads(key_file.read_text(encoding="utf-8"))
            agent_key = data.get("key", "")
        except Exception:
            print(f"  SKIP {agent_name} — cannot read .agent_key")
            continue

        if not agent_key:
            print(f"  SKIP {agent_name} — empty agent_key")
            continue

        # Generate token, verify inline, bind directly (local shortcut)
        result = generate_trust_token(agent_name, agent_key, machine_fp=fp)
        burn_nonce(agent_dir, result["nonce"])
        store_trust_binding(
            agent_dir, owner, result["nonce"], fp,
            result["owner_auth_secret"],
        )

        print(f"  BOUND {agent_name} → {owner}")
        bound_count += 1

    print()
    if bound_count:
        print(f"Bound {bound_count} agent(s) to {owner}.")
    else:
        print("No agents were bound (all already bound or no agents found).")
