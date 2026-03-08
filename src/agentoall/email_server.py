#!/usr/bin/env python3
"""
AgentoAll Local Email Server

Zero-dependency SMTP + IMAP + POP3 server in a single script.
Stores mail in a local directory.  Designed for local agent-to-agent
and agent-to-human testing.

Usage:
    python email_server.py                           # defaults
    python email_server.py --smtp-port 2525          # custom ports
    python email_server.py --create-accounts 5       # agent1..agent5
"""

import asyncio
import base64
import itertools
import json
import logging
import re
import socket
import time
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# -- logging --

LOG_FMT = "%(asctime)s [%(name)-4s] %(message)s"
LOG_DATE = "%H:%M:%S"
logging.basicConfig(level=logging.INFO, format=LOG_FMT, datefmt=LOG_DATE)
log_smtp = logging.getLogger("SMTP")
log_imap = logging.getLogger("IMAP")
log_pop3 = logging.getLogger("POP3")
log_main = logging.getLogger("MAIN")

# -- port helpers --


def is_port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def find_port(host: str, preferred: int, alt_start: int, alt_end: int) -> int:
    if is_port_free(host, preferred):
        return preferred
    for p in range(alt_start, alt_end):
        if is_port_free(host, p):
            return p
    raise RuntimeError(
        f"No free port (tried {preferred} and {alt_start}-{alt_end})"
    )


# -- mail store --


class MailStore:
    """Simple file-backed mailbox store shared by all three protocols."""

    def __init__(self, base_dir: str):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)
        self.accounts: Dict[str, dict] = self._load_accounts()
        self._uid_counter = itertools.count(int(time.time() * 1000))
        self._accounts_mtime: float = self._accounts_file_mtime()
        self._write_lock = asyncio.Lock()  # protects concurrent writes

    # -- accounts --

    def _accounts_path(self) -> Path:
        return self.base / "accounts.json"

    def _load_accounts(self) -> dict:
        p = self._accounts_path()
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return {}

    def _save_accounts(self):
        p = self._accounts_path()
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.accounts, indent=2), encoding="utf-8")
        tmp.replace(p)
        self._accounts_mtime = p.stat().st_mtime

    def ensure_account(self, addr: str, password: str = "password"):
        if addr not in self.accounts:
            self.accounts[addr] = {"password": password}
            self._save_accounts()
            log_main.info("Account created: %s (pw: %s)", addr, password)
        udir = self._user_dir(addr)
        for folder in ("INBOX", "Sent", "Drafts", "WhoAmI", "WhatAmIDoing"):
            (udir / folder).mkdir(parents=True, exist_ok=True)

    def _accounts_file_mtime(self) -> float:
        p = self._accounts_path()
        return p.stat().st_mtime if p.exists() else 0.0

    def _maybe_reload_accounts(self):
        """Reload accounts.json if it changed on disk."""
        try:
            mt = self._accounts_file_mtime()
            if mt > self._accounts_mtime:
                fresh = self._load_accounts()
                # merge: keep in-memory auto-created accounts, add new disk ones
                fresh.update(self.accounts)
                self.accounts = fresh
                self._accounts_mtime = mt
                log_main.info("Accounts reloaded from disk (%d total)", len(self.accounts))
        except Exception:
            pass

    def authenticate(self, user: str, password: str) -> bool:
        self._maybe_reload_accounts()
        acct = self.accounts.get(user)
        if acct and acct.get("password") == password:
            return True
        return False

    # -- storage helpers --

    def _user_dir(self, addr: str) -> Path:
        safe = addr.replace("@", "_at_")
        safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", safe)
        return self.base / safe

    def _next_uid(self) -> str:
        return str(next(self._uid_counter))

    # -- deliver / read --

    def deliver(self, recipient: str, raw: bytes) -> str:
        self.ensure_account(recipient)
        uid = self._next_uid()
        inbox = self._user_dir(recipient) / "INBOX"
        (inbox / f"{uid}.eml").write_bytes(raw)
        (inbox / f"{uid}.meta").write_text(
            json.dumps({"uid": uid, "flags": [], "ts": datetime.now().isoformat()}),
            encoding="utf-8",
        )
        return uid

    def get_messages(self, user: str, folder: str = "INBOX") -> List[dict]:
        fdir = self._user_dir(user) / folder
        if not fdir.exists():
            return []
        msgs = []
        for eml in sorted(fdir.glob("*.eml")):
            uid = eml.stem
            meta_path = eml.with_suffix(".meta")
            meta = {}
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    meta = {"uid": uid, "flags": []}
            # Lazy: store path, load raw only on demand via get_raw()
            msgs.append({"uid": uid, "path": eml, "meta": meta,
                         "size": eml.stat().st_size})
        return msgs

    def get_raw(self, msg: dict) -> bytes:
        """Load raw message bytes on demand."""
        if "raw" in msg:
            return msg["raw"]
        raw = msg["path"].read_bytes()
        msg["raw"] = raw  # cache once loaded
        return raw

    def get_folders(self, user: str) -> List[str]:
        udir = self._user_dir(user)
        if not udir.exists():
            return []
        return sorted(d.name for d in udir.iterdir() if d.is_dir())

    def create_folder(self, user: str, folder: str):
        (self._user_dir(user) / folder).mkdir(parents=True, exist_ok=True)

    def append_message(self, user: str, folder: str, raw: bytes) -> str:
        self.ensure_account(user)
        fdir = self._user_dir(user) / folder
        fdir.mkdir(parents=True, exist_ok=True)
        uid = self._next_uid()
        (fdir / f"{uid}.eml").write_bytes(raw)
        (fdir / f"{uid}.meta").write_text(
            json.dumps({"uid": uid, "flags": [], "ts": datetime.now().isoformat()}),
            encoding="utf-8",
        )
        return uid

    def set_flags(self, user: str, folder: str, uid: str, flags: list):
        meta_p = self._user_dir(user) / folder / f"{uid}.meta"
        if meta_p.exists():
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
            meta["flags"] = flags
            tmp = meta_p.with_suffix(".tmp")
            tmp.write_text(json.dumps(meta), encoding="utf-8")
            tmp.replace(meta_p)

    def delete_message(self, user: str, folder: str, uid: str):
        fdir = self._user_dir(user) / folder
        for ext in (".eml", ".meta"):
            p = fdir / f"{uid}{ext}"
            if p.exists():
                p.unlink()


