"""AgentAZAll daemon — background sync loop for email/FTP transports."""

import email as email_mod
import email.mime.text
import email.utils
import logging
import re
import shutil
import time
from datetime import date, timedelta
from pathlib import Path

from .config import (
    INBOX,
    OUTBOX,
    REMEMBER,
    SENT,
    WHAT_AM_I_DOING,
    WHO_AM_I,
)
from .finder import load_seen, save_seen
from .helpers import (
    agent_base,
    agent_day,
    date_dirs,
    ensure_dirs,
    generate_id,
    now_str,
    safe_move,
    today_str,
)
from .index import build_index, build_remember_index
from .address_filter import should_accept
from .identity import load_keypair, public_key_b64, Keyring, fingerprint_from_b64
from .messages import parse_message, verify_message
from .transport_agenttalk import AgentTalkTransport
from .transport_email import EmailTransport
from .transport_ftp import FTPTransport

log = logging.getLogger("agentazall")


class Daemon:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        transport = cfg.get("transport", "email")
        self.use_email = transport in ("email", "both")
        self.use_ftp = transport in ("ftp", "both")
        self.use_agenttalk = transport == "agenttalk"

        # Build transport arrays from migrated config
        self.email_transports = []
        self.relay_transports = []
        self.ftp_transports = []

        # Email: one instance per configured account
        if self.use_email:
            for acct in cfg.get("email_accounts", []):
                tcfg = dict(cfg)
                tcfg["email"] = acct
                self.email_transports.append(EmailTransport(tcfg))
            # Fallback to legacy single config
            if not self.email_transports:
                self.email_transports.append(EmailTransport(cfg))

        # AgentTalk relays: one instance per relay
        for relay in cfg.get("relays", []):
            tcfg = dict(cfg)
            tcfg["agenttalk"] = {
                "server": relay.get("server", ""),
                "token": relay.get("token", ""),
            }
            self.relay_transports.append(AgentTalkTransport(tcfg))
        # Fallback to legacy single config
        if not self.relay_transports and self.use_agenttalk:
            self.relay_transports.append(AgentTalkTransport(cfg))

        # FTP: one instance per server
        if self.use_ftp:
            for srv in cfg.get("ftp_servers", []):
                tcfg = dict(cfg)
                tcfg["ftp"] = srv
                self.ftp_transports.append(FTPTransport(tcfg))
            if not self.ftp_transports:
                self.ftp_transports.append(FTPTransport(cfg))

        # Legacy single-instance aliases (used by existing send/receive code)
        self.email = self.email_transports[0] if self.email_transports else None
        self.ftp = self.ftp_transports[0] if self.ftp_transports else None
        self.agenttalk = self.relay_transports[0] if self.relay_transports else None

        # Update flags if we have transports from arrays
        if self.relay_transports and not self.use_agenttalk:
            self.use_agenttalk = True

        total = len(self.email_transports) + len(self.relay_transports) + len(self.ftp_transports)
        log.info("Transports: %d email, %d relay, %d ftp (%d total)",
                 len(self.email_transports), len(self.relay_transports),
                 len(self.ftp_transports), total)

        # Ed25519 signing identity
        base = agent_base(cfg)
        kp = load_keypair(base)
        if kp:
            self.signing_key, self.verify_key = kp
            self.pk_b64 = public_key_b64(self.verify_key)
            log.info("Crypto identity loaded: %s", fingerprint_from_b64(self.pk_b64))
        else:
            self.signing_key = None
            self.verify_key = None
            self.pk_b64 = None
            log.warning("No Ed25519 identity — messages will be unsigned")

        # Peer keyring
        self.keyring = Keyring(base)

    def run(self, once=False):
        agent = self.cfg["agent_name"]
        interval = self.cfg.get("sync_interval", 10)
        log.info("Daemon started  agent=%s  transport=%s  interval=%ds",
                 agent, self.cfg.get("transport", "email"), interval)
        ensure_dirs(self.cfg)
        try:
            while True:
                try:
                    self._cycle()
                except KeyboardInterrupt:
                    raise
                except Exception:
                    log.exception("Daemon cycle error (will retry)")
                if once:
                    break
                time.sleep(interval)
        except KeyboardInterrupt:
            pass
        finally:
            for et in self.email_transports:
                try:
                    et.imap_disconnect()
                except Exception:
                    pass
            log.info("Daemon stopped")

    def _cycle(self):
        ensure_dirs(self.cfg)
        changed = set()

        # 1. Send outbox
        sent = self._send_outbox_unified()
        if sent:
            changed.add(today_str())

        # 2. Receive inbox — iterate all transport instances
        for et in self.email_transports:
            try:
                rx = self._email_receive_from(et)
                if rx:
                    changed.add(today_str())
            except Exception:
                log.exception("Email receive error")
        for ft in self.ftp_transports:
            try:
                seen = load_seen(self.cfg)
                rx = ft.fetch_inbox(self.cfg, seen)
                if rx:
                    save_seen(self.cfg, seen)
                    changed.add(today_str())
            except Exception:
                log.exception("FTP receive error")
        for rt in self.relay_transports:
            try:
                rx = self._agenttalk_receive_from(rt)
                if rx:
                    changed.add(today_str())
            except Exception:
                log.exception("AgentTalk receive error")

        # 3. Sync special folders
        if self.use_email and self.cfg["email"].get("sync_special_folders"):
            self._email_sync_special()
        if self.use_ftp:
            try:
                self.ftp.sync_special(self.cfg)
                self.ftp.restore_special(self.cfg)
            except Exception:
                pass

        # 4. Rebuild indexes
        build_index(self.cfg, today_str())
        for d in changed:
            if d != today_str():
                build_index(self.cfg, d)
        build_remember_index(self.cfg)

    def _send_outbox_unified(self) -> int:
        """Process outbox via all active transports."""
        b = agent_base(self.cfg)
        agent = self.cfg["agent_name"]
        sent_count = 0

        for dd_name in date_dirs(self.cfg):
            outbox = b / dd_name / OUTBOX
            if not outbox.exists():
                continue
            for mf in sorted(outbox.glob("*.txt")):
                h, body = parse_message(mf)
                if not h or not h.get("To"):
                    continue

                # Sign outgoing message if we have an identity and it's unsigned
                if self.signing_key and not h.get("Signature"):
                    self._sign_outbox_file(mf, h, body)

                to_list = [a.strip() for a in h["To"].split(",") if a.strip()]
                cc_list = [a.strip() for a in h.get("Cc", "").split(",") if a.strip()]
                subject = h.get("Subject", "No Subject")
                att_dir = outbox / mf.stem
                att_paths = [str(f) for f in att_dir.iterdir()] if att_dir.is_dir() else []

                ok_email = True
                ok_ftp = True

                # email transports (all instances)
                for et in self.email_transports:
                    try:
                        ok_email = et.send(
                            to_list, cc_list, subject, body or "",
                            agent, att_paths) and ok_email
                    except Exception as exc:
                        log.error("Email send %s: %s", mf.stem[:8], exc)
                        ok_email = False

                # agenttalk relay transports (all instances)
                ok_agenttalk = True
                for rt in self.relay_transports:
                    try:
                        ok_agenttalk = rt.send(
                            to_list, cc_list, subject, body or "",
                            agent, att_paths) and ok_agenttalk
                    except Exception as exc:
                        log.error("Relay send %s: %s", mf.stem[:8], exc)
                        ok_agenttalk = False

                # ftp transport
                if self.use_ftp:
                    ftp = None
                    try:
                        ftp = self.ftp.connect()
                        if ftp:
                            for rcpt in to_list + cc_list:
                                rinbox = f"/{rcpt}/{dd_name}/{INBOX}"
                                FTPTransport._upload(ftp, str(mf), f"{rinbox}/{mf.name}")
                                if att_dir.is_dir():
                                    for af in att_dir.iterdir():
                                        FTPTransport._upload(
                                            ftp, str(af),
                                            f"{rinbox}/{mf.stem}/{af.name}")
                            rsent = f"/{agent}/{dd_name}/{SENT}"
                            FTPTransport._upload(ftp, str(mf), f"{rsent}/{mf.name}")
                        else:
                            ok_ftp = False
                    except Exception as e:
                        log.error("FTP send %s: %s", mf.stem[:8], e)
                        ok_ftp = False
                    finally:
                        if ftp:
                            try:
                                ftp.quit()
                            except Exception:
                                pass

                # local filesystem delivery
                ok_local = False
                mb_root = Path(self.cfg["mailbox_dir"])
                for rcpt in to_list + cc_list:
                    rcpt_base = mb_root / rcpt
                    if rcpt_base.exists() and rcpt != agent:
                        try:
                            rcpt_inbox = rcpt_base / dd_name / INBOX
                            rcpt_inbox.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(str(mf), str(rcpt_inbox / mf.name))
                            if att_dir.is_dir():
                                adest = rcpt_inbox / mf.stem
                                if adest.exists():
                                    shutil.rmtree(str(adest))
                                shutil.copytree(str(att_dir), str(adest))
                            ok_local = True
                        except Exception as e:
                            log.error("Local deliver %s -> %s: %s", mf.stem[:8], rcpt, e)

                # Move to sent/ if at least one delivery method succeeded
                if ok_email or ok_ftp or ok_local or (
                    self.use_agenttalk and ok_agenttalk):
                    sentd = mf.parent.parent / SENT
                    sentd.mkdir(exist_ok=True)
                    safe_move(str(mf), str(sentd / mf.name))
                    if att_dir.is_dir():
                        dest = sentd / mf.stem
                        if dest.exists():
                            shutil.rmtree(str(dest))
                        shutil.move(str(att_dir), str(dest))
                    via = "+".join(filter(None, [
                        "email" if ok_email and self.email_transports else "",
                        "agenttalk" if ok_agenttalk and self.relay_transports else "",
                        "ftp" if ok_ftp and self.ftp_transports else "",
                        "local" if ok_local else ""]))
                    log.info("Sent %s -> %s via %s",
                             mf.stem[:8], ", ".join(to_list), via or "none")
                    sent_count += 1

        return sent_count

    def _sign_outbox_file(self, mf: Path, headers: dict, body: str):
        """Inject Public-Key + Signature headers into an outbox message file."""
        from .identity import sign_message
        # Build header lines (preserving order) with Public-Key added
        lines = []
        for k, v in headers.items():
            lines.append(f"{k}: {v}")
        lines.append(f"Public-Key: {self.pk_b64}")

        # Compute signature over all headers + --- + body
        signable = "\n".join(lines) + "\n---\n" + body
        sig = sign_message(self.signing_key, signable)
        lines.append(f"Signature: {sig}")

        # Rewrite file
        lines += ["", "---", body]
        mf.write_text("\n".join(lines), encoding="utf-8")

    def _verify_incoming(self, headers: dict, body: str, sender: str):
        """Verify signature on incoming message, update keyring."""
        result = verify_message(headers, body)
        if result is True:
            pk = headers.get("Public-Key", "")
            fp = fingerprint_from_b64(pk)
            self.keyring.add(fp, pk, sender)
            log.debug("Verified sig from %s (fp=%s)", sender, fp)
        elif result is False:
            log.warning("INVALID signature from %s — message accepted but untrusted", sender)
        # result is None → unsigned (legacy agent), no action needed

    def _email_receive_from(self, transport: EmailTransport) -> int:
        seen = load_seen(self.cfg)
        msgs = transport.receive(seen)
        count = 0
        for uid, headers, body, atts in msgs:
            try:
                # Address filter — discard before writing to disk
                sender = headers.get("From", "")
                if not should_accept(self.cfg, sender):
                    seen.add(uid)
                    continue

                ds = today_str()
                try:
                    dt = email_mod.utils.parsedate_to_datetime(headers.get("Date", ""))
                    ds = dt.date().isoformat()
                except Exception:
                    pass

                ensure_dirs(self.cfg, ds)
                msg_id = generate_id(
                    headers.get("From", ""), headers.get("To", ""),
                    headers.get("Subject", ""))
                lines = [
                    f"From: {headers.get('From', '')}",
                    f"To: {headers.get('To', '')}",
                ]
                if headers.get("Cc"):
                    lines.append(f"Cc: {headers['Cc']}")
                date_val = headers.get("Date", "").strip() or now_str()
                lines += [
                    f"Subject: {headers.get('Subject', '')}",
                    f"Date: {date_val}",
                    f"Message-ID: {msg_id}",
                    "Status: new",
                ]
                if atts:
                    lines.append(f"Attachments: {', '.join(n for n, _ in atts)}")
                lines += ["", "---", body]

                inbox_dir = agent_day(self.cfg, ds) / INBOX
                fpath = inbox_dir / f"{msg_id}.txt"
                fpath.write_text("\n".join(lines), encoding="utf-8")

                if atts:
                    adir = inbox_dir / msg_id
                    adir.mkdir(exist_ok=True)
                    for fname, data in atts:
                        safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', fname)
                        (adir / safe).write_bytes(data)

                seen.add(uid)
                log.info("Email recv %s subj=%s", msg_id[:8], headers.get("Subject", "?"))
                count += 1
            except Exception as e:
                log.error("Email save uid=%s: %s", uid, e)
        if count:
            save_seen(self.cfg, seen)
        return count

    def _agenttalk_receive_from(self, transport: AgentTalkTransport) -> int:
        """Fetch messages from AgentTalk relay and save to local inbox."""
        seen = load_seen(self.cfg)
        msgs = transport.receive(seen)
        count = 0
        for uid, headers, body, atts in msgs:
            try:
                # Address filter — discard before writing to disk
                sender = headers.get("From", "")
                if not should_accept(self.cfg, sender):
                    continue

                ds = today_str()
                # Try to parse timestamp from message
                try:
                    dt_str = headers.get("Date", "")
                    if "T" in dt_str:  # ISO format from relay
                        ds = dt_str[:10]
                except Exception:
                    pass

                ensure_dirs(self.cfg, ds)
                msg_id = headers.get("Message-ID", "") or generate_id(
                    headers.get("From", ""), headers.get("To", ""),
                    headers.get("Subject", ""))

                lines = [
                    f"From: {headers.get('From', '')}",
                    f"To: {headers.get('To', '')}",
                    f"Subject: {headers.get('Subject', '')}",
                    f"Date: {headers.get('Date', '') or now_str()}",
                    f"Message-ID: {msg_id}",
                    "Status: new",
                ]
                # Preserve crypto headers if present
                if headers.get("Public-Key"):
                    lines.append(f"Public-Key: {headers['Public-Key']}")
                if headers.get("Signature"):
                    lines.append(f"Signature: {headers['Signature']}")
                if atts:
                    lines.append(f"Attachments: {', '.join(n for n, _ in atts)}")
                lines += ["", "---", body]

                inbox_dir = agent_day(self.cfg, ds) / INBOX
                fpath = inbox_dir / f"{msg_id}.txt"
                fpath.write_text("\n".join(lines), encoding="utf-8")

                if atts:
                    adir = inbox_dir / msg_id
                    adir.mkdir(exist_ok=True)
                    for fname, data in atts:
                        safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', fname)
                        (adir / safe).write_bytes(data)

                # Verify Ed25519 signature if present
                self._verify_incoming(headers, body, sender)

                log.info("AgentTalk recv %s subj=%s",
                         msg_id[:8], headers.get("Subject", "?"))
                count += 1
            except Exception as e:
                log.error("AgentTalk save uid=%s: %s", uid, e)
        if count:
            save_seen(self.cfg, seen)
        return count

    def _email_sync_special(self):
        today = today_str()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        sync_pairs = [
            (WHO_AM_I, "WhoAmI"),
            (WHAT_AM_I_DOING, "WhatAmIDoing"),
            (REMEMBER, "Remember"),
        ]
        for day in (today, yesterday):
            for local_name, imap_folder in sync_pairs:
                ldir = agent_day(self.cfg, day) / local_name
                if not ldir.exists():
                    continue
                for f in ldir.glob("*.txt"):
                    marker = f.with_suffix(".synced")
                    if marker.exists():
                        continue
                    try:
                        txt = f.read_text(encoding="utf-8")
                        m = email_mod.mime.text.MIMEText(txt, "plain", "utf-8")
                        m["From"] = self.cfg["agent_name"]
                        m["To"] = self.cfg["agent_name"]
                        m["Subject"] = f"[{local_name}] {f.stem} - {day}"
                        m["Date"] = email_mod.utils.formatdate(localtime=True)
                        if self.email.imap_upload(imap_folder, m.as_bytes()):
                            marker.write_text(now_str(), encoding="utf-8")
                    except Exception:
                        pass
