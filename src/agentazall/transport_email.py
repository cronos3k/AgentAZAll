"""AgentAZAll email transport — SMTP + IMAP/POP3."""

import email as email_mod
import email.encoders
import email.mime.base
import email.mime.multipart
import email.mime.text
import email.utils
import imaplib
import logging
import mimetypes
import poplib
import smtplib
import ssl
import time
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import List, Tuple

log = logging.getLogger("agentazall")


class EmailTransport:
    """SMTP + IMAP/POP3 transport."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.ec = cfg["email"]
        self._imap = None

    # -- IMAP --

    def imap_connect(self) -> bool:
        try:
            if self.ec["imap_ssl"]:
                ctx = ssl.create_default_context()
                self._imap = imaplib.IMAP4_SSL(
                    self.ec["imap_server"], self.ec["imap_port"], ssl_context=ctx)
            else:
                self._imap = imaplib.IMAP4(self.ec["imap_server"], self.ec["imap_port"])
            self._imap.login(self.ec["username"], self.ec["password"])
            return True
        except Exception as e:
            log.error("IMAP connect: %s", e)
            return False

    def imap_disconnect(self):
        if self._imap:
            try:
                self._imap.close()
            except Exception:
                pass
            try:
                self._imap.logout()
            except Exception:
                pass
            self._imap = None

    def fetch_inbox(self, seen: set) -> List[Tuple[str, bytes]]:
        """Returns list of (uid, raw_rfc822_bytes)."""
        if not self._imap and not self.imap_connect():
            return []
        try:
            st, _ = self._imap.select(self.ec.get("imap_folder", "INBOX"), readonly=True)
            if st != "OK":
                return []
            st, data = self._imap.uid("search", None, "ALL")
            if st != "OK":
                return []
            results = []
            for uid_b in data[0].split():
                uid = uid_b.decode()
                if uid in seen:
                    continue
                st2, mdata = self._imap.uid("fetch", uid_b, "(RFC822)")
                if st2 != "OK":
                    continue
                for part in mdata:
                    if isinstance(part, tuple):
                        results.append((uid, part[1]))
            return results
        except Exception as e:
            log.error("IMAP fetch: %s", e)
            self._imap = None
            return []

    def imap_upload(self, folder: str, raw: bytes) -> bool:
        if not self._imap and not self.imap_connect():
            return False
        try:
            try:
                self._imap.create(folder)
            except Exception:
                pass
            dt = imaplib.Time2Internaldate(time.time())
            st, _ = self._imap.append(folder, "", dt, raw)
            return st == "OK"
        except Exception as e:
            log.error("IMAP upload (%s): %s", folder, e)
            self._imap = None
            return False

    # -- POP3 --

    def pop3_fetch(self, seen: set) -> List[Tuple[str, bytes]]:
        try:
            if self.ec.get("pop3_ssl"):
                conn = poplib.POP3_SSL(self.ec["pop3_server"], self.ec["pop3_port"])
            else:
                conn = poplib.POP3(self.ec["pop3_server"], self.ec["pop3_port"])
            conn.user(self.ec["username"])
            conn.pass_(self.ec["password"])
            count, _ = conn.stat()
            results = []
            for i in range(1, count + 1):
                resp = conn.uidl(i)
                uid = resp.decode().split()[-1] if isinstance(resp, bytes) else str(resp).split()[-1]
                if uid in seen:
                    continue
                _, lines, _ = conn.retr(i)
                results.append((uid, b"\r\n".join(lines)))
            conn.quit()
            return results
        except Exception as e:
            log.error("POP3 fetch: %s", e)
            return []

    # -- SMTP --

    def smtp_send(self, recipients: List[str], raw: bytes) -> bool:
        srv = None
        try:
            if self.ec["smtp_ssl"]:
                ctx = ssl.create_default_context()
                srv = smtplib.SMTP_SSL(self.ec["smtp_server"], self.ec["smtp_port"], context=ctx)
            else:
                srv = smtplib.SMTP(self.ec["smtp_server"], self.ec["smtp_port"], timeout=30)
                if self.ec.get("smtp_starttls"):
                    srv.starttls()
            if self.ec.get("password"):
                srv.login(self.ec["username"], self.ec["password"])
            srv.sendmail(self.cfg["agent_name"], recipients, raw)
            return True
        except Exception as e:
            log.error("SMTP send: %s", e)
            return False
        finally:
            if srv:
                try:
                    srv.quit()
                except Exception:
                    pass

    # -- high-level: receive --

    def receive(self, seen: set) -> List[Tuple[str, dict, str, List[Tuple[str, bytes]]]]:
        """Returns list of (uid, headers_dict, body_text, attachments_list)."""
        if self.ec.get("use_pop3"):
            raw_msgs = self.pop3_fetch(seen)
        else:
            raw_msgs = self.fetch_inbox(seen)

        results = []
        for uid, raw in raw_msgs:
            try:
                msg = BytesParser(policy=policy.default).parsebytes(raw)
                headers = {
                    "From": str(msg.get("From", "")),
                    "To": str(msg.get("To", "")),
                    "Cc": str(msg.get("Cc", "")),
                    "Subject": str(msg.get("Subject", "")),
                    "Date": str(msg.get("Date", "")),
                    "Message-ID": str(msg.get("Message-ID", "")),
                }
                body = self._extract_text(msg)
                atts = self._extract_attachments(msg)
                results.append((uid, headers, body, atts))
            except Exception as e:
                log.error("Parse email uid=%s: %s", uid, e)
        return results

    # -- high-level: send --

    def send(self, to_list, cc_list, subject, body, from_addr, att_paths=None) -> bool:
        if att_paths:
            mime = email_mod.mime.multipart.MIMEMultipart()
            mime.attach(email_mod.mime.text.MIMEText(body, "plain", "utf-8"))
            for ap in att_paths:
                p = Path(ap)
                mt = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
                main, sub = mt.split("/")
                att = email_mod.mime.base.MIMEBase(main, sub)
                att.set_payload(p.read_bytes())
                email_mod.encoders.encode_base64(att)
                att.add_header("Content-Disposition", "attachment", filename=p.name)
                mime.attach(att)
        else:
            mime = email_mod.mime.text.MIMEText(body, "plain", "utf-8")
        domain = from_addr.split("@")[-1] if "@" in from_addr else "localhost"
        mime["From"] = from_addr
        mime["To"] = ", ".join(to_list)
        if cc_list:
            mime["Cc"] = ", ".join(cc_list)
        mime["Subject"] = subject
        mime["Date"] = email_mod.utils.formatdate(localtime=True)
        mime["Message-ID"] = email_mod.utils.make_msgid(domain=domain)
        return self.smtp_send(to_list + cc_list, mime.as_bytes())

    # -- helpers --

    @staticmethod
    def _extract_text(msg) -> str:
        if msg.is_multipart():
            parts = []
            for part in msg.walk():
                ct = part.get_content_type()
                disp = str(part.get("Content-Disposition", ""))
                if ct == "text/plain" and "attachment" not in disp:
                    try:
                        raw = part.get_payload(decode=True)
                        cs = part.get_content_charset() or "utf-8"
                        parts.append(raw.decode(cs, errors="replace"))
                    except Exception:
                        pass
            return "\n".join(parts) if parts else "[No text content]"
        try:
            raw = msg.get_payload(decode=True)
            return raw.decode(msg.get_content_charset() or "utf-8", errors="replace")
        except Exception:
            return "[Could not decode]"

    @staticmethod
    def _extract_attachments(msg) -> List[Tuple[str, bytes]]:
        atts = []
        if not msg.is_multipart():
            return atts
        for part in msg.walk():
            disp = str(part.get("Content-Disposition", ""))
            if "attachment" in disp or (
                part.get_content_maintype() not in ("text", "multipart")
                and "inline" not in disp
            ):
                fname = part.get_filename() or f"attachment{len(atts)+1}.bin"
                data = part.get_payload(decode=True)
                if data:
                    atts.append((fname, data))
        return atts
