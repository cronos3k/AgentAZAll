#!/usr/bin/env python3
"""
AgentoAll Web UI -- Gradio-based interface for human participants.

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

# Detect CLI command: prefer pip-installed 'agentoall', fall back to module invocation

if _shutil.which("agentoall"):
    CLI = ["agentoall"]
else:
    CLI = [sys.executable, "-m", "agentoall"]

# Config: check env, then cwd, then script dir
_config_env = os.environ.get("AGENTOALL_CONFIG")
if _config_env:
    HUMAN_CONFIG = Path(_config_env)
elif (Path.cwd() / "config_human.json").exists():
    HUMAN_CONFIG = Path.cwd() / "config_human.json"
else:
    HUMAN_CONFIG = SCRIPT_DIR / "config_human.json"


def run_cli(*args):
    """Run an agentoall CLI command using the human config and return stdout."""
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
    return (f"Welcome to AgentoAll, {name}!\n\n"
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


# ── build UI ─────────────────────────────────────────────────────────────────

def build_ui():
    with gr.Blocks(title="AgentoAll") as app:
        gr.Markdown("# AgentoAll -- Agent Communication Hub")
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
    p = argparse.ArgumentParser(description="AgentoAll Web UI")
    p.add_argument("--port", type=int, default=7860)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--agent", help="Agent name (for display)")
    args = p.parse_args()

    port = args.port
    if not is_port_free(port):
        port = find_free_port(port, port + 100)
        print(f"Port {args.port} busy, using {port}")

    app = build_ui()
    print(f"\nAgentoAll Web UI starting on http://{args.host}:{port}\n")
    app.launch(server_name=args.host, server_port=port, share=False,
               theme=gr.themes.Soft())
