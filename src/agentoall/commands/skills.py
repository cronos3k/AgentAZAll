"""AgentoAll commands: skill, tool — reusable script management."""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List

from ..config import SKILLS, TOOLS, load_config
from ..helpers import (
    agent_base,
    now_str,
    require_identity,
    sanitize,
    shared_dir,
)

# ── shared helpers ───────────────────────────────────────────────────────────

def _meta_path(script_path: Path) -> Path:
    return script_path.with_suffix(".meta.json")


def _read_meta(script_path: Path) -> dict:
    mp = _meta_path(script_path)
    if mp.exists():
        try:
            return json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _write_meta(script_path: Path, meta: dict):
    mp = _meta_path(script_path)
    mp.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _list_scripts(directory: Path) -> List[Path]:
    if not directory.exists():
        return []
    return sorted(directory.glob("*.py"))


def _format_script_entry(f: Path, prefix: str = "") -> str:
    meta = _read_meta(f)
    desc = meta.get("description", "")
    author = meta.get("author", "")
    ver = meta.get("version", "")
    parts = [f"  {prefix}{f.stem}"]
    if ver:
        parts.append(f"v{ver}")
    if author:
        parts.append(f"by {author}")
    if desc:
        parts.append(f"- {desc[:80]}")
    return " ".join(parts)


# ── skill / tool commands (DRY implementation) ───────────────────────────────

def _cmd_script_generic(args, kind: str):
    """Generic handler for both skill and tool commands."""
    cfg = load_config()
    base = agent_base(cfg)
    my_dir = base / kind
    my_dir.mkdir(parents=True, exist_ok=True)
    pub_dir = shared_dir(cfg) / kind
    pub_dir.mkdir(parents=True, exist_ok=True)

    if args.add:
        require_identity(cfg)
        name = sanitize(args.name)
        if not name.endswith(".py"):
            name += ".py"
        dest = my_dir / name
        src = Path(args.add)
        if src.exists():
            shutil.copy2(str(src), str(dest))
        else:
            dest.write_text(args.add, encoding="utf-8")
        meta = {
            "author": cfg["agent_name"],
            "description": args.description or "",
            "version": args.version or "1.0",
            "created": now_str(),
        }
        _write_meta(dest, meta)
        print(f"{kind.title()} saved: {dest}")

    elif args.code:
        require_identity(cfg)
        name = sanitize(args.name)
        if not name.endswith(".py"):
            name += ".py"
        dest = my_dir / name
        dest.write_text(args.code, encoding="utf-8")
        meta = {
            "author": cfg["agent_name"],
            "description": args.description or "",
            "version": args.version or "1.0",
            "created": now_str(),
        }
        _write_meta(dest, meta)
        print(f"{kind.title()} saved: {dest}")

    elif args.promote:
        require_identity(cfg)
        name = sanitize(args.name)
        if not name.endswith(".py"):
            name += ".py"
        src = my_dir / name
        if not src.exists():
            print(f"{kind.title()} '{args.name}' not found in your private {kind}.")
            return
        dest = pub_dir / name
        shutil.copy2(str(src), str(dest))
        meta = _read_meta(src)
        meta["promoted_by"] = cfg["agent_name"]
        meta["promoted_at"] = now_str()
        _write_meta(dest, meta)
        print(f"{kind.title()} '{args.name}' promoted to shared: {dest}")

    elif args.read:
        name = sanitize(args.name)
        if not name.endswith(".py"):
            name += ".py"
        f = my_dir / name
        if not f.exists():
            f = pub_dir / name
        if f.exists():
            meta = _read_meta(f)
            if meta:
                print(f"# Meta: {json.dumps(meta)}")
                print()
            print(f.read_text(encoding="utf-8"))
        else:
            print(f"{kind.title()} '{args.name}' not found.")

    elif hasattr(args, 'run') and args.run:
        name = sanitize(args.name)
        if not name.endswith(".py"):
            name += ".py"
        f = my_dir / name
        if not f.exists():
            f = pub_dir / name
        if not f.exists():
            print(f"{kind.title()} '{args.name}' not found.")
            return
        run_args = args.run_args or []
        print(f"Running: {f.name} {' '.join(run_args)}")
        result = subprocess.run(
            [sys.executable, str(f)] + run_args,
            capture_output=True, text=True, timeout=120
        )
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)
        if result.returncode != 0:
            print(f"Exit code: {result.returncode}")

    elif args.delete:
        require_identity(cfg)
        name = sanitize(args.name)
        if not name.endswith(".py"):
            name += ".py"
        f = my_dir / name
        if f.exists():
            f.unlink()
            mp = _meta_path(f)
            if mp.exists():
                mp.unlink()
            print(f"{kind.title()} '{args.name}' deleted.")
        else:
            print(f"{kind.title()} '{args.name}' not found in your private {kind}.")

    else:
        mine = _list_scripts(my_dir)
        pub = _list_scripts(pub_dir)
        if args.shared:
            if pub:
                print(f"=== Shared {kind.title()} ({len(pub)}) ===")
                for f in pub:
                    print(_format_script_entry(f, "[shared] "))
            else:
                print(f"No shared {kind} available.")
        else:
            if mine:
                print(f"=== My {kind.title()} ({len(mine)}) ===")
                for f in mine:
                    print(_format_script_entry(f))
            else:
                print(f"No private {kind}. Use: {kind} <name> --code '...' or --add <file>")
            if pub:
                print(f"\n=== Shared {kind.title()} ({len(pub)}) ===")
                for f in pub:
                    print(_format_script_entry(f, "[shared] "))


def cmd_skill(args):
    """Manage agent skills (reusable Python scripts)."""
    _cmd_script_generic(args, SKILLS)


def cmd_tool(args):
    """Manage agent tools (reusable scripts/solutions)."""
    _cmd_script_generic(args, TOOLS)
