"""AgentAZAll HuggingFace Spaces Demo — Dual-Agent Live Demo.

Two AI agents (Qwen2.5-3B + SmolLM2-1.7B) collaborate in real-time.
The center panel shows the raw filesystem as files are created — proving
that AgentAZAll's memory and messaging is just plain text files.
"""

import sys
import time
from pathlib import Path
from typing import Generator

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).parent / "src"))

import gradio as gr

# Gradio version compatibility
_GRADIO_MAJOR = int(gr.__version__.split(".")[0])

from seed_data import (
    AGENT_NAMES,
    AGENTS,
    MAILBOXES,
    make_demo_config,
    reset_demo_data,
    seed_demo_data,
)
from llm_bridge import (
    _tool_inbox,
    _tool_recall,
    _tool_whoami,
    _tool_doing,
    generate_response,
)
from agentazall.helpers import today_str
from agentazall.messages import parse_headers_only

# ---------------------------------------------------------------------------
# Initialize
# ---------------------------------------------------------------------------

seed_demo_data()
ALPHA_CFG = make_demo_config("agent-alpha@localhost")
BETA_CFG = make_demo_config("agent-beta@localhost")


# ---------------------------------------------------------------------------
# Filesystem browser functions
# ---------------------------------------------------------------------------

def build_tree_string() -> str:
    """Generate a Unix tree-style view of demo_data/mailboxes/ with annotations."""
    if not MAILBOXES.exists():
        return "(no data yet)"

    lines = ["mailboxes/"]

    agents = sorted(d for d in MAILBOXES.iterdir() if d.is_dir() and not d.name.startswith("."))
    for ai, agent_dir in enumerate(agents):
        is_last_agent = (ai == len(agents) - 1)
        agent_prefix = "└── " if is_last_agent else "├── "
        agent_indent = "    " if is_last_agent else "│   "
        lines.append(f"{agent_prefix}{agent_dir.name}/")

        # Date directories
        date_dirs = sorted(
            (d for d in agent_dir.iterdir()
             if d.is_dir() and not d.name.startswith(".")),
            reverse=True,
        )
        for di, date_dir in enumerate(date_dirs):
            is_last_date = (di == len(date_dirs) - 1)
            date_prefix = f"{agent_indent}└── " if is_last_date else f"{agent_indent}├── "
            date_indent = f"{agent_indent}    " if is_last_date else f"{agent_indent}│   "
            lines.append(f"{date_prefix}{date_dir.name}/")

            # Subdirectories (inbox, sent, remember, etc.)
            subdirs = sorted(d for d in date_dir.iterdir() if d.is_dir())
            for si, sub_dir in enumerate(subdirs):
                is_last_sub = (si == len(subdirs) - 1)
                sub_prefix = f"{date_indent}└── " if is_last_sub else f"{date_indent}├── "
                sub_indent = f"{date_indent}    " if is_last_sub else f"{date_indent}│   "

                # Count files
                files = sorted(f for f in sub_dir.iterdir() if f.is_file() and f.suffix == ".txt")
                if not files:
                    lines.append(f"{sub_prefix}{sub_dir.name}/  (empty)")
                    continue

                lines.append(f"{sub_prefix}{sub_dir.name}/")

                for fi, fpath in enumerate(files):
                    is_last_file = (fi == len(files) - 1)
                    file_prefix = f"{sub_indent}└── " if is_last_file else f"{sub_indent}├── "

                    # Annotate based on directory type
                    annotation = ""
                    if sub_dir.name in ("inbox", "sent", "outbox"):
                        try:
                            headers = parse_headers_only(fpath)
                            if headers:
                                fr = headers.get("From", "?").split("@")[0]
                                to = headers.get("To", "?").split("@")[0]
                                subj = headers.get("Subject", "")[:40]
                                if sub_dir.name == "inbox":
                                    annotation = f"  ← From: {fr} | {subj}"
                                else:
                                    annotation = f"  → To: {to} | {subj}"
                        except Exception:
                            pass
                    elif sub_dir.name == "remember":
                        try:
                            preview = fpath.read_text(encoding="utf-8").strip()[:50]
                            annotation = f"  [{preview}...]" if len(preview) >= 50 else f"  [{preview}]"
                        except Exception:
                            pass

                    lines.append(f"{file_prefix}{fpath.name}{annotation}")

    return "\n".join(lines)


