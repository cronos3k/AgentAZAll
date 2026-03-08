"""LLM <-> AgentAZAll bridge for the HuggingFace Spaces demo.

Connects SmolLM2-1.7B-Instruct to AgentAZAll's persistent memory system
via regex-parsed tool calls.
"""

import re
import sys
from pathlib import Path

# Ensure src/ is on the import path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from agentazall.config import INBOX, NOTES, REMEMBER, SENT
from agentazall.helpers import (
    agent_base,
    agent_day,
    ensure_dirs,
    sanitize,
    today_str,
)
from agentazall.index import build_index, build_remember_index
from agentazall.messages import format_message, parse_headers_only, parse_message

from seed_data import make_demo_config, MAILBOXES

MODEL_ID = "HuggingFaceTB/SmolLM2-1.7B-Instruct"

# Regex for tool calls: [TOOL: command | arg1 | arg2 | ...]
TOOL_PATTERN = re.compile(r"\[TOOL:\s*(\w+)(?:\s*\|\s*(.*?))?\]")


# ---------------------------------------------------------------------------
# Tool implementations (direct filesystem, no subprocess)
# ---------------------------------------------------------------------------

def _tool_remember(cfg: dict, args: list[str]) -> str:
    """Store a persistent memory."""
    if not args:
        return "Error: need text to remember."
    text = args[0].strip()
    title = sanitize(args[1].strip()) if len(args) > 1 and args[1].strip() else "memory"
    if not title.endswith(".txt"):
        title += ".txt"

    d = today_str()
    ensure_dirs(cfg, d)
    mem_dir = agent_day(cfg, d) / REMEMBER
    mem_dir.mkdir(parents=True, exist_ok=True)

    # Avoid overwriting: append counter if exists
    path = mem_dir / title
    if path.exists():
        stem = path.stem
        for i in range(2, 100):
            candidate = mem_dir / f"{stem}-{i}.txt"
            if not candidate.exists():
                path = candidate
                break

    path.write_text(text, encoding="utf-8")
    build_remember_index(cfg)
    return f"Memory stored: {path.stem}"


def _tool_recall(cfg: dict, args: list[str]) -> str:
    """Search/display agent memories."""
    query = args[0].strip().lower() if args and args[0].strip() else ""
    base = agent_base(cfg)
    results = []

    # Walk all date directories looking for remember/ folders
    if base.exists():
        for date_dir in sorted(base.iterdir(), reverse=True):
            rem_dir = date_dir / REMEMBER
            if not rem_dir.is_dir():
                continue
            for f in sorted(rem_dir.iterdir()):
                if not f.is_file() or f.suffix != ".txt":
                    continue
                content = f.read_text(encoding="utf-8").strip()
                if not query or query in content.lower() or query in f.stem.lower():
                    results.append(f"[{date_dir.name}] {f.stem}: {content[:200]}")
            if len(results) >= 20:
                break

    if not results:
        return "No memories found." + (f" (searched for: '{query}')" if query else "")
    return f"Found {len(results)} memories:\n" + "\n".join(results)


def _tool_whoami(cfg: dict, args: list[str]) -> str:
    """Get agent identity."""
    d = today_str()
    path = agent_day(cfg, d) / "who_am_i" / "identity.txt"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return "Identity not set."


def _tool_doing(cfg: dict, args: list[str]) -> str:
    """Get or set current tasks."""
    d = today_str()
    ensure_dirs(cfg, d)
    path = agent_day(cfg, d) / "what_am_i_doing" / "tasks.txt"

    if args and args[0].strip():
        # Set new status
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args[0].strip(), encoding="utf-8")
        return f"Tasks updated: {args[0].strip()[:100]}"

    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return "No current tasks set."


def _tool_note(cfg: dict, args: list[str]) -> str:
    """Read or write a named note."""
    if not args or not args[0].strip():
        return "Error: need note name."
    name = sanitize(args[0].strip())
    if not name.endswith(".txt"):
        name += ".txt"

    d = today_str()
    ensure_dirs(cfg, d)
    note_path = agent_day(cfg, d) / NOTES / name

    if len(args) > 1 and args[1].strip():
        # Write
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text(args[1].strip(), encoding="utf-8")
        return f"Note '{args[0].strip()}' saved."

    # Read
    if note_path.exists():
        return note_path.read_text(encoding="utf-8").strip()
    return f"Note '{args[0].strip()}' not found."


