"""AgentAZAll index builder — daily index and cross-day memory index."""

import json
from pathlib import Path
from typing import Optional

from .config import (
    INBOX,
    INDEX,
    NOTES,
    OUTBOX,
    REMEMBER,
    REMEMBER_INDEX,
    SENT,
    SKILLS,
    TOOLS,
    WHAT_AM_I_DOING,
    WHO_AM_I,
)
from .helpers import (
    agent_base,
    agent_day,
    date_dirs,
    now_str,
    today_str,
)
from .messages import parse_headers_only


def build_index(cfg, d=None) -> Optional[Path]:
    """Build or rebuild the daily index file."""
    d = d or today_str()
    root = agent_day(cfg, d)
    if not root.exists():
        return None

    lines = [
        f"# AgentAZAll Index: {cfg['agent_name']}",
        f"# Date: {d}",
        f"# Updated: {now_str()}",
        "",
    ]

    # inbox
    inbox_dir = root / INBOX
    ie = []
    if inbox_dir.exists():
        for f in sorted(inbox_dir.glob("*.txt")):
            h = parse_headers_only(f)
            if not h:
                continue
            st = h.get("Status", "?").upper()
            ts = h.get("Date", "").split()[-1] if " " in h.get("Date", "") else "??:??"
            att = " [ATT]" if "Attachments" in h else ""
            ie.append(
                f"  [{st}]{att} {ts} | From: {h.get('From', '?')} "
                f"| Subject: {h.get('Subject', '?')} | {INBOX}/{f.name}"
            )
    lines.append(f"INBOX ({len(ie)}):")
    lines.extend(ie or ["  (empty)"])
    lines.append("")

    # sent
    sent_dir = root / SENT
    se = []
    if sent_dir.exists():
        for f in sorted(sent_dir.glob("*.txt")):
            h = parse_headers_only(f)
            if not h:
                continue
            ts = h.get("Date", "").split()[-1] if " " in h.get("Date", "") else "??:??"
            se.append(
                f"  {ts} | To: {h.get('To', '?')} "
                f"| Subject: {h.get('Subject', '?')} | {SENT}/{f.name}"
            )
    lines.append(f"SENT ({len(se)}):")
    lines.extend(se or ["  (empty)"])
    lines.append("")

    # outbox (pending)
    outbox_dir = root / OUTBOX
    oe = []
    if outbox_dir.exists():
        for f in sorted(outbox_dir.glob("*.txt")):
            h = parse_headers_only(f)
            if not h:
                continue
            oe.append(
                f"  [PENDING] To: {h.get('To', '?')} "
                f"| Subject: {h.get('Subject', '?')} | {OUTBOX}/{f.name}"
            )
    if oe:
        lines.append(f"OUTBOX ({len(oe)}):")
        lines.extend(oe)
        lines.append("")

    # notes
    notes_dir = root / NOTES
    ne = []
    if notes_dir.exists():
        for f in sorted(notes_dir.glob("*.txt")):
            ne.append(f"  {f.stem} ({f.stat().st_size}B) | {NOTES}/{f.name}")
    if ne:
        lines.append(f"NOTES ({len(ne)}):")
        lines.extend(ne)
        lines.append("")

    # remember
    rem_dir = root / REMEMBER
    re_entries = []
    if rem_dir.exists():
        for f in sorted(rem_dir.glob("*.txt")):
            text = f.read_text(encoding="utf-8", errors="replace").strip()
            first = ""
            for ln in text.split("\n"):
                ln = ln.strip()
                if ln:
                    first = ln[:100]
                    break
            re_entries.append(f"  {f.stem}: {first} | {REMEMBER}/{f.name}")
    if re_entries:
        lines.append(f"REMEMBER ({len(re_entries)}):")
        lines.extend(re_entries)
        lines.append("")

    # identity / tasks
    wf = root / WHO_AM_I / "identity.txt"
    df = root / WHAT_AM_I_DOING / "tasks.txt"
    if wf.exists():
        lines.append(f"IDENTITY: {WHO_AM_I}/identity.txt")
    if df.exists():
        lines.append(f"TASKS: {WHAT_AM_I_DOING}/tasks.txt")

    # skills & tools (agent-level, not per-day)
    base = agent_base(cfg)
    for kind in (SKILLS, TOOLS):
        kdir = base / kind
        if kdir.exists():
            entries = sorted(kdir.glob("*.py"))
            if entries:
                lines.append("")
                lines.append(f"{kind.upper()} ({len(entries)}):")
                for f in entries:
                    meta = {}
                    mp = f.with_suffix(".meta.json")
                    if mp.exists():
                        try:
                            meta = json.loads(mp.read_text(encoding="utf-8"))
                        except Exception:
                            pass
                    desc = meta.get("description", "")
                    tag = f"- {desc[:60]}" if desc else ""
                    lines.append(f"  {f.stem} {tag}")

    content = "\n".join(lines)
    idx = root / INDEX
    idx.write_text(content, encoding="utf-8")
    return idx


# ── remember index (cross-day sparse bullet-point index) ─────────────────────

def _remember_needs_rebuild(cfg) -> bool:
    """Check if any remember files are newer than the index."""
    b = agent_base(cfg)
    idx = b / REMEMBER_INDEX
    if not idx.exists():
        return True
    idx_mtime = idx.stat().st_mtime
    for d in date_dirs(cfg):
        rem_dir = b / d / REMEMBER
        if not rem_dir.exists():
            continue
        if rem_dir.stat().st_mtime > idx_mtime:
            return True
        for f in rem_dir.glob("*.txt"):
            if f.stat().st_mtime > idx_mtime:
                return True
    return False


def build_remember_index(cfg) -> Optional[Path]:
    """Build a consolidated sparse bullet-point memory index across all days."""
    b = agent_base(cfg)
    if not b.exists():
        return None

    if not _remember_needs_rebuild(cfg):
        return b / REMEMBER_INDEX

    entries = []
    for d in sorted(date_dirs(cfg), reverse=True):
        rem_dir = b / d / REMEMBER
        if not rem_dir.exists():
            continue
        for f in sorted(rem_dir.glob("*.txt"), reverse=True):
            text = f.read_text(encoding="utf-8", errors="replace").strip()
            summary = ""
            for ln in text.split("\n"):
                ln = ln.strip()
                if ln:
                    summary = ln[:120]
                    break
            title = f.stem
            entries.append((d, title, summary, f"{d}/{REMEMBER}/{f.name}"))

    lines = [
        f"# Agent Memory Index: {cfg['agent_name']}",
        f"# Updated: {now_str()}",
        f"# Total memories: {len(entries)}",
        "",
    ]
    for d, title, summary, rel in entries:
        lines.append(f"- [{d}] {title}: {summary}  | {rel}")

    if not entries:
        lines.append("(no memories stored yet)")

    idx = b / REMEMBER_INDEX
    idx.parent.mkdir(parents=True, exist_ok=True)
    idx.write_text("\n".join(lines), encoding="utf-8")
    return idx
