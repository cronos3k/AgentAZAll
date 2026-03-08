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
from .messages import parse_message
from .transport_email import EmailTransport
from .transport_ftp import FTPTransport

log = logging.getLogger("agentazall")


class Daemon:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        transport = cfg.get("transport", "email")
        self.use_email = transport in ("email", "both")
        self.use_ftp = transport in ("ftp", "both")
        self.email = EmailTransport(cfg) if self.use_email else None
        self.ftp = FTPTransport(cfg) if self.use_ftp else None

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
            if self.email:
                self.email.imap_disconnect()
            log.info("Daemon stopped")

    def _cycle(self):
        ensure_dirs(self.cfg)
        changed = set()

        # 1. Send outbox
        sent = self._send_outbox_unified()
        if sent:
            changed.add(today_str())

        # 2. Receive inbox
        if self.use_email:
            rx = self._email_receive()
            if rx:
                changed.add(today_str())
        if self.use_ftp:
            seen = load_seen(self.cfg)
            rx = self.ftp.fetch_inbox(self.cfg, seen)
            if rx:
                save_seen(self.cfg, seen)
                changed.add(today_str())

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

                to_list = [a.strip() for a in h["To"].split(",") if a.strip()]
                cc_list = [a.strip() for a in h.get("Cc", "").split(",") if a.strip()]
                subject = h.get("Subject", "No Subject")
                att_dir = outbox / mf.stem
                att_paths = [str(f) for f in att_dir.iterdir()] if att_dir.is_dir() else []

                ok_email = True
                ok_ftp = True

                # email transport
                if self.use_email:
                    ok_email = self.email.send(
                        to_list, cc_list, subject, body or "",
                        agent, att_paths)

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
                if ok_email or ok_ftp or ok_local:
                    sentd = mf.parent.parent / SENT
                    sentd.mkdir(exist_ok=True)
                    safe_move(str(mf), str(sentd / mf.name))
                    if att_dir.is_dir():
                        dest = sentd / mf.stem
                        if dest.exists():
                            shutil.rmtree(str(dest))
                        shutil.move(str(att_dir), str(dest))
                    via = "+".join(filter(None, [
                        "email" if ok_email and self.use_email else "",
                        "ftp" if ok_ftp and self.use_ftp else "",
                        "local" if ok_local else ""]))
                    log.info("Sent %s -> %s via %s",
                             mf.stem[:8], ", ".join(to_list), via or "none")
                    sent_count += 1

        return sent_count

    def _email_receive(self) -> int:
        seen = load_seen(self.cfg)
        msgs = self.email.receive(seen)
        count = 0
        for uid, headers, body, atts in msgs:
            try:
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
