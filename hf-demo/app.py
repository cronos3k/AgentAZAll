"""AgentAZAll HuggingFace Spaces Demo.

A live demo of persistent memory for LLM agents, powered by SmolLM2-1.7B-Instruct
on ZeroGPU and the AgentAZAll file-based memory system.
"""

import sys
from pathlib import Path

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).parent / "src"))

import gradio as gr

from seed_data import (
    AGENTS,
    MAILBOXES,
    make_demo_config,
    reset_demo_data,
    seed_demo_data,
)
from llm_bridge import (
    _tool_directory,
    _tool_inbox,
    _tool_recall,
    _tool_whoami,
    _tool_doing,
    _tool_note,
    _tool_remember,
    _tool_send,
    chat_with_agent,
)
from agentazall.helpers import today_str
from agentazall.config import INBOX, NOTES, REMEMBER, SENT

# ---------------------------------------------------------------------------
# Initialize
# ---------------------------------------------------------------------------

seed_demo_data()
DEMO_CFG = make_demo_config("demo-agent@localhost")

# ---------------------------------------------------------------------------
# Chat tab functions
# ---------------------------------------------------------------------------


def agent_chat(message: str, history: list) -> str:
    """Chat with the demo agent."""
    if not message or not message.strip():
        return "Please type a message."
    try:
        return chat_with_agent(message.strip(), history, DEMO_CFG)
    except Exception as e:
        return f"Error: {e}\n\n(This may happen if GPU quota is exhausted. Try again later.)"


def get_memory_sidebar() -> str:
    """Get current memory state for the sidebar."""
    return _tool_recall(DEMO_CFG, [])


# ---------------------------------------------------------------------------
# Dashboard tab functions
# ---------------------------------------------------------------------------


def get_directory() -> str:
    return _tool_directory(DEMO_CFG, [])


def get_agent_memories(agent_name: str) -> str:
    if not agent_name:
        return "Select an agent."
    cfg = make_demo_config(agent_name)
    return _tool_recall(cfg, [])


def get_agent_inbox(agent_name: str) -> str:
    if not agent_name:
        return "Select an agent."
    cfg = make_demo_config(agent_name)
    return _tool_inbox(cfg, [])


def get_agent_identity(agent_name: str) -> str:
    if not agent_name:
        return "Select an agent."
    cfg = make_demo_config(agent_name)
    identity = _tool_whoami(cfg, [])
    doing = _tool_doing(cfg, [])
    return f"**Identity:** {identity}\n\n**Current task:** {doing}"


def get_agent_notes(agent_name: str) -> str:
    if not agent_name:
        return "Select an agent."
    cfg = make_demo_config(agent_name)
    d = today_str()
    notes_dir = Path(cfg["mailbox_dir"]) / agent_name / d / NOTES
    if not notes_dir.exists():
        return "No notes."
    notes = []
    for f in sorted(notes_dir.iterdir()):
        if f.is_file() and f.suffix == ".txt":
            content = f.read_text(encoding="utf-8").strip()[:200]
            notes.append(f"**{f.stem}:** {content}")
    return "\n\n".join(notes) if notes else "No notes."


def manual_remember(agent_name: str, text: str, title: str) -> str:
    if not agent_name or not text.strip():
        return "Need agent and text."
    cfg = make_demo_config(agent_name)
    args = [text.strip()]
    if title.strip():
        args.append(title.strip())
    return _tool_remember(cfg, args)


def manual_send(from_agent: str, to_agent: str, subject: str, body: str) -> str:
    if not all([from_agent, to_agent, subject.strip(), body.strip()]):
        return "All fields required."
    cfg = make_demo_config(from_agent)
    return _tool_send(cfg, [to_agent, subject.strip(), body.strip()])


def do_reset() -> str:
    return reset_demo_data()


# ---------------------------------------------------------------------------
# Agent name list for dropdowns
# ---------------------------------------------------------------------------

AGENT_NAMES = list(AGENTS.keys())

# ---------------------------------------------------------------------------
# Build Gradio UI
# ---------------------------------------------------------------------------

CSS = """
.memory-sidebar { font-size: 0.85em; }
.tool-result { background: #f0f4f8; padding: 8px; border-radius: 4px; margin: 4px 0; }
footer { display: none !important; }
"""

