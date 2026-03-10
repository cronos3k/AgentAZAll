#!/usr/bin/env python3
"""
AgentAZAll Web UI -- Gradio-based interface for human participants.

Provides a browser GUI for:
  - Reading inbox messages
  - Composing and sending messages
  - Browsing the agent directory
  - Managing notes and memories
  - Running daemon sync cycles

Usage:
    python web_ui.py [--port PORT] [--agent AGENT]

Requires: pip install gradio
"""

import json
import os
import shutil as _shutil
import socket
import subprocess
import sys
from pathlib import Path

try:
    import gradio as gr
except ImportError:
    print("ERROR: gradio required.  Install:  pip install gradio")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).parent.resolve()

# Detect CLI command: prefer pip-installed 'agentazall', fall back to module invocation

if _shutil.which("agentazall"):
    CLI = ["agentazall"]
else:
    CLI = [sys.executable, "-m", "agentazall"]

# Config: check env, then cwd, then script dir
_config_env = os.environ.get("AGENTAZALL_CONFIG")
if _config_env:
    HUMAN_CONFIG = Path(_config_env)
elif (Path.cwd() / "config_human.json").exists():
    HUMAN_CONFIG = Path.cwd() / "config_human.json"
else:
    HUMAN_CONFIG = SCRIPT_DIR / "config_human.json"


def run_cli(*args):
    """Run an agentazall CLI command using the human config and return stdout."""
    cmd = CLI + ["--config", str(HUMAN_CONFIG)] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           cwd=str(SCRIPT_DIR), timeout=60)
    except subprocess.TimeoutExpired:
        return "ERROR: Command timed out after 60 seconds."
    except OSError as e:
        return f"ERROR: Could not run command: {e}"
    if r.returncode != 0:
        return f"ERROR (exit {r.returncode}): {r.stderr or r.stdout}"
    return r.stdout


def _ensure_human_setup():
    """Create human config and mailbox if they don't exist yet."""
    if HUMAN_CONFIG.exists():
        try:
            cfg = json.loads(HUMAN_CONFIG.read_text(encoding="utf-8"))
            return cfg.get("agent_name", "human@localhost")
        except Exception:
            pass
    # Run setup for the human user
    cmd = CLI + ["--config", str(HUMAN_CONFIG), "setup", "--agent", "human@localhost"]
    subprocess.run(cmd, capture_output=True, text=True, cwd=str(SCRIPT_DIR), timeout=30)
    return "human@localhost"


def is_port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def find_free_port(start=7860, end=7960):
    for p in range(start, end + 1):
        if is_port_free(p):
            return p
    raise RuntimeError(f"No free port found in range {start}-{end}")


# ── actions ──────────────────────────────────────────────────────────────────

def get_status():
    return run_cli("status")


def sync_now():
    return run_cli("daemon", "--once")


def get_inbox(date_str, show_all):
    if show_all:
        return run_cli("inbox", "--all")
    if date_str:
        if not _valid_date(date_str):
            return "Invalid date format. Use YYYY-MM-DD."
        return run_cli("inbox", "--date", date_str.strip())
    return run_cli("inbox")


def _sanitize_input(val: str) -> str:
    """Strip and reject values that look like CLI flags."""
    val = val.strip()
    if val.startswith("-"):
        return ""
    return val


def _valid_msg_id(val: str) -> bool:
    """Message IDs are 12-char hex strings."""
    import re
    return bool(re.match(r'^[a-f0-9]{4,20}$', val.strip()))


def _valid_date(val: str) -> bool:
    import re
    return bool(re.match(r'^\d{4}-\d{2}-\d{2}$', val.strip()))


def read_message(msg_id):
    if not msg_id or not msg_id.strip():
        return "Enter a message ID."
    mid = msg_id.strip()
    if not _valid_msg_id(mid):
        return "Invalid message ID format (expected hex string like abc123def456)."
    return run_cli("read", mid)


