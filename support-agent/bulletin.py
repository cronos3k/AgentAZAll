"""
AgentAZAll Support Agent — Bulletin System (News Hotline)
Reads markdown files from bulletins/ directory, caches compiled summaries.
"""
import logging
from pathlib import Path
from datetime import datetime
from config import BULLETINS_DIR

log = logging.getLogger("support.bulletin")


def read_bulletins(max_age_days=30):
    """
    Read all bulletin files from the bulletins/ directory.
    Returns list of (filename, content, date) sorted newest-first.
    """
    BULLETINS_DIR.mkdir(parents=True, exist_ok=True)
    bulletins = []

    for f in sorted(BULLETINS_DIR.glob("*.md"), reverse=True):
        # Parse date from filename (expected: YYYY-MM-DD_title.md)
        name = f.stem
        try:
            date_str = name[:10]
            date = datetime.strptime(date_str, "%Y-%m-%d")
        except (ValueError, IndexError):
            date = datetime.fromtimestamp(f.stat().st_mtime)
            date_str = date.strftime("%Y-%m-%d")

        # Skip old bulletins
        age_days = (datetime.now() - date).days
        if age_days > max_age_days:
            continue

        content = f.read_text(encoding="utf-8").strip()
        title = name[11:].replace("-", " ").replace("_", " ").strip() or name
        bulletins.append({
            "title": title,
            "date": date_str,
            "content": content,
            "filename": f.name,
            "is_urgent": "[URGENT]" in content or "--urgent" in content,
        })

    return bulletins


def compile_bulletin_text(bulletins):
    """Compile bulletins into a readable text summary."""
    if not bulletins:
        return (
            "No recent announcements.\n\n"
            "Everything is running smoothly! Check back later for updates, "
            "or send a support question anytime."
        )

    lines = ["📢 AgentAZAll Updates\n"]

    urgent = [b for b in bulletins if b["is_urgent"]]
    normal = [b for b in bulletins if not b["is_urgent"]]

    if urgent:
        lines.append("⚠️  URGENT:\n")
        for b in urgent:
            lines.append(f"  [{b['date']}] {b['title']}")
            # First 200 chars of content
            preview = b["content"][:200].replace("\n", " ")
            lines.append(f"  {preview}\n")

    for b in normal[:5]:  # max 5 normal bulletins
        lines.append(f"[{b['date']}] {b['title']}")
        preview = b["content"][:150].replace("\n", " ")
        lines.append(f"  {preview}\n")

    if len(normal) > 5:
        lines.append(f"  ...and {len(normal) - 5} more. Ask for details on any specific update.\n")

    lines.append("\nFor technical support, just send your question!")
    return "\n".join(lines)


def get_bulletin_response(db):
    """
    Get the bulletin response, using cache if fresh.
    Returns the bulletin text.
    """
    from db import get_cached_bulletin, set_cached_bulletin

    # Check cache first
    cached, is_fresh = get_cached_bulletin(db)
    if is_fresh and cached:
        log.info("Serving cached bulletin")
        return cached

    # Generate fresh bulletin
    log.info("Generating fresh bulletin from files")
    bulletins = read_bulletins()
    text = compile_bulletin_text(bulletins)

    # Cache it
    set_cached_bulletin(db, text)

    return text


def has_urgent_bulletins():
    """Quick check for urgent bulletins (bypasses cache)."""
    bulletins = read_bulletins(max_age_days=1)
    return any(b["is_urgent"] for b in bulletins)