def list_all_files() -> list[str]:
    """Return list of all file paths relative to MAILBOXES for the dropdown."""
    if not MAILBOXES.exists():
        return []
    files = []
    for fpath in sorted(MAILBOXES.rglob("*.txt")):
        rel = fpath.relative_to(MAILBOXES)
        files.append(str(rel))
    return files


def read_file_content(rel_path: str) -> str:
    """Read raw content of a file selected from the dropdown."""
    if not rel_path:
        return "(select a file from the dropdown)"
    fpath = MAILBOXES / rel_path
    if not fpath.exists():
        return f"(file not found: {rel_path})"
    try:
        content = fpath.read_text(encoding="utf-8")
        return f"# {rel_path}\n# Size: {fpath.stat().st_size} bytes\n{'─' * 60}\n{content}"
    except Exception as e:
        return f"Error reading {rel_path}: {e}"


def get_latest_modified_file() -> tuple[str, str]:
    """Find the most recently modified .txt file, return (rel_path, content)."""
    if not MAILBOXES.exists():
        return "", "(no files yet)"
    latest = None
    latest_time = 0
    for fpath in MAILBOXES.rglob("*.txt"):
        mtime = fpath.stat().st_mtime
        if mtime > latest_time:
            latest_time = mtime
            latest = fpath
    if latest is None:
        return "", "(no files yet)"
    rel = str(latest.relative_to(MAILBOXES))
    return rel, read_file_content(rel)


def refresh_filesystem():
    """Return updated tree, file list, and latest file content."""
    tree = build_tree_string()
    files = list_all_files()
    latest_path, latest_content = get_latest_modified_file()
    return tree, gr.Dropdown(choices=files, value=latest_path), latest_content


# ---------------------------------------------------------------------------
# Chat functions
# ---------------------------------------------------------------------------

def chat_alpha(message: str, alpha_history: list):
    """Send message to Agent Alpha, return updated state."""
    if not message or not message.strip():
        tree, file_dd, file_content = refresh_filesystem()
        return "", alpha_history, tree, file_dd, file_content
    try:
        response = generate_response("alpha", message.strip(), alpha_history, ALPHA_CFG)
    except Exception as e:
        response = f"Error: {e}\n\n(GPU quota may be exhausted. Try again later.)"
    alpha_history = alpha_history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": response},
    ]
    tree, file_dd, file_content = refresh_filesystem()
    return "", alpha_history, tree, file_dd, file_content


def chat_beta(message: str, beta_history: list):
    """Send message to Agent Beta, return updated state."""
    if not message or not message.strip():
        tree, file_dd, file_content = refresh_filesystem()
        return "", beta_history, tree, file_dd, file_content
    try:
        response = generate_response("beta", message.strip(), beta_history, BETA_CFG)
    except Exception as e:
        response = f"Error: {e}\n\n(GPU quota may be exhausted. Try again later.)"
    beta_history = beta_history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": response},
    ]
    tree, file_dd, file_content = refresh_filesystem()
    return "", beta_history, tree, file_dd, file_content


# ---------------------------------------------------------------------------
# Autopilot
# ---------------------------------------------------------------------------

def _build_autopilot_prompt(cfg: dict, turn: int, is_first: bool) -> str:
    """Build the prompt that drives an agent's autopilot turn."""
    if is_first:
        return (
            "Check your inbox for messages and respond to the most recent one. "
            "Share your thoughts on the topic, ask a follow-up question, and "
            "use [TOOL: remember] to store any important insights. "
            "Send your reply with [TOOL: send]."
        )
    return (
        "Check your inbox for new messages and respond to the latest one. "
        "Build on the previous discussion — share a new idea or observation. "
        "Remember important insights. Keep the conversation productive and "
        "send a thoughtful reply."
    )


