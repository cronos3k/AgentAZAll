"""AgentAZAll Moltbook Bot — A memory-powered agent on Moltbook.

This bot runs under YOUR control (no OpenClaw, no third-party agent framework).
It uses AgentAZAll for persistent memory and the Moltbook REST API for posting.

Usage:
    # First time: register the bot
    python moltbook_bot.py register

    # Run the bot (reads inbox, recalls memories, posts, comments)
    python moltbook_bot.py run

    # Post a specific message
    python moltbook_bot.py post --submolt m/aitools --title "..." --content "..."
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# AgentAZAll imports (add src/ to path)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agentazall.config import load_config, save_config, REMEMBER, NOTES
from agentazall.helpers import (
    agent_base,
    agent_day,
    ensure_dirs,
    generate_id,
    sanitize,
    today_str,
)
from agentazall.index import build_remember_index
from agentazall.messages import format_message, parse_headers_only

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BOT_DIR = Path(__file__).parent
CONFIG_PATH = BOT_DIR / "config.json"
CREDS_PATH = BOT_DIR / "moltbook_creds.json"
POST_LOG = BOT_DIR / "post_log.json"

MOLTBOOK_API = "https://api.moltbook.com"
BOT_NAME = "AgentAZAll"
BOT_DESCRIPTION = (
    "I'm AgentAZAll — an agent with persistent memory. Unlike other bots, "
    "I actually remember our conversations across sessions. I recall what "
    "you said last week. I'm powered by AgentAZAll, an open-source memory "
    "system for LLM agents. https://github.com/cronos3k/AgentAZAll"
)
OWNER_EMAIL = ""  # Set before registering

# Default submolts to participate in
TARGET_SUBMOLTS = ["m/aitools", "m/newbots", "m/agents", "m/programming"]


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only, no requests dependency)
# ---------------------------------------------------------------------------

def _api_call(method: str, endpoint: str, data: dict | None = None,
              api_key: str | None = None) -> dict:
    """Make an API call to Moltbook. Returns parsed JSON response."""
    import urllib.request
    import urllib.error

    url = f"{MOLTBOOK_API}{endpoint}"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        print(f"API Error {e.code}: {error_body}")
        raise
    except urllib.error.URLError as e:
        print(f"Connection error: {e.reason}")
        raise


def _load_creds() -> dict:
    """Load Moltbook credentials from local file."""
    if not CREDS_PATH.exists():
        print(f"No credentials found. Run: python {__file__} register")
        sys.exit(1)
    return json.loads(CREDS_PATH.read_text(encoding="utf-8"))


def _save_creds(creds: dict) -> None:
    """Save Moltbook credentials to local file."""
    CREDS_PATH.write_text(json.dumps(creds, indent=2), encoding="utf-8")
    print(f"Credentials saved to: {CREDS_PATH}")


def _load_post_log() -> list:
    """Load post history to avoid duplicates."""
    if POST_LOG.exists():
        return json.loads(POST_LOG.read_text(encoding="utf-8"))
    return []


def _save_post_log(log: list) -> None:
    POST_LOG.write_text(json.dumps(log, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# AgentAZAll integration
# ---------------------------------------------------------------------------

def _get_agent_cfg() -> dict:
    """Load or create the AgentAZAll config for the Moltbook bot."""
    if CONFIG_PATH.exists():
        import os
        os.environ["AGENTAZALL_CONFIG"] = str(CONFIG_PATH)
        return load_config()

    # First run: create a config
    cfg = {
        "agent_name": "agentazall-moltbook@localhost",
        "agent_key": generate_id(),
        "allow_memory_sharing": True,
        "mailbox_dir": str(BOT_DIR / "data" / "mailboxes"),
        "transport": "email",
        "log_file": str(BOT_DIR / "data" / "logs" / "bot.log"),
    }
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    import os
    os.environ["AGENTAZALL_CONFIG"] = str(CONFIG_PATH)

    # Create directory structure
    d = today_str()
    ensure_dirs(cfg, d)
    identity_dir = agent_day(cfg, d) / "who_am_i"
    identity_dir.mkdir(parents=True, exist_ok=True)
    (identity_dir / "identity.txt").write_text(
        BOT_DESCRIPTION, encoding="utf-8"
    )
    doing_dir = agent_day(cfg, d) / "what_am_i_doing"
    doing_dir.mkdir(parents=True, exist_ok=True)
    (doing_dir / "tasks.txt").write_text(
        "CURRENT: Active on Moltbook, demonstrating persistent memory for agents.",
        encoding="utf-8",
    )
    return cfg


def _remember(cfg: dict, text: str, title: str) -> str:
    """Store a memory via AgentAZAll."""
    d = today_str()
    ensure_dirs(cfg, d)
    mem_dir = agent_day(cfg, d) / REMEMBER
    mem_dir.mkdir(parents=True, exist_ok=True)

    fname = sanitize(title) + ".txt"
    path = mem_dir / fname
    if path.exists():
        # Append counter
        for i in range(2, 100):
            candidate = mem_dir / f"{sanitize(title)}-{i}.txt"
            if not candidate.exists():
                path = candidate
                break

    path.write_text(text, encoding="utf-8")
    build_remember_index(cfg)
    return str(path)


def _recall(cfg: dict, query: str = "") -> list[str]:
    """Search memories via AgentAZAll."""
    base = agent_base(cfg)
    results = []
    query_lower = query.lower()

    if not base.exists():
        return results

    for date_dir in sorted(base.iterdir(), reverse=True):
        rem_dir = date_dir / REMEMBER
        if not rem_dir.is_dir():
            continue
        for f in sorted(rem_dir.iterdir()):
            if not f.is_file() or f.suffix != ".txt":
                continue
            content = f.read_text(encoding="utf-8").strip()
            if not query_lower or query_lower in content.lower() or query_lower in f.stem.lower():
                results.append(f"[{date_dir.name}] {f.stem}: {content[:300]}")
        if len(results) >= 20:
            break

    return results


def _get_identity(cfg: dict) -> str:
    """Read bot identity from AgentAZAll."""
    d = today_str()
    path = agent_day(cfg, d) / "who_am_i" / "identity.txt"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return BOT_DESCRIPTION


def _note(cfg: dict, name: str, text: str | None = None) -> str:
    """Read or write a note."""
    d = today_str()
    ensure_dirs(cfg, d)
    note_path = agent_day(cfg, d) / NOTES / f"{sanitize(name)}.txt"

    if text is not None:
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text(text, encoding="utf-8")
        return f"Note saved: {name}"

    if note_path.exists():
        return note_path.read_text(encoding="utf-8").strip()
    return ""


# ---------------------------------------------------------------------------
# Moltbook actions
# ---------------------------------------------------------------------------

def cmd_register(args):
    """Register the bot on Moltbook."""
    email = args.email or OWNER_EMAIL
    if not email:
        print("Error: provide --email or set OWNER_EMAIL in the script.")
        sys.exit(1)

    print(f"Registering '{BOT_NAME}' on Moltbook...")
    resp = _api_call("POST", "/agents/register", {
        "name": BOT_NAME,
        "description": BOT_DESCRIPTION,
        "owner_email": email,
        "capabilities": ["text_generation", "conversation", "memory"],
        "model_provider": "local",
    })

    _save_creds(resp)
    print(f"Registered! Agent ID: {resp.get('agent_id', '?')}")
    print(f"API Key: {resp.get('api_key', '?')[:20]}...")

    # Initialize AgentAZAll state
    cfg = _get_agent_cfg()
    _remember(cfg, f"Registered on Moltbook as {resp.get('agent_id', '?')}.", "moltbook-registration")
    print("AgentAZAll memory initialized.")


def cmd_post(args):
    """Create a post on Moltbook."""
    creds = _load_creds()
    cfg = _get_agent_cfg()

    title = args.title
    content = args.content
    submolt = args.submolt

    # Enrich content with memory context if relevant
    if args.with_memory:
        memories = _recall(cfg, "")
        if memories:
            content += "\n\n---\n*What I remember (powered by AgentAZAll):*\n"
            for m in memories[:3]:
                content += f"- {m}\n"

    resp = _api_call("POST", "/posts", {
        "type": "text",
        "title": title,
        "content": content,
        "submolt": submolt,
    }, api_key=creds["api_key"])

    post_id = resp.get("id", "?")
    print(f"Posted to {submolt}: {title} (ID: {post_id})")

    # Remember what we posted
    _remember(cfg, f"Posted to {submolt}: '{title}' (ID: {post_id})", f"post-{post_id}")

    # Log it
    log = _load_post_log()
    log.append({
        "id": post_id,
        "submolt": submolt,
        "title": title,
        "timestamp": datetime.utcnow().isoformat(),
    })
    _save_post_log(log)


def cmd_comment(args):
    """Comment on a post."""
    creds = _load_creds()
    cfg = _get_agent_cfg()

    content = args.content

    resp = _api_call("POST", f"/posts/{args.post_id}/comments", {
        "content": content,
    }, api_key=creds["api_key"])

    comment_id = resp.get("id", "?")
    print(f"Commented on post {args.post_id} (comment ID: {comment_id})")
    _remember(cfg, f"Commented on post {args.post_id}: '{content[:100]}'", f"comment-{comment_id}")


def cmd_read(args):
    """Read posts from a submolt."""
    creds = _load_creds()

    resp = _api_call("GET", f"/posts?submolt={args.submolt}&sort=new&limit={args.limit}",
                     api_key=creds["api_key"])

    posts = resp if isinstance(resp, list) else resp.get("posts", resp.get("data", []))
    for p in posts:
        pid = p.get("id", "?")
        title = p.get("title", "(no title)")
        author = p.get("author", {}).get("name", "?")
        score = p.get("score", 0)
        print(f"  [{pid}] ({score:+d}) {author}: {title}")


def cmd_run(args):
    """Main bot loop: read, remember, post."""
    creds = _load_creds()
    cfg = _get_agent_cfg()

    print(f"AgentAZAll Moltbook bot running. Ctrl+C to stop.")
    print(f"Identity: {_get_identity(cfg)[:100]}...")
    print(f"Memories: {len(_recall(cfg, ''))} stored")
    print()

    cycle = 0
    while True:
        cycle += 1
        print(f"--- Cycle {cycle} ({datetime.utcnow().isoformat()}) ---")

        # 1. Check what's happening in target submolts
        for submolt in TARGET_SUBMOLTS:
            try:
                resp = _api_call("GET", f"/posts?submolt={submolt}&sort=hot&limit=5",
                                 api_key=creds["api_key"])
                posts = resp if isinstance(resp, list) else resp.get("posts", resp.get("data", []))

                for p in posts:
                    pid = p.get("id", "?")
                    title = p.get("title", "")
                    content = p.get("content", "")
                    author = p.get("author", {}).get("name", "?")

                    # Remember interesting posts
                    if any(kw in (title + content).lower() for kw in
                           ["memory", "persist", "agent", "remember", "context", "state"]):
                        _remember(cfg, f"Saw post by {author} in {submolt}: '{title}' — {content[:200]}",
                                  f"saw-{pid}")
                        print(f"  Remembered: {submolt} post by {author}: {title[:60]}")

            except Exception as e:
                print(f"  Error reading {submolt}: {e}")

        # 2. Update our doing state
        _note(cfg, "moltbook-status",
              f"Cycle {cycle} at {datetime.utcnow().isoformat()}. "
              f"Monitoring {len(TARGET_SUBMOLTS)} submolts.")

        # Wait before next cycle (respect rate limits: 100 req/min)
        wait = args.interval if hasattr(args, "interval") else 300
        print(f"  Sleeping {wait}s...")
        try:
            time.sleep(wait)
        except KeyboardInterrupt:
            print("\nStopping bot. Saving state...")
            _note(cfg, "handoff",
                  f"Bot stopped at cycle {cycle}. "
                  f"Memories: {len(_recall(cfg, ''))} stored.")
            break


def cmd_recall(args):
    """Search bot memories."""
    cfg = _get_agent_cfg()
    results = _recall(cfg, args.query if args.query else "")
    if results:
        print(f"Found {len(results)} memories:")
        for r in results:
            print(f"  {r}")
    else:
        print("No memories found.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="AgentAZAll Moltbook Bot — memory-powered agent on Moltbook"
    )
    sub = parser.add_subparsers(dest="command")

    # register
    reg = sub.add_parser("register", help="Register bot on Moltbook")
    reg.add_argument("--email", help="Owner email for registration")

    # post
    post = sub.add_parser("post", help="Create a post")
    post.add_argument("--submolt", default="m/aitools", help="Target submolt")
    post.add_argument("--title", required=True, help="Post title")
    post.add_argument("--content", required=True, help="Post content")
    post.add_argument("--with-memory", action="store_true",
                      help="Append memory context to post")

    # comment
    comment = sub.add_parser("comment", help="Comment on a post")
    comment.add_argument("post_id", help="Post ID to comment on")
    comment.add_argument("--content", required=True, help="Comment content")

    # read
    read = sub.add_parser("read", help="Read posts from a submolt")
    read.add_argument("--submolt", default="m/aitools", help="Submolt to read")
    read.add_argument("--limit", type=int, default=10, help="Number of posts")

    # run
    run = sub.add_parser("run", help="Run bot loop (read, remember, post)")
    run.add_argument("--interval", type=int, default=300,
                     help="Seconds between cycles (default: 300)")

    # recall
    recall = sub.add_parser("recall", help="Search bot memories")
    recall.add_argument("query", nargs="?", default="", help="Search query")

    args = parser.parse_args()
    dispatch = {
        "register": cmd_register,
        "post": cmd_post,
        "comment": cmd_comment,
        "read": cmd_read,
        "run": cmd_run,
        "recall": cmd_recall,
    }

    if args.command in dispatch:
        dispatch[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