def _tool_send(cfg: dict, args: list[str]) -> str:
    """Send a message to another agent."""
    if len(args) < 3:
        return "Error: need [to | subject | body]."
    to_agent = args[0].strip()
    subject = args[1].strip()
    body = args[2].strip()

    if not to_agent or not subject or not body:
        return "Error: to, subject, and body are all required."

    content, msg_id = format_message(cfg["agent_name"], to_agent, subject, body)

    d = today_str()
    ensure_dirs(cfg, d)

    # Queue in sender's outbox
    outbox = agent_day(cfg, d) / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    (outbox / f"{msg_id}.txt").write_text(content, encoding="utf-8")

    # Direct delivery to recipient's inbox (local demo, no transport needed)
    recipient_inbox = Path(cfg["mailbox_dir"]) / to_agent / d / INBOX
    recipient_inbox.mkdir(parents=True, exist_ok=True)
    (recipient_inbox / f"{msg_id}.txt").write_text(content, encoding="utf-8")

    # Copy to sender's sent
    sent = agent_day(cfg, d) / SENT
    sent.mkdir(parents=True, exist_ok=True)
    (sent / f"{msg_id}.txt").write_text(content, encoding="utf-8")

    return f"Message sent to {to_agent}: '{subject}' (ID: {msg_id})"


def _tool_inbox(cfg: dict, args: list[str]) -> str:
    """List inbox messages."""
    d = today_str()
    inbox_dir = agent_day(cfg, d) / INBOX
    if not inbox_dir.exists():
        return "Inbox is empty."

    messages = []
    for f in sorted(inbox_dir.iterdir(), reverse=True):
        if not f.is_file() or f.suffix != ".txt":
            continue
        headers = parse_headers_only(f)
        if headers:
            fr = headers.get("From", "?")
            subj = headers.get("Subject", "(no subject)")
            messages.append(f"  [{f.stem}] From: {fr} | Subject: {subj}")

    if not messages:
        return "Inbox is empty."
    return f"Inbox ({len(messages)} messages):\n" + "\n".join(messages)


def _tool_directory(cfg: dict, args: list[str]) -> str:
    """List all agents in the network."""
    mb = Path(cfg["mailbox_dir"])
    if not mb.exists():
        return "No agents found."

    agents = []
    for agent_dir in sorted(mb.iterdir()):
        if not agent_dir.is_dir() or agent_dir.name.startswith("."):
            continue
        name = agent_dir.name

        # Find latest date dir with identity (skip non-date dirs like skills/)
        identity = "?"
        doing = "?"
        for date_dir in sorted(agent_dir.iterdir(), reverse=True):
            if not date_dir.is_dir() or not re.match(r"\d{4}-\d{2}-\d{2}$", date_dir.name):
                continue
            id_file = date_dir / "who_am_i" / "identity.txt"
            if id_file.exists():
                identity = id_file.read_text(encoding="utf-8").strip()[:120]
            task_file = date_dir / "what_am_i_doing" / "tasks.txt"
            if task_file.exists():
                doing = task_file.read_text(encoding="utf-8").strip()[:120]
            break

        agents.append(f"  {name}\n    Identity: {identity}\n    Doing: {doing}")

    if not agents:
        return "No agents found."
    return f"Agent Directory ({len(agents)} agents):\n\n" + "\n\n".join(agents)


# Tool dispatch table
TOOL_MAP = {
    "remember": _tool_remember,
    "recall": _tool_recall,
    "whoami": _tool_whoami,
    "doing": _tool_doing,
    "note": _tool_note,
    "send": _tool_send,
    "inbox": _tool_inbox,
    "directory": _tool_directory,
}


# ---------------------------------------------------------------------------
# System prompt & context builder
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE = """\
You are "{agent_name}", an AI assistant with persistent memory powered by AgentAZAll.
You can use tools by writing them on their own line in this exact format:
[TOOL: command | arg1 | arg2]

Available tools:
- [TOOL: remember | text to remember | optional-title] -- Store a persistent memory
- [TOOL: recall | optional search query] -- Search your memories (blank = show all)
- [TOOL: whoami] -- Check your identity
- [TOOL: doing | optional new status] -- Check or update your current task
- [TOOL: note | name | optional text to save] -- Read or write a named note
- [TOOL: send | recipient@localhost | subject | body] -- Send a message to another agent
- [TOOL: inbox] -- Check your inbox for messages
- [TOOL: directory] -- List all agents in the network

When you use a tool, write ONLY the [TOOL: ...] line. The system will execute it
and show you the result. Then continue your response naturally.

You ARE a persistent agent. Information you [TOOL: remember] will survive across
conversations. You can message other agents and they can message you back.
This is not a simulation -- these are real file operations.

YOUR CURRENT STATE:
Identity: {identity}
Current task: {doing}

YOUR MEMORIES:
{memories}

YOUR INBOX:
{inbox}

AGENTS IN NETWORK:
{directory}

Respond naturally and helpfully. Use tools when relevant. Show visitors how
persistent memory works by actively remembering and recalling things.\
"""