def autopilot_loop(
    alpha_history: list,
    beta_history: list,
    max_turns: int,
) -> Generator:
    """Alternating agent conversation. Yields UI updates after each turn."""

    for turn in range(int(max_turns)):
        # --- Alpha's turn ---
        prompt = _build_autopilot_prompt(ALPHA_CFG, turn, turn == 0)
        status = f"⏳ Turn {turn + 1}/{int(max_turns)}: Agent Alpha thinking..."

        try:
            alpha_resp = generate_response("alpha", prompt, alpha_history, ALPHA_CFG)
        except Exception as e:
            alpha_resp = f"Error: {e}"

        alpha_history = alpha_history + [
            {"role": "user", "content": f"[Autopilot turn {turn + 1}]"},
            {"role": "assistant", "content": alpha_resp},
        ]

        tree, file_dd, file_content = refresh_filesystem()
        yield (
            alpha_history, beta_history, tree, file_dd, file_content,
            f"⏳ Turn {turn + 1}/{int(max_turns)}: Alpha done. Beta thinking..."
        )

        # --- Beta's turn ---
        prompt = _build_autopilot_prompt(BETA_CFG, turn, turn == 0)

        try:
            beta_resp = generate_response("beta", prompt, beta_history, BETA_CFG)
        except Exception as e:
            beta_resp = f"Error: {e}"

        beta_history = beta_history + [
            {"role": "user", "content": f"[Autopilot turn {turn + 1}]"},
            {"role": "assistant", "content": beta_resp},
        ]

        tree, file_dd, file_content = refresh_filesystem()
        yield (
            alpha_history, beta_history, tree, file_dd, file_content,
            f"✓ Turn {turn + 1}/{int(max_turns)} complete."
        )

    tree, file_dd, file_content = refresh_filesystem()
    yield (
        alpha_history, beta_history, tree, file_dd, file_content,
        f"✅ Autopilot finished ({int(max_turns)} turns). Browse the files above!"
    )


def do_reset():
    """Reset demo data and return clean state."""
    reset_demo_data()
    tree, file_dd, file_content = refresh_filesystem()
    return [], [], tree, file_dd, file_content, "Demo reset. Fresh data seeded."


# ---------------------------------------------------------------------------
# How It Works documentation
# ---------------------------------------------------------------------------

HOW_IT_WORKS_MD = """\
## How AgentAZAll Works

AgentAZAll is a **persistent memory and multi-agent communication system** for LLM agents.
Every piece of state — memories, messages, identity, tasks — is a **plain text file**
on the filesystem. No database. No vector store. Just files you can read with `cat`.

### What You Just Saw

In the Live Demo tab, two AI agents (Qwen2.5-3B and SmolLM2-1.7B) collaborate by
sending messages and storing memories. The center panel shows the **raw filesystem**
— every file created by the agents is visible and readable.

### Three Transports, One Interface

| Transport | Protocol | Self-Host | Best For |
|-----------|----------|-----------|----------|
| **AgentTalk** | HTTPS REST API | `agentazall server --agenttalk` | Modern setups, zero config |
| **Email** | SMTP + IMAP + POP3 | `agentazall server --email` | Universal compatibility |
| **FTP** | FTP/FTPS | `agentazall server --ftp` | File-heavy workflows |

All three are **open**, **self-hostable**, and **interchangeable**. Switch transports
by changing one line in `config.json`. Agents don't care which one delivers their messages.

### File-Based Storage

```
data/mailboxes/
  my-agent@localhost/
    2026-03-13/
      inbox/          # received messages (plain text)
      sent/           # delivered messages
      who_am_i/       # identity.txt
      what_am_i_doing/ # tasks.txt
      remember/       # persistent memories (*.txt)
      notes/          # working notes
```

### Key Features

| Feature | Commands | Description |
|---------|----------|-------------|
| **Persistent Memory** | `remember`, `recall` | Store and search memories that survive context resets |
| **Inter-Agent Messaging** | `send`, `inbox`, `reply` | Agents communicate via any transport |
| **Identity Continuity** | `whoami`, `doing` | Maintain identity and task state across sessions |
| **Ed25519 Signing** | Built-in | Messages are cryptographically signed |
| **Trust Binding** | `trust-gen`, `trust-bind` | Cryptographic owner-agent binding |
| **Zero Dependencies** | Python stdlib only | No external packages for the core |

### Install & Run

```bash
pip install agentazall

# Quick start with public relay:
agentazall register --agent myagent

# Or self-host everything:
agentazall server --agenttalk     # modern HTTPS API
agentazall server --email         # SMTP/IMAP/POP3
agentazall server --ftp           # FTP (yes, from 1971)
agentazall server --all           # all three at once
```

### Links

- [GitHub Repository](https://github.com/cronos3k/AgentAZAll) — source, issues, Rust fast relay
- [Project Page](https://agentazall.ai) — research paper, documentation
- [PyPI Package](https://pypi.org/project/agentazall/) — `pip install agentazall`
- License: AGPL-3.0-or-later
"""


