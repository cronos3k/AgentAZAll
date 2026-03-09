#!/usr/bin/env python3
"""
AgentAZAll Portation Script

Packages the entire AgentAZAll project -- code, agent data, email server data,
FTP server data, configs, and logs -- into a single ZIP file that can be
copied to another system and run immediately.

Usage:
    python portation.py                          # auto-named output
    python portation.py --output backup.zip      # custom name
    python portation.py --no-data                # code only, no agent data
"""

import argparse
import os
import zipfile
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()


def create_export(output=None, include_data=True):
    if not output:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = f"agentazall_portable_{ts}.zip"
    out_path = Path(output).resolve()

    # files to always include
    code_files = [
        "agentazall.py",
        "email_server.py",
        "ftp_server.py",
        "web_ui.py",
        "portation.py",
        "config.json",
        "requirements.txt",
        "test_integration.py",
        "AGENT.md",
    ]

    # directories to include (agent config)
    code_dirs = [".agent"]
    data_dirs = ["data", "logs"] if include_data else []

    count = 0
    total_bytes = 0

    with zipfile.ZipFile(str(out_path), "w", zipfile.ZIP_DEFLATED) as zf:
        # individual files
        for fname in code_files:
            fp = SCRIPT_DIR / fname
            if fp.exists():
                zf.write(str(fp), fname)
                total_bytes += fp.stat().st_size
                count += 1

        # directory trees
        for dname in code_dirs + data_dirs:
            dp = SCRIPT_DIR / dname
            if not dp.exists():
                continue
            for root, dirs, files in os.walk(str(dp)):
                # skip __pycache__
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for f in files:
                    if f.endswith((".pyc", ".pyo")):
                        continue
                    full = Path(root) / f
                    arcname = str(full.relative_to(SCRIPT_DIR))
                    zf.write(str(full), arcname)
                    total_bytes += full.stat().st_size
                    count += 1

    zip_size = out_path.stat().st_size
    ratio = (1 - zip_size / total_bytes) * 100 if total_bytes > 0 else 0

    print("=" * 52)
    print("  AgentAZAll Portation Complete")
    print("=" * 52)
    print(f"  Output:       {out_path}")
    print(f"  Files:        {count}")
    print(f"  Uncompressed: {total_bytes / (1024*1024):.1f} MB")
    print(f"  Compressed:   {zip_size / (1024*1024):.1f} MB ({ratio:.0f}% reduction)")
    print()
    print("  To restore on another system:")
    print(f"    1. unzip {out_path.name}")
    print("    2. pip install pyftpdlib gradio  (optional deps)")
    print("    3. python email_server.py        (start mail server)")
    print("    4. python agentazall.py daemon    (start sync daemon)")
    print("    5. python web_ui.py              (start web UI)")
    print("=" * 52)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="AgentAZAll Portation Script")
    p.add_argument("--output", "-o", help="Output ZIP filename")
    p.add_argument("--no-data", action="store_true",
                   help="Exclude agent data (code only)")
    args = p.parse_args()
    create_export(args.output, include_data=not args.no_data)