def send_message(to_addr, subject, body):
    if not to_addr or not subject or not body:
        return "All fields (To, Subject, Body) are required."
    to_clean = _sanitize_input(to_addr)
    if not to_clean:
        return "Invalid recipient address."
    result = run_cli("send", "--to", to_clean,
                     "--subject", _sanitize_input(subject) or "No Subject",
                     "--body", body.strip())
    return result


def reply_message(msg_id, body):
    if not msg_id or not body:
        return "Message ID and reply body are required."
    mid = msg_id.strip()
    if not _valid_msg_id(mid):
        return "Invalid message ID format."
    return run_cli("reply", mid, "--body", body.strip())


def search_messages(query):
    if not query or not query.strip():
        return "Enter a search query."
    q = _sanitize_input(query)
    if not q:
        return "Invalid search query."
    return run_cli("search", q)


def get_directory():
    return run_cli("directory")


def get_directory_json():
    return run_cli("directory", "--json")


def get_dates():
    return run_cli("dates")


def get_index(date_str):
    if date_str:
        return run_cli("index", "--date", date_str)
    return run_cli("index")


def get_tree(date_str):
    if date_str:
        return run_cli("tree", "--date", date_str)
    return run_cli("tree")


def get_whoami():
    return run_cli("whoami")


def set_whoami(text):
    if not text or not text.strip():
        return "Enter identity text."
    return run_cli("whoami", "--set", text.strip())


def get_doing():
    return run_cli("doing")


def set_doing(text):
    if not text or not text.strip():
        return "Enter task text."
    return run_cli("doing", "--set", text.strip())


def get_notes(date_str):
    if date_str:
        return run_cli("notes", "--date", date_str)
    return run_cli("notes")


def read_note(name):
    if not name or not name.strip():
        return "Enter a note name."
    return run_cli("note", name.strip())


def write_note(name, text):
    if not name or not text:
        return "Both name and text are required."
    return run_cli("note", name.strip(), "--set", text.strip())


def store_memory(text, title):
    if not text or not text.strip():
        return "Enter memory text."
    args = ["remember", "--text", text.strip()]
    if title and title.strip():
        args += ["--title", title.strip()]
    return run_cli(*args)


def recall_memories(query):
    if query and query.strip():
        return run_cli("recall", query.strip())
    return run_cli("recall")


def export_project():
    return run_cli("export")


# ── onboarding ───────────────────────────────────────────────────────────────

def _get_all_users() -> list:
    """Return list of existing agent/human names from mailbox directories."""
    mb_root = SCRIPT_DIR / "data" / "mailboxes"
    if not mb_root.exists():
        return []
    return [d.name for d in mb_root.iterdir() if d.is_dir()]


def _user_config_path(username: str) -> Path:
    """Config file path for a specific user."""
    safe = username.replace("@", "_at_")
    return SCRIPT_DIR / f"config_{safe}.json"


def check_onboard_status():
    """Check if the current user (from HUMAN_CONFIG) is onboarded."""
    if not HUMAN_CONFIG.exists():
        return "NOT ONBOARDED. Please use the Onboarding tab to create your account."
    try:
        cfg = json.loads(HUMAN_CONFIG.read_text(encoding="utf-8"))
        name = cfg.get("agent_name", "unknown")
        identity = run_cli("whoami")
        doing = run_cli("doing")
        return (f"Logged in as: {name}\n\n"
                f"Identity: {identity}\n"
                f"Current task: {doing}")
    except Exception as e:
        return f"Config exists but error reading it: {e}"