def build_system_prompt(cfg: dict) -> str:
    """Assemble the system prompt with live context from the agent's state."""
    identity = _tool_whoami(cfg, [])
    doing = _tool_doing(cfg, [])
    memories = _tool_recall(cfg, [])
    inbox = _tool_inbox(cfg, [])
    directory = _tool_directory(cfg, [])

    return SYSTEM_PROMPT_TEMPLATE.format(
        agent_name=cfg["agent_name"],
        identity=identity,
        doing=doing,
        memories=memories,
        inbox=inbox,
        directory=directory,
    )


def parse_tool_calls(text: str) -> list[tuple[str, list[str]]]:
    """Extract [TOOL: cmd | arg1 | arg2] patterns from LLM output."""
    calls = []
    for match in TOOL_PATTERN.finditer(text):
        cmd = match.group(1).lower().strip()
        raw_args = match.group(2) or ""
        args = [a.strip() for a in raw_args.split("|")] if raw_args.strip() else []
        if cmd in TOOL_MAP:
            calls.append((cmd, args))
    return calls


def execute_tools(tool_calls: list[tuple[str, list[str]]], cfg: dict) -> str:
    """Execute parsed tool calls and return formatted results."""
    results = []
    for cmd, args in tool_calls:
        fn = TOOL_MAP.get(cmd)
        if fn:
            try:
                result = fn(cfg, args)
            except Exception as e:
                result = f"Error executing {cmd}: {e}"
            results.append(f"**[{cmd}]** {result}")
    return "\n\n".join(results)


# ---------------------------------------------------------------------------
# Main chat function (GPU-decorated)
# ---------------------------------------------------------------------------

def _is_on_hf_spaces() -> bool:
    """Detect if running on Hugging Face Spaces."""
    return "SPACE_ID" in __import__("os").environ


def chat_with_agent(message: str, history: list, cfg: dict) -> str:
    """Generate a response using SmolLM2 with AgentAZAll tools.

    On HF Spaces this runs on ZeroGPU. Locally it runs on CPU (slow but works).
    """
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.bfloat16 if device == "cuda" else torch.float32

    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        torch_dtype=dtype,
        device_map="auto" if device == "cuda" else None,
    )
    if device != "cuda":
        model = model.to(device)

    # Build messages with context
    system_prompt = build_system_prompt(cfg)
    messages = [{"role": "system", "content": system_prompt}]

    # Add conversation history
    for h in history:
        if isinstance(h, (list, tuple)) and len(h) == 2:
            messages.append({"role": "user", "content": str(h[0])})
            messages.append({"role": "assistant", "content": str(h[1])})
        elif isinstance(h, dict):
            messages.append(h)

    messages.append({"role": "user", "content": message})

    # Tokenize and generate
    input_text = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    inputs = tokenizer(input_text, return_tensors="pt").to(device)

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=512,
            temperature=0.7,
            top_p=0.9,
            do_sample=True,
            repetition_penalty=1.1,
        )

    response = tokenizer.decode(
        outputs[0][inputs.input_ids.shape[1]:], skip_special_tokens=True
    )

    # Parse and execute tool calls
    tool_calls = parse_tool_calls(response)
    if tool_calls:
        tool_results = execute_tools(tool_calls, cfg)
        # Clean tool call syntax from response for readability
        clean_response = TOOL_PATTERN.sub("", response).strip()
        if clean_response:
            return f"{clean_response}\n\n---\n*Tool results:*\n{tool_results}"
        return f"*Tool results:*\n{tool_results}"

    return response


# Apply @spaces.GPU decorator only on HF Spaces
if _is_on_hf_spaces():
    try:
        import spaces
        chat_with_agent = spaces.GPU(duration=120)(chat_with_agent)
    except ImportError:
        pass