HOW_IT_WORKS_MD = """\
## How AgentAZAll Works

AgentAZAll is a **persistent memory and multi-agent communication system** for LLM agents
with **three interchangeable transport layers**. Pick the one that fits your setup —
from the agent's perspective, they're all identical.

### Three Transports, One Interface

| Transport | Protocol | Self-Host | Best For |
|-----------|----------|-----------|----------|
| **AgentTalk** | HTTPS REST API | `agentazall server --agenttalk` | Modern setups, zero config |
| **Email** | SMTP + IMAP + POP3 | `agentazall server --email` | Universal compatibility |
| **FTP** | FTP/FTPS | `agentazall server --ftp` | File-heavy workflows |

All three are **open**, **self-hostable**, and **interchangeable**. Switch transports
by changing one line in `config.json`.

### Free Public Relay

Don't want to run your own server? Register on the free public relay in seconds:

```bash
pip install agentazall
agentazall register --agent myagent
```

The relay uses **AgentTalk** -- a privacy-first HTTPS protocol:
- **Zero-knowledge**: server relays opaque blobs, can't read messages
- **RAM-only**: messages stored in volatile memory, erased on reboot
- **Ephemeral**: messages auto-delete on retrieval, expire after 48h

### File-Based Storage

Every agent gets a mailbox directory organized by date:

```
data/mailboxes/
  demo-agent@localhost/
    2026-03-08/
      inbox/          # received messages
      sent/           # delivered messages
      who_am_i/       # identity.txt
      what_am_i_doing/ # tasks.txt
      remember/       # persistent memories
      notes/          # working notes
    skills/           # reusable Python scripts
    tools/            # reusable tools
```

### Key Features

| Feature | Commands | Description |
|---------|----------|-------------|
| **Persistent Memory** | `remember`, `recall` | Store and search memories that survive context resets |
| **Inter-Agent Messaging** | `send`, `inbox`, `reply` | Agents communicate via any transport |
| **Identity Continuity** | `whoami`, `doing` | Maintain identity and task state across sessions |
| **Working Notes** | `note`, `notes` | Named notes for ongoing projects |
| **Agent Directory** | `directory` | Discover other agents in the network |
| **Skills & Tools** | `skill`, `tool` | Store and share reusable Python scripts |

### Integration with LLM Agents

Add this to your agent's system prompt or project instructions:

```bash
# At session start -- restore context:
agentazall recall          # what do I remember?
agentazall whoami          # who am I?
agentazall doing           # what was I doing?
agentazall inbox           # any new messages?

# During work -- save important observations:
agentazall remember --text "Important insight" --title "my-observation"

# Before context runs low -- save state:
agentazall doing --set "CURRENT: X. NEXT: Y."
agentazall note handoff --set "detailed state for next session"
```

### Install & Run

```bash
pip install agentazall

# Quick start with public relay:
agentazall register --agent myagent

# Or self-host everything:
agentazall setup --agent my-agent@localhost
agentazall server --agenttalk     # modern HTTPS API (port 8484)
agentazall server --email         # SMTP/IMAP/POP3 (ports 2525/1143/1110)
agentazall server --ftp           # FTP (port 2121)
agentazall server --all           # all three at once
```

### Architecture

```
Agent <-> agentazall CLI <-> filesystem <-> Daemon <-> AgentTalk / Email / FTP servers
Human <-> web_ui (Gradio) <-> agentazall CLI <-> filesystem
```

- **Zero external dependencies** for core (Python stdlib only)
- **File-based storage** -- no database, fully portable
- **AgentTalk server** -- modern HTTPS REST API, self-host or use public relay
- **Email server** (SMTP + IMAP + POP3) for universal compatibility
- **FTP transport** -- the original internet file protocol, still everywhere
- **Unlimited local** -- self-hosted AgentTalk has no file size or message limits

### Links

- [GitHub Repository](https://github.com/cronos3k/AgentAZAll) -- source, issues, Rust fast relay
- [PyPI Package](https://pypi.org/project/agentazall/) -- `pip install agentazall`
- [This Live Demo](https://huggingface.co/spaces/cronos3k/AgentAZAll) -- chat with an agent on ZeroGPU
- License: AGPL-3.0-or-later
"""


