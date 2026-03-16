"""AgentAZAll CLI — main entry point with argparse subcommands."""

import argparse
import logging
import os
import sys
import textwrap

from .config import LOG_FMT, VERSION


def _ensure_utf8():
    """Force UTF-8 on Windows so Unicode output (trust tokens, etc.) works."""
    if sys.platform == "win32":
        os.environ.setdefault("PYTHONUTF8", "1")
        # Reconfigure stdout/stderr if they use a lossy codec
        for stream_name in ("stdout", "stderr"):
            stream = getattr(sys, stream_name)
            if hasattr(stream, "reconfigure") and stream.encoding.lower() not in ("utf-8", "utf8"):
                try:
                    stream.reconfigure(encoding="utf-8", errors="replace")
                except Exception:
                    pass


def main():
    _ensure_utf8()
    logging.basicConfig(level=logging.INFO, format=LOG_FMT, datefmt="%H:%M:%S")

    p = argparse.ArgumentParser(
        prog="agentazall",
        description=f"AgentAZAll v{VERSION} - Persistent Memory & Communication for LLM Agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Transports: email (SMTP/IMAP), ftp, or both.
            Set AGENTAZALL_CONFIG / AGENTAZALL_AGENT to override defaults.

            Examples:
              %(prog)s register --agent myagent
              %(prog)s address                             # show your public address
              %(prog)s send --to other.agenttalk -s "Hi" -b "Hello!"
              %(prog)s inbox
              %(prog)s reply abc123 --body "Got it, thanks."
              %(prog)s whoami --set "I am Agent1, a code reviewer."
              %(prog)s doing --set "Reviewing PR #42"
              %(prog)s note context --set "API key rotated today"
              %(prog)s remember --text "The API uses OAuth2" --title "api-auth"
              %(prog)s recall
              %(prog)s recall "OAuth"
              %(prog)s search "deployment"
              %(prog)s daemon
              %(prog)s daemon --once
              %(prog)s server --all
        """),
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    p.add_argument("--config", "-c", help="Config file path")
    p.add_argument("--verbose", "-v", action="store_true")
    sub = p.add_subparsers(dest="command")

    # startup (restore context at session start — works with any LLM)
    sub.add_parser("startup",
                    help="Restore full context (identity + memories + inbox) — run at session start")

    # prompt (output system-prompt snippet for any LLM)
    sub.add_parser("prompt",
                    help="Output a system-prompt snippet for any LLM agent")

    # quickstart (one-command full setup for autonomous agents)
    sp = sub.add_parser("quickstart", help="One-command full setup (for autonomous agents)")
    sp.add_argument("--agent", help="Agent name (auto-generated if omitted)")
    sp.add_argument("--identity", help="Identity string (e.g., 'I am a code reviewer')")

    # setup
    sp = sub.add_parser("setup", help="Configure this agent")
    sp.add_argument("--agent", required=True)
    sp.add_argument("--transport", choices=["email", "ftp", "both", "agenttalk"],
                     default="email")
    sp.add_argument("--share-memories", action="store_true",
                     help="Allow other agents to read this agent's memories")

    # inbox
    sp = sub.add_parser("inbox", help="List inbox messages (auto-syncs with relay)")
    sp.add_argument("--date", "-d")
    sp.add_argument("--all", action="store_true")
    sp.add_argument("--offline", action="store_true",
                     help="Skip sync, only show local messages")

    # read
    sp = sub.add_parser("read", help="Read a message")
    sp.add_argument("message_id")
    sp.add_argument("--date", "-d")

    # send
    sp = sub.add_parser("send", help="Send a message")
    sp.add_argument("--to", required=True)
    sp.add_argument("--subject", "-s", required=True)
    sp.add_argument("--body", "-b")
    sp.add_argument("--body-file")
    sp.add_argument("--attach", "-a", action="append")

    # reply
    sp = sub.add_parser("reply", help="Reply to a message")
    sp.add_argument("message_id")
    sp.add_argument("--body", "-b")

    # dates
    sub.add_parser("dates", help="List available dates")

    # search
    sp = sub.add_parser("search", help="Search messages")
    sp.add_argument("query")

    # address
    sp = sub.add_parser("address", help="Show this agent's public address")
    sp.add_argument("--quiet", "-q", action="store_true",
                     help="Machine-readable output (address only, no decoration)")

    # whoami
    sp = sub.add_parser("whoami", help="Get/set identity")
    sp.add_argument("--set")

    # doing
    sp = sub.add_parser("doing", help="Get/set current tasks")
    sp.add_argument("--set")
    sp.add_argument("--append")

    # note
    sp = sub.add_parser("note", help="Read/write a named note")
    sp.add_argument("name")
    sp.add_argument("--set")
    sp.add_argument("--append")

    # notes
    sp = sub.add_parser("notes", help="List all notes")
    sp.add_argument("--date", "-d")

    # remember
    sp = sub.add_parser("remember", help="Store a persistent memory")
    sp.add_argument("--text", "-t", help="Memory text to store")
    sp.add_argument("--title", help="Short title/slug for the memory")
    sp.add_argument("--list", action="store_true", help="List today's memories")

    # recall
    sp = sub.add_parser("recall", help="Search/display agent memories")
    sp.add_argument("query", nargs="?", help="Search query (optional)")
    sp.add_argument("--agent", help="Read another agent's memories (if they allow sharing)")

    # skill
    sp = sub.add_parser("skill", help="Manage skills (reusable Python scripts)")
    sp.add_argument("name", nargs="?", help="Skill name")
    sp.add_argument("--add", help="Add skill from file path")
    sp.add_argument("--code", help="Add skill from inline code")
    sp.add_argument("--description", help="Description of the skill")
    sp.add_argument("--version", help="Version string (default: 1.0)")
    sp.add_argument("--promote", action="store_true", help="Promote to shared/public")
    sp.add_argument("--read", action="store_true", help="Read skill source code")
    sp.add_argument("--delete", action="store_true", help="Delete a private skill")
    sp.add_argument("--shared", action="store_true", help="List only shared skills")

    # tool
    sp = sub.add_parser("tool", help="Manage tools (reusable scripts/solutions)")
    sp.add_argument("name", nargs="?", help="Tool name")
    sp.add_argument("--add", help="Add tool from file path")
    sp.add_argument("--code", help="Add tool from inline code")
    sp.add_argument("--description", help="Description of the tool")
    sp.add_argument("--version", help="Version string (default: 1.0)")
    sp.add_argument("--promote", action="store_true", help="Promote to shared/public")
    sp.add_argument("--read", action="store_true", help="Read tool source code")
    sp.add_argument("--run", action="store_true", help="Run the tool")
    sp.add_argument("--run-args", nargs="*", help="Arguments to pass when running")
    sp.add_argument("--delete", action="store_true", help="Delete a private tool")
    sp.add_argument("--shared", action="store_true", help="List only shared tools")

    # index
    sp = sub.add_parser("index", help="Show/rebuild daily index")
    sp.add_argument("--date", "-d")
    sp.add_argument("--rebuild", action="store_true")

    # status
    sub.add_parser("status", help="System status + connectivity")

    # tree
    sp = sub.add_parser("tree", help="Directory tree")
    sp.add_argument("--date", "-d")

    # daemon
    sp = sub.add_parser("daemon", help="Run sync daemon")
    sp.add_argument("--once", action="store_true")

    # directory
    sp = sub.add_parser("directory", help="List all agents and their status")
    sp.add_argument("--json", action="store_true", help="Output as JSON")

    # onboard
    sub.add_parser("onboard", help="Print onboarding guide for new agents")

    # export
    sp = sub.add_parser("export", help="Export project state to ZIP")
    sp.add_argument("--output", "-o", help="Output ZIP filename")

    # register
    sp = sub.add_parser("register", help="Register on a public relay server")
    sp.add_argument("--agent", required=True, help="Agent name (e.g., myagent)")
    sp.add_argument("--server", default="relay.agentazall.ai",
                     help="Relay server hostname (default: relay.agentazall.ai)")
    sp.add_argument("--port", type=int, default=8443,
                     help="Relay API port (default: 8443)")
    sp.add_argument("--yes", "-y", action="store_true",
                     help="Skip confirmation if config.json exists")

    # filter
    sp = sub.add_parser("filter", help="Manage address blacklist/whitelist")
    sp.add_argument("--block", help="Add address to blacklist")
    sp.add_argument("--unblock", help="Remove address from blacklist")
    sp.add_argument("--allow", help="Add address to whitelist")
    sp.add_argument("--disallow", help="Remove address from whitelist")
    sp.add_argument("--mode", choices=["blacklist", "whitelist", "off"],
                     help="Set filter mode")

    # trust-gen
    sp = sub.add_parser("trust-gen", help="Generate a trust token (proves filesystem access)")
    sp.add_argument("--agent", help="Agent name (default: current agent)")
    sp.add_argument("--force", action="store_true", help="Generate even if already bound")
    sp.add_argument("--quiet", "-q", action="store_true", help="Output raw base64 only")

    # trust-verify
    sp = sub.add_parser("trust-verify", help="Verify a trust token (for testing)")
    sp.add_argument("--token", help="Token string (or use --file or stdin)")
    sp.add_argument("--file", help="Read token from file")

    # trust-bind
    sp = sub.add_parser("trust-bind", help="Bind this agent to a human owner")
    sp.add_argument("--owner", required=True, help="Owner address (e.g. gregor@localhost)")
    sp.add_argument("--token", help="Trust token (or use --file or stdin)")
    sp.add_argument("--file", help="Read token from file")

    # trust-status
    sub.add_parser("trust-status", help="Show trust binding status")

    # trust-revoke
    sp = sub.add_parser("trust-revoke", help="Revoke trust binding (needs filesystem access)")
    sp.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")

    # trust-bind-local (one-shot: gen + bind, no piping needed)
    sp = sub.add_parser("trust-bind-local",
                          help="One-shot local trust binding (gen + bind, no piping)")
    sp.add_argument("--owner", required=True, help="Owner address (e.g., gregor@localhost)")
    sp.add_argument("--force", action="store_true", help="Force rebind")

    # trust-bind-all
    sp = sub.add_parser("trust-bind-all",
                          help="Bind ALL local agents to an owner (local shortcut)")
    sp.add_argument("--owner", required=True, help="Owner address")
    sp.add_argument("--force", action="store_true", help="Rebind already-bound agents")

    # crypto-identity (Ed25519 keypair)
    sub.add_parser("crypto-identity",
                    help="Show/generate Ed25519 cryptographic identity")

    # relay
    sp = sub.add_parser("relay", help="Manage relay server connections")
    relay_sub = sp.add_subparsers(dest="relay_action")
    relay_sub.add_parser("list", help="List configured relays")
    rr = relay_sub.add_parser("add", help="Add a relay server")
    rr.add_argument("--url", required=True, help="Relay server URL")
    rr.add_argument("--token", help="API token for the relay")
    rr.add_argument("--address", help="Agent address on this relay")
    rr = relay_sub.add_parser("remove", help="Remove a relay server")
    rr.add_argument("--url", required=True, help="Relay server URL to remove")

    # mcp-shim (MCP doorbell — push inbox notifications to LLM clients)
    sp = sub.add_parser("mcp-shim",
                         help="MCP stdio server — pushes inbox notifications to LLM clients")
    sp.add_argument("--poll-interval", type=int, default=5,
                     help="Seconds between inbox checks (default: 5)")

    # server
    sp = sub.add_parser("server", help="Start local servers")
    sp.add_argument("--email", action="store_true", help="Start email server (SMTP/IMAP/POP3)")
    sp.add_argument("--ftp", action="store_true", help="Start FTP server")
    sp.add_argument("--agenttalk", action="store_true",
                     help="Start AgentTalk server (modern HTTPS API)")
    sp.add_argument("--all", action="store_true", help="Start all servers")

    args = p.parse_args()

    # Override config path if specified
    if args.config:
        import os
        os.environ["AGENTAZALL_CONFIG"] = args.config

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Lazy imports for command dispatch
    dispatch = {
        "startup": ("commands.startup", "cmd_startup"),
        "prompt": ("commands.startup", "cmd_prompt"),
        "quickstart": ("commands.quickstart", "cmd_quickstart"),
        "setup": ("commands.setup", "cmd_setup"),
        "inbox": ("commands.messaging", "cmd_inbox"),
        "read": ("commands.messaging", "cmd_read"),
        "send": ("commands.messaging", "cmd_send"),
        "reply": ("commands.messaging", "cmd_reply"),
        "dates": ("commands.messaging", "cmd_dates"),
        "search": ("commands.messaging", "cmd_search"),
        "address": ("commands.identity", "cmd_address"),
        "whoami": ("commands.identity", "cmd_whoami"),
        "doing": ("commands.identity", "cmd_doing"),
        "note": ("commands.notes", "cmd_note"),
        "notes": ("commands.notes", "cmd_notes"),
        "remember": ("commands.memory", "cmd_remember"),
        "recall": ("commands.memory", "cmd_recall"),
        "skill": ("commands.skills", "cmd_skill"),
        "tool": ("commands.skills", "cmd_tool"),
        "index": ("commands.system", "cmd_index"),
        "status": ("commands.system", "cmd_status"),
        "tree": ("commands.system", "cmd_tree"),
        "directory": ("commands.system", "cmd_directory"),
        "filter": ("commands.filtering", "cmd_filter"),
        "register": ("commands.register", "cmd_register"),
        "crypto-identity": ("commands.relay_cmd", "cmd_crypto_identity"),
        "relay": ("commands.relay_cmd", "cmd_relay"),
        "trust-gen": ("commands.trust_cmd", "cmd_trust_gen"),
        "trust-verify": ("commands.trust_cmd", "cmd_trust_verify"),
        "trust-bind": ("commands.trust_cmd", "cmd_trust_bind"),
        "trust-status": ("commands.trust_cmd", "cmd_trust_status"),
        "trust-revoke": ("commands.trust_cmd", "cmd_trust_revoke"),
        "trust-bind-local": ("commands.trust_cmd", "cmd_trust_bind_local"),
        "trust-bind-all": ("commands.trust_cmd", "cmd_trust_bind_all"),
        "mcp-shim": ("mcp_shim", "cmd_mcp_shim"),
        "daemon": ("commands.server", "cmd_daemon"),
        "server": ("commands.server", "cmd_server"),
        "export": ("commands.server", "cmd_export"),
        "onboard": ("commands.server", "cmd_onboard"),
    }

    if args.command in dispatch:
        module_name, func_name = dispatch[args.command]
        import importlib
        mod = importlib.import_module(f".{module_name}", package="agentazall")
        func = getattr(mod, func_name)
        func(args)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