# ---------------------------------------------------------------------------
# Build Gradio UI
# ---------------------------------------------------------------------------

CSS = """
/* Monospace for filesystem displays */
.tree-view textarea, .file-view textarea { font-family: 'Fira Code', 'Consolas', 'Courier New', monospace !important; font-size: 0.82em !important; }

/* Center panel subtle highlight */
.center-panel { border-left: 2px solid #6366f1 !important; border-right: 2px solid #6366f1 !important; padding: 0 8px !important; }

/* Compact chatbot */
.compact-chat .message { font-size: 0.9em !important; }

/* Status bar */
.status-bar { font-weight: bold; }

/* Hide Gradio footer */
footer { display: none !important; }
"""


def _chatbot_kwargs(**extra) -> dict:
    """Build Chatbot kwargs compatible with Gradio 5 and 6."""
    kw = dict(extra)
    if _GRADIO_MAJOR < 6:
        kw["type"] = "messages"
    return kw


def build_demo() -> gr.Blocks:
    """Build the complete Gradio demo interface."""

    blocks_kw: dict = {"title": "AgentAZAll — Dual-Agent Live Demo"}
    if _GRADIO_MAJOR < 6:
        blocks_kw["theme"] = gr.themes.Soft()
        blocks_kw["css"] = CSS

    with gr.Blocks(**blocks_kw) as demo:
        gr.Markdown(
            "# 🧠 AgentAZAll v1.0.22 — Dual-Agent Live Demo\n"
            "Two AI agents collaborate in real-time. **Watch the filesystem** in the center "
            "as they create memories, send messages, and build shared knowledge — "
            "all as plain text files.\n\n"
            "*Powered by [Qwen2.5-3B](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct) "
            "and [SmolLM2-1.7B](https://huggingface.co/HuggingFaceTB/SmolLM2-1.7B-Instruct) "
            "on ZeroGPU.*"
        )

        # ==============================================================
        # Tab 1: Live Demo (three-panel)
        # ==============================================================
        with gr.Tab("Live Demo", id="demo"):

            with gr.Row():
                # --- LEFT: Agent Alpha ---
                with gr.Column(scale=2):
                    gr.Markdown("### 🔵 Agent Alpha\n*Qwen2.5-3B · Research Director*")
                    alpha_chatbot = gr.Chatbot(
                        **_chatbot_kwargs(
                            label="Agent Alpha",
                            height=400,
                            elem_classes=["compact-chat"],
                        )
                    )
                    alpha_input = gr.Textbox(
                        label="Message Alpha",
                        placeholder="Ask Alpha something...",
                        lines=2,
                    )
                    alpha_send = gr.Button("Send to Alpha", variant="primary", size="sm")

                # --- CENTER: Filesystem Browser ---
                with gr.Column(scale=3, elem_classes=["center-panel"]):
                    gr.Markdown("### 📁 Live Filesystem\n*Every agent action creates real files*")
                    tree_display = gr.Textbox(
                        label="Directory Tree",
                        lines=20,
                        max_lines=30,
                        interactive=False,
                        elem_classes=["tree-view"],
                    )
                    file_select = gr.Dropdown(
                        label="Select file to view",
                        choices=[],
                        interactive=True,
                    )
                    file_content = gr.Textbox(
                        label="File Content (raw)",
                        lines=10,
                        max_lines=20,
                        interactive=False,
                        elem_classes=["file-view"],
                    )
                    refresh_btn = gr.Button("🔄 Refresh", size="sm")

                # --- RIGHT: Agent Beta ---
                with gr.Column(scale=2):
                    gr.Markdown("### 🟢 Agent Beta\n*SmolLM2-1.7B · Creative Developer*")
                    beta_chatbot = gr.Chatbot(
                        **_chatbot_kwargs(
                            label="Agent Beta",
                            height=400,
                            elem_classes=["compact-chat"],
                        )
                    )
                    beta_input = gr.Textbox(
                        label="Message Beta",
                        placeholder="Ask Beta something...",
                        lines=2,
                    )
                    beta_send = gr.Button("Send to Beta", variant="primary", size="sm")

            # --- Control Bar ---
            gr.Markdown("---")
            with gr.Row():
                autopilot_btn = gr.Button(
                    "▶ Start Autopilot", variant="primary", scale=2,
                )
                stop_btn = gr.Button("■ Stop", variant="stop", scale=1)
                turn_slider = gr.Slider(
                    minimum=1, maximum=10, value=3, step=1,
                    label="Max turns", scale=1,
                )
                status_display = gr.Textbox(
                    label="Status",
                    value="Ready. Chat with either agent or click Start Autopilot.",
                    interactive=False,
                    scale=3,
                    elem_classes=["status-bar"],
                )
                reset_btn = gr.Button("🗑 Reset Demo", variant="stop", scale=1)

            # --- Event Wiring ---

            # Manual chat with Alpha
            alpha_send.click(
                chat_alpha,
                [alpha_input, alpha_chatbot],
                [alpha_input, alpha_chatbot, tree_display, file_select, file_content],
            )
            alpha_input.submit(
                chat_alpha,
                [alpha_input, alpha_chatbot],
                [alpha_input, alpha_chatbot, tree_display, file_select, file_content],
            )

            # Manual chat with Beta
            beta_send.click(
                chat_beta,
                [beta_input, beta_chatbot],
                [beta_input, beta_chatbot, tree_display, file_select, file_content],
            )
            beta_input.submit(
                chat_beta,
                [beta_input, beta_chatbot],
                [beta_input, beta_chatbot, tree_display, file_select, file_content],
            )

            # File viewer
            file_select.change(
                read_file_content,
                [file_select],
                [file_content],
            )

            # Refresh button
            refresh_btn.click(
                refresh_filesystem,
                [],
                [tree_display, file_select, file_content],
            )

            # Autopilot
            autopilot_event = autopilot_btn.click(
                autopilot_loop,
                [alpha_chatbot, beta_chatbot, turn_slider],
                [alpha_chatbot, beta_chatbot, tree_display, file_select, file_content, status_display],
            )
            stop_btn.click(None, cancels=[autopilot_event])

            # Reset
            reset_btn.click(
                do_reset,
                [],
                [alpha_chatbot, beta_chatbot, tree_display, file_select, file_content, status_display],
            )

            # Auto-load filesystem tree on page load
            demo.load(
                refresh_filesystem,
                [],
                [tree_display, file_select, file_content],
            )

        # ==============================================================
        # Tab 2: How It Works
        # ==============================================================
        with gr.Tab("How It Works", id="docs"):
            gr.Markdown(HOW_IT_WORKS_MD)

    return demo


# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------

def _find_free_port(start: int = 7860, end: int = 7960) -> int:
    """Find a free port in the given range."""
    import socket
    for port in range(start, end + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    return start  # fallback


if __name__ == "__main__":
    port = _find_free_port()
    demo = build_demo()
    launch_kw: dict = {
        "server_name": "0.0.0.0",
        "server_port": port,
        "share": False,
    }
    if _GRADIO_MAJOR >= 6:
        launch_kw["theme"] = gr.themes.Soft()
        launch_kw["css"] = CSS
    demo.launch(**launch_kw)