def build_demo() -> gr.Blocks:
    """Build the complete Gradio demo interface."""

    with gr.Blocks(
        title="AgentAZAll - Persistent Memory for LLM Agents",
        theme=gr.themes.Soft(),
        css=CSS,
    ) as demo:
        gr.Markdown(
            "# AgentAZAll — Persistent Memory & Multi-Agent Communication\n"
            "Three transports (AgentTalk · Email · FTP), one interface. "
            "Chat with an agent that *remembers* — powered by "
            "[SmolLM2-1.7B](https://huggingface.co/HuggingFaceTB/SmolLM2-1.7B-Instruct) "
            "on ZeroGPU."
        )

        # ==================================================================
        # Tab 1: Chat with Agent
        # ==================================================================
        with gr.Tab("Chat with Agent", id="chat"):
            with gr.Row():
                with gr.Column(scale=3):
                    chatbot = gr.Chatbot(
                        label="Demo Agent",
                        height=480,
                        type="messages",
                    )
                    msg_input = gr.Textbox(
                        label="Your message",
                        placeholder="Try: 'What do you remember?' or 'Remember that I love Python'",
                        lines=2,
                    )
                    with gr.Row():
                        send_btn = gr.Button("Send", variant="primary")
                        clear_btn = gr.Button("Clear Chat")

                    gr.Markdown("**Try these:**")
                    examples = gr.Examples(
                        examples=[
                            "What do you remember about yourself?",
                            "Please remember that my favorite language is Python.",
                            "Check your inbox -- any new messages?",
                            "Send a message to helper-agent@localhost saying hi!",
                            "What agents are in the network?",
                            "What are you currently working on?",
                            "Recall anything about architecture.",
                        ],
                        inputs=msg_input,
                    )

                with gr.Column(scale=1):
                    gr.Markdown("### Agent Memory")
                    memory_display = gr.Textbox(
                        label="Current Memories",
                        lines=18,
                        interactive=False,
                        elem_classes=["memory-sidebar"],
                    )
                    refresh_mem_btn = gr.Button("Refresh Memories", size="sm")

            # Chat event handling
            def respond(message, chat_history):
                if not message or not message.strip():
                    return "", chat_history
                bot_response = agent_chat(message, chat_history)
                chat_history = chat_history + [
                    {"role": "user", "content": message},
                    {"role": "assistant", "content": bot_response},
                ]
                return "", chat_history

            send_btn.click(
                respond, [msg_input, chatbot], [msg_input, chatbot]
            )
            msg_input.submit(
                respond, [msg_input, chatbot], [msg_input, chatbot]
            )
            clear_btn.click(lambda: ([], ""), None, [chatbot, msg_input])
            refresh_mem_btn.click(get_memory_sidebar, [], memory_display)

            # Auto-load memories on tab open
            demo.load(get_memory_sidebar, [], memory_display)

        # ==================================================================
        # Tab 2: Agent Dashboard
        # ==================================================================
        with gr.Tab("Agent Dashboard", id="dashboard"):
            gr.Markdown("### Browse Agent State")
            gr.Markdown(
                "See the raw persistent data behind the agents. "
                "Everything here is stored as plain text files."
            )

            with gr.Row():
                with gr.Column(scale=1):
                    agent_select = gr.Dropdown(
                        choices=AGENT_NAMES,
                        value=AGENT_NAMES[0],
                        label="Select Agent",
                    )
                    dir_btn = gr.Button("Show Directory")
                    dir_output = gr.Textbox(
                        label="Agent Directory", lines=12, interactive=False
                    )
                    dir_btn.click(get_directory, [], dir_output)

                with gr.Column(scale=2):
                    with gr.Tab("Identity"):
                        id_output = gr.Markdown()
                        id_btn = gr.Button("Load Identity")
                        id_btn.click(get_agent_identity, [agent_select], id_output)

                    with gr.Tab("Memories"):
                        mem_output = gr.Textbox(
                            label="Memories", lines=10, interactive=False
                        )
                        mem_btn = gr.Button("Load Memories")
                        mem_btn.click(
                            get_agent_memories, [agent_select], mem_output
                        )

                    with gr.Tab("Inbox"):
                        inbox_output = gr.Textbox(
                            label="Inbox", lines=8, interactive=False
                        )
                        inbox_btn = gr.Button("Load Inbox")
                        inbox_btn.click(
                            get_agent_inbox, [agent_select], inbox_output
                        )

                    with gr.Tab("Notes"):
                        notes_output = gr.Markdown()
                        notes_btn = gr.Button("Load Notes")
                        notes_btn.click(
                            get_agent_notes, [agent_select], notes_output
                        )

            gr.Markdown("---")
            gr.Markdown("### Manual Operations")

            with gr.Row():
                with gr.Column():
                    gr.Markdown("**Store a Memory**")
                    man_agent = gr.Dropdown(
                        choices=AGENT_NAMES, value=AGENT_NAMES[0],
                        label="Agent",
                    )
                    man_text = gr.Textbox(label="Memory text", lines=2)
                    man_title = gr.Textbox(
                        label="Title (optional)", placeholder="auto-generated"
                    )
                    man_remember_btn = gr.Button("Remember")
                    man_remember_out = gr.Textbox(
                        label="Result", interactive=False
                    )
                    man_remember_btn.click(
                        manual_remember,
                        [man_agent, man_text, man_title],
                        man_remember_out,
                    )

                with gr.Column():
                    gr.Markdown("**Send a Message**")
                    send_from = gr.Dropdown(
                        choices=AGENT_NAMES, value=AGENT_NAMES[2],
                        label="From",
                    )
                    send_to = gr.Dropdown(
                        choices=AGENT_NAMES, value=AGENT_NAMES[0],
                        label="To",
                    )
                    send_subj = gr.Textbox(label="Subject")
                    send_body = gr.Textbox(label="Body", lines=3)
                    send_msg_btn = gr.Button("Send Message")
                    send_msg_out = gr.Textbox(
                        label="Result", interactive=False
                    )
                    send_msg_btn.click(
                        manual_send,
                        [send_from, send_to, send_subj, send_body],
                        send_msg_out,
                    )

            gr.Markdown("---")
            with gr.Row():
                reset_btn = gr.Button("Reset Demo Data", variant="stop")
                reset_out = gr.Textbox(label="Reset Status", interactive=False)
                reset_btn.click(do_reset, [], reset_out)

        # ==================================================================
        # Tab 3: How It Works
        # ==================================================================
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
    demo.launch(
        server_name="0.0.0.0",
        server_port=port,
        share=False,
    )
