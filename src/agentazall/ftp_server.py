#!/usr/bin/env python3
"""
AgentAZAll FTP Server - Embedded FTP server for agent-to-agent communication.

Provides the central FTP hub that all agent daemons sync with.
Each agent gets a directory on the server, and messages are delivered
by uploading files to the recipient's inbox directory.

Usage:
    python ftp_server.py [--port PORT] [--host HOST]

Requires: pip install pyftpdlib
"""

import argparse
import json
import logging
import os
import socket
import sys
from pathlib import Path

try:
    from pyftpdlib.authorizers import DummyAuthorizer
    from pyftpdlib.handlers import FTPHandler
    from pyftpdlib.servers import FTPServer
except ImportError:
    print("ERROR: pyftpdlib required.  Install:  pip install pyftpdlib")
    sys.exit(1)


SCRIPT_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = Path(os.environ.get("AGENTAZALL_CONFIG", str(SCRIPT_DIR / "config.json")))

# logging
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [FTP] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("FTP")


def is_port_free(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def find_free_port(host, start, end):
    for port in range(start, end + 1):
        if is_port_free(host, port):
            return port
    return None


def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Could not parse config %s: %s (using defaults)", CONFIG_FILE, e)
    return {}


def start_server(cfg=None, port=None):
    if cfg is None:
        cfg = load_config()

    ftp_cfg = cfg.get("ftp", {})
    host = ftp_cfg.get("host", "127.0.0.1")
    ftp_root = Path(ftp_cfg.get("root", str(SCRIPT_DIR / "data" / "ftp_root")))
    ftp_root.mkdir(parents=True, exist_ok=True)

    user = ftp_cfg.get("user", "agentoftp")
    password = ftp_cfg.get("password", "agentoftp_pass")
    port_range = ftp_cfg.get("port_range", [2121, 2199])

    if port is None:
        port = ftp_cfg.get("port", 2121)

    # Find free port
    if not is_port_free(host, port):
        log.info("Port %d in use. Searching range %d-%d...", port, port_range[0], port_range[1])
        port = find_free_port(host, port_range[0], port_range[1])
        if port is None:
            log.error("No free port in range %d-%d", port_range[0], port_range[1])
            sys.exit(1)
        log.info("Found free port: %d", port)

    # Authorizer
    authorizer = DummyAuthorizer()
    authorizer.add_user(user, password, str(ftp_root), perm="elradfmwMT")

    # Handler - subclass to avoid mutating the global FTPHandler class
    class AgentoFTPHandler(FTPHandler):
        pass

    AgentoFTPHandler.authorizer = authorizer
    AgentoFTPHandler.banner = "AgentAZAll FTP Server ready."
    AgentoFTPHandler.timeout = 120        # connection timeout
    AgentoFTPHandler.idle_timeout = 60    # idle connection timeout

    # Passive port range (for data connections)
    passive_start = port + 100
    passive_end = port + 200
    AgentoFTPHandler.passive_ports = range(passive_start, passive_end)

    # Server
    server = FTPServer((host, port), AgentoFTPHandler)
    server.max_cons = 256
    server.max_cons_per_ip = 50

    print()
    print("=" * 52)
    print("  AgentAZAll FTP Server")
    print("=" * 52)
    print(f"  Listen: {host}:{port}")
    print(f"  Root:   {ftp_root}")
    print(f"  User:   {user}")
    print(f"  Passive ports: {passive_start}-{passive_end}")
    print()
    print("  Press Ctrl+C to stop")
    print("=" * 52)
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.close_all()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AgentAZAll FTP Server")
    parser.add_argument("--port", type=int, help="FTP port")
    parser.add_argument("--host", help="Bind host")
    args = parser.parse_args()

    cfg = load_config()
    ftp_cfg = cfg.get("ftp", {})
    if args.host:
        ftp_cfg["host"] = args.host
    cfg["ftp"] = ftp_cfg
    start_server(cfg, args.port)