def do_onboard(username, identity, current_task):
    """Onboard a new human user into the system."""
    if not username or not username.strip():
        return "Please enter a username."

    name = username.strip()
    if "@" not in name:
        name = f"{name}@localhost"

    # Check if name is taken
    existing = _get_all_users()
    if name in existing:
        return (f"The name '{name}' is already taken!\n\n"
                f"Existing users: {', '.join(existing)}\n\n"
                f"Please choose a different name.")

    # Create user config
    user_cfg_path = _user_config_path(name)
    cmd = CLI + ["--config", str(user_cfg_path), "setup", "--agent", name]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       cwd=str(SCRIPT_DIR), timeout=30)
    if r.returncode != 0:
        return f"Setup failed: {r.stderr or r.stdout}"

    # Copy as the active human config
    import shutil
    shutil.copy2(str(user_cfg_path), str(HUMAN_CONFIG))

    # Set identity
    if identity and identity.strip():
        run_cli("whoami", "--set", identity.strip())

    # Set current task
    if current_task and current_task.strip():
        run_cli("doing", "--set", current_task.strip())

    # Add to email server accounts
    accounts_path = SCRIPT_DIR / "data" / "email_store" / "accounts.json"
    if accounts_path.exists():
        try:
            accounts = json.loads(accounts_path.read_text(encoding="utf-8"))
            if name not in accounts:
                accounts[name] = {"password": "password"}
                accounts_path.write_text(json.dumps(accounts, indent=2), encoding="utf-8")
        except Exception:
            pass

    # Sync
    run_cli("daemon", "--once")

    directory = run_cli("directory")
    return (f"Welcome to AgentAZAll, {name}!\n\n"
            f"Your account is set up and ready.\n\n"
            f"=== Current Network ===\n{directory}")


def switch_user(username):
    """Switch to an existing user's config."""
    if not username or not username.strip():
        return "Select a user."
    name = username.strip()
    user_cfg = _user_config_path(name)
    if not user_cfg.exists():
        # Try creating from the setup data
        cmd = CLI + ["--config", str(user_cfg), "setup", "--agent", name]
        r = subprocess.run(cmd, capture_output=True, text=True,
                           cwd=str(SCRIPT_DIR), timeout=30)
        if r.returncode != 0:
            return f"Could not load user: {r.stderr or r.stdout}"

    import shutil
    shutil.copy2(str(user_cfg), str(HUMAN_CONFIG))
    identity = run_cli("whoami")
    return f"Switched to {name}.\nIdentity: {identity}"


def list_users():
    """List all users in the system."""
    users = _get_all_users()
    if not users:
        return "No users registered yet."
    lines = ["=== Registered Users ===", ""]
    for u in sorted(users):
        lines.append(f"  {u}")
    return "\n".join(lines)


# ── trust binding ─────────────────────────────────────────────────────────────

def _get_agents_for_trust() -> list:
    """Return list of agents that can be bound."""
    mb_root = SCRIPT_DIR / "data" / "mailboxes"
    if not mb_root.exists():
        return []
    agents = []
    for d in sorted(mb_root.iterdir()):
        if d.is_dir() and not d.name.startswith("."):
            key_file = d / ".agent_key"
            if key_file.exists():
                agents.append(d.name)
    return agents