# -- SMTP server --


class SMTPHandler:
    def __init__(self, store: MailStore, max_connections: int = 100):
        self.store = store
        self._sem = asyncio.Semaphore(max_connections)

    async def __call__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        if not self._sem._value:  # all slots taken
            writer.write(b"421 Too many connections, try again later\r\n")
            writer.close()
            return
        async with self._sem:
            await self._handle(reader, writer)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = writer.get_extra_info("peername")
        log_smtp.info("Connection from %s", peer)
        writer.write(b"220 AgentoAll SMTP ready\r\n")
        await writer.drain()

        sender: Optional[str] = None
        recipients: list = []

        try:
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=300)
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                upper = text.upper()

                if upper.startswith("EHLO") or upper.startswith("HELO"):
                    writer.write(
                        b"250-AgentoAll\r\n"
                        b"250-AUTH PLAIN LOGIN\r\n"
                        b"250-SIZE 52428800\r\n"
                        b"250 OK\r\n"
                    )

                elif upper.startswith("AUTH PLAIN"):
                    parts = text.split(None, 2)
                    if len(parts) > 2:
                        cred_b64 = parts[2]
                    else:
                        writer.write(b"334\r\n")
                        await writer.drain()
                        cred_line = await reader.readline()
                        cred_b64 = cred_line.decode("utf-8", errors="replace").strip()
                    try:
                        decoded = base64.b64decode(cred_b64).decode("utf-8", errors="replace")
                        # AUTH PLAIN format: \0user\0password
                        auth_parts = decoded.split("\0")
                        auth_user = auth_parts[1] if len(auth_parts) >= 2 else ""
                        auth_pass = auth_parts[2] if len(auth_parts) >= 3 else ""
                        if self.store.authenticate(auth_user, auth_pass):
                            sender = auth_user  # track authenticated sender
                            writer.write(b"235 2.7.0 Authentication successful\r\n")
                        else:
                            writer.write(b"535 5.7.8 Authentication failed\r\n")
                    except Exception:
                        writer.write(b"535 5.7.8 Authentication failed\r\n")

                elif upper.startswith("AUTH LOGIN"):
                    writer.write(b"334 VXNlcm5hbWU6\r\n")
                    await writer.drain()
                    user_line = await reader.readline()
                    writer.write(b"334 UGFzc3dvcmQ6\r\n")
                    await writer.drain()
                    pass_line = await reader.readline()
                    try:
                        auth_user = base64.b64decode(user_line.strip()).decode("utf-8", errors="replace")
                        auth_pass = base64.b64decode(pass_line.strip()).decode("utf-8", errors="replace")
                        if self.store.authenticate(auth_user, auth_pass):
                            sender = auth_user
                            writer.write(b"235 2.7.0 Authentication successful\r\n")
                        else:
                            writer.write(b"535 5.7.8 Authentication failed\r\n")
                    except Exception:
                        writer.write(b"535 5.7.8 Authentication failed\r\n")

                elif upper.startswith("AUTH"):
                    writer.write(b"504 Unrecognized auth type\r\n")

                elif upper.startswith("MAIL FROM:"):
                    sender = self._extract_addr(text)
                    writer.write(b"250 OK\r\n")

                elif upper.startswith("RCPT TO:"):
                    rcpt = self._extract_addr(text)
                    if rcpt:
                        recipients.append(rcpt)
                        writer.write(b"250 OK\r\n")
                    else:
                        writer.write(b"501 Syntax error in recipient address\r\n")

                elif upper.startswith("DATA"):
                    writer.write(b"354 End data with <CRLF>.<CRLF>\r\n")
                    await writer.drain()
                    max_size = 50 * 1024 * 1024  # 50 MB limit
                    chunks = []
                    total = 0
                    overflow = False
                    while True:
                        dline = await reader.readline()
                        if dline in (b".\r\n", b".\n"):
                            break
                        if dline.startswith(b".."):
                            dline = dline[1:]
                        total += len(dline)
                        if total > max_size:
                            overflow = True
                            # drain remaining DATA without storing
                            continue
                        chunks.append(dline)
                    if overflow:
                        writer.write(b"552 Message exceeds size limit\r\n")
                        sender = None
                        recipients = []
                        await writer.drain()
                        continue
                    data = b"".join(chunks)
                    for rcpt in recipients:
                        uid = self.store.deliver(rcpt, data)
                        log_smtp.info(
                            "Delivered  %s -> %s  (%d bytes, uid=%s)",
                            sender, rcpt, len(data), uid,
                        )
                    writer.write(b"250 OK message delivered\r\n")
                    sender = None
                    recipients = []

                elif upper.startswith("STARTTLS"):
                    writer.write(b"454 TLS not available (local test server)\r\n")

                elif upper.startswith("RSET"):
                    sender = None
                    recipients = []
                    writer.write(b"250 OK\r\n")

                elif upper.startswith("NOOP"):
                    writer.write(b"250 OK\r\n")

                elif upper.startswith("QUIT"):
                    writer.write(b"221 Bye\r\n")
                    await writer.drain()
                    break

                else:
                    writer.write(b"502 Command not recognised\r\n")

                await writer.drain()
        except (asyncio.TimeoutError, ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    @staticmethod
    def _extract_addr(line: str) -> Optional[str]:
        m = re.search(r"<([^>]+)>", line)
        if m:
            return m.group(1)
        parts = line.split(":", 1)
        return parts[1].strip() if len(parts) > 1 else None


# -- IMAP server --


class IMAPHandler:
    def __init__(self, store: MailStore, max_connections: int = 100):
        self.store = store
        self._sem = asyncio.Semaphore(max_connections)

    async def __call__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        if not self._sem._value:
            writer.write(b"* BYE Too many connections\r\n")
            writer.close()
            return
        async with self._sem:
            await self._handle(reader, writer)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = writer.get_extra_info("peername")
        log_imap.debug("Connection from %s", peer)
        writer.write(b"* OK AgentoAll IMAP4rev1 ready\r\n")
        await writer.drain()

        user: Optional[str] = None
        sel_folder: Optional[str] = None
        messages: list = []

        try:
            while True:
                raw_line = await asyncio.wait_for(reader.readline(), timeout=300)
                if not raw_line:
                    break
                text = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if not text:
                    continue

                # handle synchronising literal {N}
                literal_data: Optional[bytes] = None
                lit_m = re.search(r"\{(\d+)\}\s*$", text)
                if lit_m:
                    size = int(lit_m.group(1))
                    writer.write(b"+ Ready for literal data\r\n")
                    await writer.drain()
                    literal_data = await reader.readexactly(size)
                    await reader.readline()  # trailing CRLF

                parts = text.split(None, 2)
                if len(parts) < 2:
                    writer.write(b"* BAD Invalid command\r\n")
                    await writer.drain()
                    continue

                tag = parts[0]
                cmd = parts[1].upper()
                rest = parts[2] if len(parts) > 2 else ""

                # -- CAPABILITY --
                if cmd == "CAPABILITY":
                    writer.write(b"* CAPABILITY IMAP4rev1 AUTH=PLAIN\r\n")
                    await self._ok(writer, tag, "CAPABILITY")

                # -- LOGIN --
                elif cmd == "LOGIN":
                    u, p = self._parse_login(rest)
                    if u and self.store.authenticate(u, p):
                        user = u
                        log_imap.info("Login OK: %s", user)
                        await self._ok(writer, tag, "LOGIN")
                    else:
                        log_imap.warning("Login FAILED: %s", rest)
                        await self._no(writer, tag, "LOGIN failed")

                # -- LIST --
                elif cmd == "LIST":
                    if not user:
                        await self._no(writer, tag, "Not authenticated")
                    else:
                        folders = self.store.get_folders(user)
                        for f in folders:
                            writer.write(
                                f'* LIST (\\HasNoChildren) "/" "{f}"\r\n'.encode()
                            )
                        await self._ok(writer, tag, "LIST")

                # -- CREATE --
                elif cmd == "CREATE":
                    if not user:
                        await self._no(writer, tag, "Not authenticated")
                    else:
                        self.store.create_folder(user, rest.strip('"'))
                        await self._ok(writer, tag, "CREATE")

                # -- SELECT / EXAMINE --
                elif cmd in ("SELECT", "EXAMINE"):
                    if not user:
                        await self._no(writer, tag, "Not authenticated")
                    else:
                        sel_folder = rest.strip('"')
                        messages = self.store.get_messages(user, sel_folder)
                        writer.write(f"* {len(messages)} EXISTS\r\n".encode())
                        writer.write(b"* 0 RECENT\r\n")
                        writer.write(
                            b"* FLAGS (\\Seen \\Answered \\Flagged \\Deleted \\Draft)\r\n"
                        )
                        writer.write(b"* OK [UIDVALIDITY 1]\r\n")
                        nxt = int(messages[-1]["uid"]) + 1 if messages else 1
                        writer.write(f"* OK [UIDNEXT {nxt}]\r\n".encode())
                        rw = "READ-WRITE" if cmd == "SELECT" else "READ-ONLY"
                        await self._ok(writer, tag, f"[{rw}] {cmd}")

                # -- UID --
                elif cmd == "UID":
                    await self._handle_uid(
                        writer, tag, rest, user, sel_folder, messages
                    )

                # -- SEARCH (non-UID) --
                elif cmd == "SEARCH":
                    if not sel_folder:
                        await self._no(writer, tag, "No folder selected")
                    else:
                        messages = self.store.get_messages(user, sel_folder)
                        seqs = " ".join(str(i + 1) for i in range(len(messages)))
                        writer.write(f"* SEARCH {seqs}\r\n".encode())
                        await self._ok(writer, tag, "SEARCH")

                # -- FETCH (non-UID) --
                elif cmd == "FETCH":
                    await self._handle_fetch_seq(writer, tag, rest, messages)

                # -- APPEND --
                elif cmd == "APPEND":
                    if not user:
                        await self._no(writer, tag, "Not authenticated")
                    elif literal_data is None:
                        await self._bad(writer, tag, "APPEND requires literal")
                    else:
                        folder = self._parse_append_folder(rest)
                        self.store.append_message(user, folder, literal_data)
                        log_imap.info("Append  user=%s  folder=%s  %d bytes",
                                      user, folder, len(literal_data))
                        await self._ok(writer, tag, "APPEND")

                # -- STORE (non-UID) --
                elif cmd == "STORE":
                    await self._ok(writer, tag, "STORE")

                # -- CLOSE --
                elif cmd == "CLOSE":
                    sel_folder = None
                    messages = []
                    await self._ok(writer, tag, "CLOSE")

                # -- NOOP --
                elif cmd == "NOOP":
                    if sel_folder and user:
                        messages = self.store.get_messages(user, sel_folder)
                        writer.write(f"* {len(messages)} EXISTS\r\n".encode())
                    await self._ok(writer, tag, "NOOP")

                # -- LOGOUT --
                elif cmd == "LOGOUT":
                    writer.write(b"* BYE AgentoAll logging out\r\n")
                    await self._ok(writer, tag, "LOGOUT")
                    await writer.drain()
                    break

                # -- unknown --
                else:
                    await self._bad(writer, tag, f"Unknown command {cmd}")

                await writer.drain()

        except (asyncio.TimeoutError, ConnectionError, asyncio.IncompleteReadError,
                ValueError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    # -- UID sub-commands --

    async def _handle_uid(self, writer, tag, rest, user, folder, messages):
        parts = rest.split(None, 1)
        subcmd = parts[0].upper() if parts else ""
        subrest = parts[1] if len(parts) > 1 else ""

        if not folder:
            await self._no(writer, tag, "No folder selected")
            return

        # refresh messages to pick up new deliveries
        messages = self.store.get_messages(user, folder)

        if subcmd == "SEARCH":
            uids = " ".join(str(m["uid"]) for m in messages)
            writer.write(f"* SEARCH {uids}\r\n".encode())
            await self._ok(writer, tag, "UID SEARCH")

        elif subcmd == "FETCH":
            fetch_parts = subrest.split(None, 1)
            uid_range = fetch_parts[0] if fetch_parts else ""
            fetch_items = fetch_parts[1] if len(fetch_parts) > 1 else "(RFC822)"
            target = self._resolve_uid_set(uid_range, messages)

            for seq_0, msg in enumerate(messages):
                if msg["uid"] not in target:
                    continue
                seq = seq_0 + 1
                raw = self.store.get_raw(msg)
                flags_str = " ".join(msg["meta"].get("flags", []))
                if "RFC822" in fetch_items.upper() or "BODY[]" in fetch_items.upper():
                    hdr = (
                        f"* {seq} FETCH (UID {msg['uid']} "
                        f"FLAGS ({flags_str}) RFC822 {{{len(raw)}}}\r\n"
                    )
                    writer.write(hdr.encode())
                    writer.write(raw)
                    writer.write(b")\r\n")
                elif "FLAGS" in fetch_items.upper():
                    writer.write(
                        f"* {seq} FETCH (UID {msg['uid']} FLAGS ({flags_str}))\r\n".encode()
                    )
            await self._ok(writer, tag, "UID FETCH")

        elif subcmd == "STORE":
            store_parts = subrest.split(None, 2)
            if len(store_parts) >= 3 and user:
                uid_val = store_parts[0]
                flags_action = store_parts[1]
                raw_flags = re.findall(r"\\(\w+)", store_parts[2])
                new_flags = [f"\\{f}" for f in raw_flags]
                for msg in messages:
                    if str(msg["uid"]) == uid_val:
                        cur = msg["meta"].get("flags", [])
                        if "+" in flags_action:
                            cur = list(set(cur + new_flags))
                        elif "-" in flags_action:
                            cur = [f for f in cur if f not in new_flags]
                        else:
                            cur = new_flags
                        self.store.set_flags(user, folder, msg["uid"], cur)
            await self._ok(writer, tag, "UID STORE")

        else:
            await self._bad(writer, tag, f"Unknown UID sub-command {subcmd}")

    # -- fetch by sequence number --

    async def _handle_fetch_seq(self, writer, tag, rest, messages):
        fetch_parts = rest.split(None, 1)
        seq_range = fetch_parts[0] if fetch_parts else ""
        fetch_items = fetch_parts[1] if len(fetch_parts) > 1 else "(RFC822)"

        for seq_s in self._resolve_seq_set(seq_range, len(messages)):
            seq = int(seq_s)
            if 1 <= seq <= len(messages):
                msg = messages[seq - 1]
                raw = self.store.get_raw(msg)
                flags_str = " ".join(msg["meta"].get("flags", []))
                if "RFC822" in fetch_items.upper() or "BODY[]" in fetch_items.upper():
                    hdr = (
                        f"* {seq} FETCH (FLAGS ({flags_str}) RFC822 {{{len(raw)}}}\r\n"
                    )
                    writer.write(hdr.encode())
                    writer.write(raw)
                    writer.write(b")\r\n")
        await self._ok(writer, tag, "FETCH")

    # -- helpers --

    @staticmethod
    def _resolve_uid_set(spec: str, messages: list) -> set:
        all_uids = {str(m["uid"]) for m in messages}
        if not spec or spec == "*":
            return all_uids
        if ":" in spec:
            lo, hi = spec.split(":", 1)
            if hi == "*":
                return {u for u in all_uids if int(u) >= int(lo)}
            return {u for u in all_uids if int(lo) <= int(u) <= int(hi)}
        if "," in spec:
            return set(spec.split(",")) & all_uids
        return {spec} & all_uids

    @staticmethod
    def _resolve_seq_set(spec: str, total: int) -> list:
        if not spec or spec == "*":
            return [str(i) for i in range(1, total + 1)]
        if ":" in spec:
            lo, hi = spec.split(":", 1)
            hi_int = total if hi == "*" else int(hi)
            return [str(i) for i in range(int(lo), hi_int + 1)]
        return [spec]

    @staticmethod
    def _parse_login(rest: str) -> Tuple[str, str]:
        tokens = []
        for m in re.finditer(r'"([^"]*)"|(\S+)', rest):
            tokens.append(m.group(1) if m.group(1) is not None else m.group(2))
        if len(tokens) >= 2:
            return tokens[0], tokens[1]
        return "", ""

    @staticmethod
    def _parse_append_folder(rest: str) -> str:
        m = re.match(r'"([^"]*)"', rest) or re.match(r"(\S+)", rest)
        return m.group(1) if m else "INBOX"

    @staticmethod
    async def _ok(w, tag, msg):
        w.write(f"{tag} OK {msg} completed\r\n".encode())

    @staticmethod
    async def _no(w, tag, msg):
        w.write(f"{tag} NO {msg}\r\n".encode())

    @staticmethod
    async def _bad(w, tag, msg):
        w.write(f"{tag} BAD {msg}\r\n".encode())


# -- POP3 server --


class POP3Handler:
    def __init__(self, store: MailStore, max_connections: int = 50):
        self.store = store
        self._sem = asyncio.Semaphore(max_connections)

    async def __call__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        if not self._sem._value:
            writer.write(b"-ERR Too many connections\r\n")
            writer.close()
            return
        async with self._sem:
            await self._handle(reader, writer)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = writer.get_extra_info("peername")
        log_pop3.debug("Connection from %s", peer)
        writer.write(b"+OK AgentoAll POP3 ready\r\n")
        await writer.drain()

        user: Optional[str] = None
        authed = False
        messages: list = []
        deleted: set = set()

        try:
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=300)
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                parts = text.split(None, 1)
                cmd = parts[0].upper() if parts else ""
                arg = parts[1] if len(parts) > 1 else ""

                if cmd == "CAPA":
                    writer.write(b"+OK\r\nUSER\r\nUIDL\r\nTOP\r\n.\r\n")

                elif cmd == "USER":
                    user = arg
                    writer.write(b"+OK\r\n")

                elif cmd == "PASS":
                    if user and self.store.authenticate(user, arg):
                        authed = True
                        messages = self.store.get_messages(user, "INBOX")
                        log_pop3.info("Login OK: %s (%d msgs)", user, len(messages))
                        writer.write(f"+OK {len(messages)} messages\r\n".encode())
                    else:
                        writer.write(b"-ERR Authentication failed\r\n")

                elif cmd == "STAT":
                    if not authed:
                        writer.write(b"-ERR Not authenticated\r\n")
                    else:
                        active = [(i, m) for i, m in enumerate(messages) if i not in deleted]
                        total = sum(m.get("size", 0) for _, m in active)
                        writer.write(f"+OK {len(active)} {total}\r\n".encode())

                elif cmd == "LIST":
                    if not authed:
                        writer.write(b"-ERR Not authenticated\r\n")
                    elif arg:
                        idx = int(arg) - 1
                        if 0 <= idx < len(messages) and idx not in deleted:
                            writer.write(f"+OK {arg} {messages[idx].get('size', 0)}\r\n".encode())
                        else:
                            writer.write(b"-ERR No such message\r\n")
                    else:
                        active = [(i, m) for i, m in enumerate(messages) if i not in deleted]
                        writer.write(f"+OK {len(active)} messages\r\n".encode())
                        for i, m in active:
                            writer.write(f"{i+1} {m.get('size', 0)}\r\n".encode())
                        writer.write(b".\r\n")

                elif cmd == "UIDL":
                    if not authed:
                        writer.write(b"-ERR Not authenticated\r\n")
                    elif arg:
                        idx = int(arg) - 1
                        if 0 <= idx < len(messages) and idx not in deleted:
                            writer.write(f"+OK {arg} {messages[idx]['uid']}\r\n".encode())
                        else:
                            writer.write(b"-ERR No such message\r\n")
                    else:
                        writer.write(b"+OK\r\n")
                        for i, m in enumerate(messages):
                            if i not in deleted:
                                writer.write(f"{i+1} {m['uid']}\r\n".encode())
                        writer.write(b".\r\n")

                elif cmd == "RETR":
                    if not authed:
                        writer.write(b"-ERR Not authenticated\r\n")
                    else:
                        idx = int(arg) - 1
                        if 0 <= idx < len(messages) and idx not in deleted:
                            raw = self.store.get_raw(messages[idx])
                            writer.write(f"+OK {len(raw)} octets\r\n".encode())
                            for raw_line in raw.split(b"\n"):
                                out = raw_line.rstrip(b"\r")
                                if out.startswith(b"."):
                                    writer.write(b"." + out + b"\r\n")
                                else:
                                    writer.write(out + b"\r\n")
                            writer.write(b".\r\n")
                        else:
                            writer.write(b"-ERR No such message\r\n")

                elif cmd == "DELE":
                    if not authed:
                        writer.write(b"-ERR Not authenticated\r\n")
                    else:
                        idx = int(arg) - 1
                        if 0 <= idx < len(messages):
                            deleted.add(idx)
                            writer.write(b"+OK Deleted\r\n")
                        else:
                            writer.write(b"-ERR No such message\r\n")

                elif cmd == "RSET":
                    deleted.clear()
                    writer.write(b"+OK\r\n")

                elif cmd == "NOOP":
                    writer.write(b"+OK\r\n")

                elif cmd == "QUIT":
                    if authed:
                        for idx in sorted(deleted, reverse=True):
                            if 0 <= idx < len(messages):
                                self.store.delete_message(user, "INBOX", messages[idx]["uid"])
                    writer.write(b"+OK Bye\r\n")
                    await writer.drain()
                    break

                else:
                    writer.write(b"-ERR Unknown command\r\n")

                await writer.drain()

        except (asyncio.TimeoutError, ConnectionError, asyncio.IncompleteReadError,
                ValueError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass


# -- main --


async def run_server(args):
    store = MailStore(args.data_dir)

    # create accounts
    if not store.accounts:
        n = args.create_accounts
        for i in range(1, n + 1):
            store.ensure_account(f"agent{i}@localhost", "password")
        store.ensure_account("human@localhost", "password")

    log_main.info("Accounts: %s", ", ".join(sorted(store.accounts.keys())))

    host = args.host

    # find available ports
    smtp_port = find_port(host, args.smtp_port, 2525, 2600)
    imap_port = find_port(host, args.imap_port, 1143, 1200)
    pop3_port = find_port(host, args.pop3_port, 1110, 1200)

    smtp_handler = SMTPHandler(store)
    imap_handler = IMAPHandler(store)
    pop3_handler = POP3Handler(store)

    smtp_srv = await asyncio.start_server(smtp_handler, host, smtp_port)
    imap_srv = await asyncio.start_server(imap_handler, host, imap_port)
    pop3_srv = await asyncio.start_server(pop3_handler, host, pop3_port)

    print()
    print("=" * 52)
    print("  AgentoAll Local Email Server")
    print("=" * 52)
    print(f"  SMTP : {host}:{smtp_port}")
    print(f"  IMAP : {host}:{imap_port}")
    print(f"  POP3 : {host}:{pop3_port}")
    print(f"  Data : {args.data_dir}")
    print()
    print("  Accounts (all passwords: 'password'):")
    for addr in sorted(store.accounts.keys()):
        print(f"    {addr}")
    print()
    print("  Press Ctrl+C to stop")
    print("=" * 52)
    print()

    # write a server info file for other tools to read
    info = {
        "smtp_host": host, "smtp_port": smtp_port,
        "imap_host": host, "imap_port": imap_port,
        "pop3_host": host, "pop3_port": pop3_port,
        "data_dir": args.data_dir,
        "accounts": list(store.accounts.keys()),
    }
    info_path = Path(args.data_dir) / "server_info.json"
    info_path.write_text(json.dumps(info, indent=2), encoding="utf-8")

    try:
        await asyncio.gather(
            smtp_srv.serve_forever(),
            imap_srv.serve_forever(),
            pop3_srv.serve_forever(),
        )
    except asyncio.CancelledError:
        pass


def main():
    p = ArgumentParser(description="AgentoAll Local Email Server")
    p.add_argument("--host", default="127.0.0.1", help="Bind address")
    p.add_argument("--smtp-port", type=int, default=2525)
    p.add_argument("--imap-port", type=int, default=1143)
    p.add_argument("--pop3-port", type=int, default=1110)
    p.add_argument("--data-dir", default="./data/email_store",
                   help="Mail storage directory")
    p.add_argument("--create-accounts", type=int, default=3,
                   help="Number of agent accounts to create (agent1..agentN)")
    args = p.parse_args()

    try:
        asyncio.run(run_server(args))
    except KeyboardInterrupt:
        log_main.info("Server stopped.")


if __name__ == "__main__":
    main()