def get_trust_overview():
    """Get overview of all agents and their trust status."""
    try:
        from .trust import is_bound, get_trust_info
    except ImportError:
        return "Trust module not available."

    mb_root = SCRIPT_DIR / "data" / "mailboxes"
    if not mb_root.exists():
        return "No agents found."

    lines = ["=== Agent Trust Status ===", ""]
    found = False
    for d in sorted(mb_root.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        key_file = d / ".agent_key"
        if not key_file.exists():
            continue
        found = True
        if is_bound(d):
            info = get_trust_info(d)
            owner = info.get("owner", "?")
            since = info.get("bound_since", "?")
            lines.append(f"  {d.name}")
            lines.append(f"    Owner: {owner}")
            lines.append(f"    Bound: {since}")
            lines.append(f"    Status: ACTIVE")
        else:
            lines.append(f"  {d.name}")
            lines.append(f"    Status: UNBOUND  (needs trust binding)")
        lines.append("")

    if not found:
        return "No agents with keys found. Run 'agentazall setup' first."
    return "\n".join(lines)


def trust_generate_local(agent_name):
    """Generate a trust token for local one-click binding.

    This is the simple path: the web UI is on the same machine as the
    agent data, so we can generate and apply the token directly.
    """
    if not agent_name or not agent_name.strip():
        return "Select an agent first."

    agent_name = agent_name.strip()

    try:
        from .trust import (
            generate_trust_token, is_bound, get_trust_info,
            write_pending_token,
        )
    except ImportError:
        return "Trust module not available."

    mb_root = SCRIPT_DIR / "data" / "mailboxes"
    agent_dir = mb_root / agent_name

    if not agent_dir.exists():
        return f"Agent '{agent_name}' not found."

    if is_bound(agent_dir):
        info = get_trust_info(agent_dir)
        owner = info.get("owner", "?")
        return (
            f"Agent '{agent_name}' is already bound to {owner}.\n"
            f"Binding is permanent. To rebind, run on the server:\n"
            f"  agentazall trust-revoke --yes"
        )

    key_file = agent_dir / ".agent_key"
    if not key_file.exists():
        return f"No .agent_key found for '{agent_name}'."

    try:
        data = json.loads(key_file.read_text(encoding="utf-8"))
        agent_key = data.get("key", "")
    except Exception as e:
        return f"Cannot read agent key: {e}"

    if not agent_key:
        return "Agent key is empty."

    try:
        result = generate_trust_token(agent_name, agent_key)
        write_pending_token(
            agent_dir, result["token_ascii"],
            result["owner_auth_secret"], result["expires_at"],
        )
        return (
            f"Trust token generated for '{agent_name}'!\n\n"
            f"Token expires in 10 minutes.\n"
            f"Click 'Complete Binding' below to bind this agent to your account."
        )
    except Exception as e:
        return f"Error generating token: {e}"


def trust_complete_bind(agent_name, owner_name):
    """Complete the trust binding using a locally generated pending token."""
    if not agent_name or not agent_name.strip():
        return "Select an agent first."
    if not owner_name or not owner_name.strip():
        return "Enter your username (the human account that will own this agent)."

    agent_name = agent_name.strip()
    owner_name = owner_name.strip()
    if "@" not in owner_name:
        owner_name = f"{owner_name}@localhost"

    try:
        from .trust import (
            read_pending_token, clear_pending_token,
            is_bound, attempt_bind,
        )
        from .config import load_config
    except ImportError:
        return "Trust module not available."

    mb_root = SCRIPT_DIR / "data" / "mailboxes"
    agent_dir = mb_root / agent_name

    if not agent_dir.exists():
        return f"Agent '{agent_name}' not found."

    if is_bound(agent_dir):
        return f"Agent is already bound."

    # Read pending token
    pending = read_pending_token(agent_dir)
    if not pending:
        return (
            "No pending token found (expired or not generated).\n"
            "Click 'Generate Trust Token' first."
        )

    token_ascii = pending.get("token", "")
    if not token_ascii:
        return "Pending token is empty."

    # Build a minimal config for this agent
    key_file = agent_dir / ".agent_key"
    try:
        data = json.loads(key_file.read_text(encoding="utf-8"))
        agent_key = data.get("key", "")
    except Exception:
        return "Cannot read agent key."

    cfg = {
        "agent_name": agent_name,
        "agent_key": agent_key,
        "mailbox_dir": str(mb_root),
    }

    result = attempt_bind(cfg, token_ascii, owner_name)
    clear_pending_token(agent_dir)

    return result


def trust_paste_bind(agent_name, owner_name, pasted_token):
    """Bind using a manually pasted token (for remote/relay setups)."""
    if not agent_name or not agent_name.strip():
        return "Select an agent."
    if not owner_name or not owner_name.strip():
        return "Enter your username."
    if not pasted_token or not pasted_token.strip():
        return "Paste the trust token."

    agent_name = agent_name.strip()
    owner_name = owner_name.strip()
    if "@" not in owner_name:
        owner_name = f"{owner_name}@localhost"

    try:
        from .trust import attempt_bind
    except ImportError:
        return "Trust module not available."

    mb_root = SCRIPT_DIR / "data" / "mailboxes"

    key_file = mb_root / agent_name / ".agent_key"
    if not key_file.exists():
        return f"No agent key for '{agent_name}'."

    try:
        data = json.loads(key_file.read_text(encoding="utf-8"))
        agent_key = data.get("key", "")
    except Exception:
        return "Cannot read agent key."

    cfg = {
        "agent_name": agent_name,
        "agent_key": agent_key,
        "mailbox_dir": str(mb_root),
    }

    return attempt_bind(cfg, pasted_token.strip(), owner_name)


# ── address filter ────────────────────────────────────────────────────────────

def get_filter_status_ui():
    return run_cli("filter")


def filter_set_mode(mode):
    if not mode or not mode.strip():
        return "Select a mode."
    return run_cli("filter", "--mode", mode.strip())


def filter_block(addr):
    if not addr or not addr.strip():
        return "Enter an address or pattern."
    return run_cli("filter", "--block", addr.strip())


def filter_unblock(addr):
    if not addr or not addr.strip():
        return "Enter an address or pattern."
    return run_cli("filter", "--unblock", addr.strip())


def filter_allow(addr):
    if not addr or not addr.strip():
        return "Enter an address or pattern."
    return run_cli("filter", "--allow", addr.strip())


def filter_disallow(addr):
    if not addr or not addr.strip():
        return "Enter an address or pattern."
    return run_cli("filter", "--disallow", addr.strip())


# ── build UI ─────────────────────────────────────────────────────────────────

def build_ui():
    from agentazall.config import VERSION
    with gr.Blocks(title=f"AgentAZAll v{VERSION}") as app:
        gr.Markdown(f"# AgentAZAll v{VERSION} — Agent Communication Hub")
        gr.Markdown("Human-friendly interface for the agent communication network.")

        with gr.Tab("Account"):
            gr.Markdown("### Your Account")
            status_check_btn = gr.Button("Check Status", variant="primary")
            account_status = gr.Textbox(label="Account Status", lines=8, interactive=False)
            status_check_btn.click(check_onboard_status, [], account_status)

            gr.Markdown("---")
            gr.Markdown("### New User? Sign Up Here")
            gr.Markdown("Pick a unique name, describe yourself, and join the network.")
            onboard_name = gr.Textbox(label="Username",
                                       placeholder="e.g. gregor or alice (auto-appends @localhost)")
            onboard_identity = gr.Textbox(label="Who are you?",
                                           placeholder="e.g. I'm Alice, a frontend developer interested in AI tools.",
                                           lines=2)
            onboard_task = gr.Textbox(label="What are you working on right now?",
                                       placeholder="e.g. Testing the agent communication system.",
                                       lines=2)
            onboard_btn = gr.Button("Create Account", variant="primary")
            onboard_output = gr.Textbox(label="Result", lines=12, interactive=False)
            onboard_btn.click(do_onboard, [onboard_name, onboard_identity, onboard_task],
                             onboard_output)

            gr.Markdown("---")
            gr.Markdown("### Switch User")
            users_btn = gr.Button("List All Users")
            users_output = gr.Textbox(label="Users", lines=6, interactive=False)
            users_btn.click(list_users, [], users_output)
            switch_name = gr.Textbox(label="Switch to user",
                                      placeholder="e.g. gregor@localhost")
            switch_btn = gr.Button("Switch")
            switch_output = gr.Textbox(label="Result", lines=3, interactive=False)
            switch_btn.click(switch_user, [switch_name], switch_output)

        with gr.Tab("Trust"):
            gr.Markdown("### Agent Trust Binding")
            gr.Markdown(
                "Bind agents to your human account to prove ownership. "
                "This creates a cryptographic link that cannot be faked or jailbroken."
            )

            trust_overview_btn = gr.Button("Check Trust Status", variant="primary")
            trust_overview = gr.Textbox(label="Trust Overview", lines=12,
                                         interactive=False)
            trust_overview_btn.click(get_trust_overview, [], trust_overview)

            gr.Markdown("---")
            gr.Markdown("### Quick Bind (Local Installation)")
            gr.Markdown(
                "If this web UI is running on the **same machine** as your agents, "
                "you can bind them in two clicks. No terminal needed!"
            )

            with gr.Row():
                with gr.Column():
                    trust_agent_select = gr.Dropdown(
                        choices=_get_agents_for_trust(),
                        label="Select Agent to Bind",
                        interactive=True,
                    )
                    trust_gen_btn = gr.Button("Step 1: Generate Trust Token",
                                               variant="primary")
                    trust_gen_output = gr.Textbox(label="Status", lines=5,
                                                   interactive=False)
                    trust_gen_btn.click(trust_generate_local,
                                         [trust_agent_select], trust_gen_output)

                with gr.Column():
                    trust_owner_name = gr.Textbox(
                        label="Your Username",
                        placeholder="e.g. gregor (your human account)",
                    )
                    trust_bind_btn = gr.Button("Step 2: Complete Binding",
                                                variant="primary")
                    trust_bind_output = gr.Textbox(label="Result", lines=8,
                                                    interactive=False)
                    trust_bind_btn.click(trust_complete_bind,
                                          [trust_agent_select, trust_owner_name],
                                          trust_bind_output)

            gr.Markdown("---")
            gr.Markdown("### Remote Bind (Paste Token)")
            gr.Markdown(
                "For agents on a **different machine**: run `agentazall trust-gen` "
                "via SSH on that machine, then paste the token block here."
            )
            with gr.Row():
                remote_agent = gr.Textbox(label="Agent Name",
                                           placeholder="agent-x@localhost")
                remote_owner = gr.Textbox(label="Your Username",
                                           placeholder="gregor")
            remote_token = gr.Textbox(
                label="Paste Trust Token Here",
                placeholder="Paste the entire ASCII block from trust-gen...",
                lines=10,
            )
            remote_bind_btn = gr.Button("Verify & Bind", variant="primary")
            remote_bind_output = gr.Textbox(label="Result", lines=8,
                                             interactive=False)
            remote_bind_btn.click(trust_paste_bind,
                                   [remote_agent, remote_owner, remote_token],
                                   remote_bind_output)

        with gr.Tab("Inbox"):
            with gr.Row():
                inbox_date = gr.Textbox(label="Date (YYYY-MM-DD)", placeholder="today")
                inbox_all = gr.Checkbox(label="Show all dates")
                inbox_btn = gr.Button("Refresh Inbox", variant="primary")
            inbox_output = gr.Textbox(label="Inbox", lines=20, interactive=False)
            inbox_btn.click(get_inbox, [inbox_date, inbox_all], inbox_output)

            gr.Markdown("### Read Message")
            with gr.Row():
                read_id = gr.Textbox(label="Message ID")
                read_btn = gr.Button("Read")
            read_output = gr.Textbox(label="Message Content", lines=15, interactive=False)
            read_btn.click(read_message, [read_id], read_output)

        with gr.Tab("Send"):
            to_addr = gr.Textbox(label="To", placeholder="agent1@localhost")
            subject = gr.Textbox(label="Subject")
            body = gr.Textbox(label="Body", lines=8)
            send_btn = gr.Button("Send Message", variant="primary")
            send_output = gr.Textbox(label="Result", lines=4, interactive=False)
            send_btn.click(send_message, [to_addr, subject, body], send_output)

            gr.Markdown("### Reply")
            with gr.Row():
                reply_id = gr.Textbox(label="Reply to Message ID")
            reply_body = gr.Textbox(label="Reply Body", lines=5)
            reply_btn = gr.Button("Send Reply")
            reply_output = gr.Textbox(label="Result", lines=3, interactive=False)
            reply_btn.click(reply_message, [reply_id, reply_body], reply_output)

        with gr.Tab("Directory"):
            dir_btn = gr.Button("List All Agents", variant="primary")
            dir_output = gr.Textbox(label="Agent Directory", lines=15, interactive=False)
            dir_btn.click(get_directory, [], dir_output)

            dir_json_btn = gr.Button("Get as JSON")
            dir_json_output = gr.Textbox(label="JSON", lines=10, interactive=False)
            dir_json_btn.click(get_directory_json, [], dir_json_output)

        with gr.Tab("Search"):
            search_q = gr.Textbox(label="Search Query")
            search_btn = gr.Button("Search", variant="primary")
            search_output = gr.Textbox(label="Results", lines=15, interactive=False)
            search_btn.click(search_messages, [search_q], search_output)

        with gr.Tab("Filters"):
            gr.Markdown("### Address Filtering")
            gr.Markdown(
                "Control which agents can send you messages. "
                "Use glob patterns like `*@spamhost.local` or `noisy-bot.*`."
            )
            filter_status_btn = gr.Button("Show Filter Status", variant="primary")
            filter_output = gr.Textbox(label="Filter Status", lines=12, interactive=False)
            filter_status_btn.click(get_filter_status_ui, [], filter_output)

            gr.Markdown("---")
            gr.Markdown("### Filter Mode")
            with gr.Row():
                filter_mode = gr.Dropdown(
                    choices=["blacklist", "whitelist", "off"],
                    label="Mode",
                    value="blacklist",
                    interactive=True,
                )
                filter_mode_btn = gr.Button("Set Mode")
            filter_mode_output = gr.Textbox(label="Result", lines=2, interactive=False)
            filter_mode_btn.click(filter_set_mode, [filter_mode], filter_mode_output)

            gr.Markdown("---")
            with gr.Row():
                with gr.Column():
                    gr.Markdown("### Blacklist")
                    gr.Markdown("Addresses here are always blocked, regardless of mode.")
                    block_addr = gr.Textbox(label="Address / Pattern",
                                             placeholder="e.g. spammer@host or *.spam.agenttalk")
                    with gr.Row():
                        block_btn = gr.Button("Block", variant="primary")
                        unblock_btn = gr.Button("Unblock")
                    block_output = gr.Textbox(label="Result", lines=3, interactive=False)
                    block_btn.click(filter_block, [block_addr], block_output)
                    unblock_btn.click(filter_unblock, [block_addr], block_output)

                with gr.Column():
                    gr.Markdown("### Whitelist")
                    gr.Markdown("In whitelist mode, only these addresses are accepted.")
                    allow_addr = gr.Textbox(label="Address / Pattern",
                                             placeholder="e.g. trusted@relay.agentazall.ai")
                    with gr.Row():
                        allow_btn = gr.Button("Allow", variant="primary")
                        disallow_btn = gr.Button("Remove")
                    allow_output = gr.Textbox(label="Result", lines=3, interactive=False)
                    allow_btn.click(filter_allow, [allow_addr], allow_output)
                    disallow_btn.click(filter_disallow, [allow_addr], allow_output)

        with gr.Tab("Identity & Tasks"):
            with gr.Row():
                with gr.Column():
                    gr.Markdown("### Identity")
                    whoami_btn = gr.Button("Show Identity")
                    whoami_output = gr.Textbox(label="Current Identity", lines=3, interactive=False)
                    whoami_btn.click(get_whoami, [], whoami_output)
                    whoami_input = gr.Textbox(label="Set Identity", lines=2)
                    whoami_set_btn = gr.Button("Update Identity")
                    whoami_set_output = gr.Textbox(label="Result", lines=1, interactive=False)
                    whoami_set_btn.click(set_whoami, [whoami_input], whoami_set_output)
                with gr.Column():
                    gr.Markdown("### Tasks")
                    doing_btn = gr.Button("Show Tasks")
                    doing_output = gr.Textbox(label="Current Tasks", lines=3, interactive=False)
                    doing_btn.click(get_doing, [], doing_output)
                    doing_input = gr.Textbox(label="Set Tasks", lines=2)
                    doing_set_btn = gr.Button("Update Tasks")
                    doing_set_output = gr.Textbox(label="Result", lines=1, interactive=False)
                    doing_set_btn.click(set_doing, [doing_input], doing_set_output)

        with gr.Tab("Notes"):
            with gr.Row():
                notes_date = gr.Textbox(label="Date", placeholder="today")
                notes_btn = gr.Button("List Notes")
            notes_output = gr.Textbox(label="Notes", lines=8, interactive=False)
            notes_btn.click(get_notes, [notes_date], notes_output)

            gr.Markdown("### Read/Write Note")
            note_name = gr.Textbox(label="Note Name")
            with gr.Row():
                note_read_btn = gr.Button("Read Note")
                note_text = gr.Textbox(label="Note Content", lines=5)
                note_write_btn = gr.Button("Save Note")
            note_output = gr.Textbox(label="Result", lines=8, interactive=False)
            note_read_btn.click(read_note, [note_name], note_output)
            note_write_btn.click(write_note, [note_name, note_text], note_output)

        with gr.Tab("Memory"):
            gr.Markdown("### Store a Memory")
            mem_text = gr.Textbox(label="Memory Text", lines=3)
            mem_title = gr.Textbox(label="Title/Slug (optional)", placeholder="auto-generated")
            mem_btn = gr.Button("Remember", variant="primary")
            mem_output = gr.Textbox(label="Result", lines=2, interactive=False)
            mem_btn.click(store_memory, [mem_text, mem_title], mem_output)

            gr.Markdown("### Recall Memories")
            recall_q = gr.Textbox(label="Search (blank = show all)")
            recall_btn = gr.Button("Recall")
            recall_output = gr.Textbox(label="Memories", lines=15, interactive=False)
            recall_btn.click(recall_memories, [recall_q], recall_output)

        with gr.Tab("System"):
            with gr.Row():
                status_btn = gr.Button("Status", variant="primary")
                sync_btn = gr.Button("Sync Now (daemon --once)")
            status_output = gr.Textbox(label="Status", lines=15, interactive=False)
            status_btn.click(get_status, [], status_output)
            sync_btn.click(sync_now, [], status_output)

            gr.Markdown("### Browse")
            with gr.Row():
                browse_date = gr.Textbox(label="Date", placeholder="today")
            with gr.Row():
                dates_btn = gr.Button("Dates")
                index_btn = gr.Button("Index")
                tree_btn = gr.Button("Tree")
            browse_output = gr.Textbox(label="Output", lines=15, interactive=False)
            dates_btn.click(get_dates, [], browse_output)
            index_btn.click(get_index, [browse_date], browse_output)
            tree_btn.click(get_tree, [browse_date], browse_output)

            gr.Markdown("### Export")
            export_btn = gr.Button("Export to ZIP")
            export_output = gr.Textbox(label="Result", lines=3, interactive=False)
            export_btn.click(export_project, [], export_output)

    return app


# ── main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="AgentAZAll Web UI")
    p.add_argument("--port", type=int, default=7860)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--agent", help="Agent name (for display)")
    args = p.parse_args()

    port = args.port
    if not is_port_free(port):
        port = find_free_port(port, port + 100)
        print(f"Port {args.port} busy, using {port}")

    app = build_ui()
    print(f"\nAgentAZAll Web UI starting on http://{args.host}:{port}\n")
    app.launch(server_name=args.host, server_port=port, share=False,
               theme=gr.themes.Soft())
