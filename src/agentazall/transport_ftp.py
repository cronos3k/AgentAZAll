"""AgentAZAll FTP transport — file-based message delivery over FTP."""

import ftplib
import logging
import re
import ssl
from pathlib import Path
from typing import List, Optional

from .config import INBOX, NOTES, REMEMBER, WHAT_AM_I_DOING, WHO_AM_I
from .helpers import now_str

log = logging.getLogger("agentazall")


class FTPTransport:
    """FTP-based transport with optional FTPS (TLS) support."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.fc = cfg["ftp"]

    def connect(self) -> Optional[ftplib.FTP]:
        try:
            if self.fc.get("ftp_ssl"):
                ctx = ssl.create_default_context()
                ftp = ftplib.FTP_TLS(context=ctx)
                ftp.connect(self.fc["host"], self.fc["port"], timeout=30)
                ftp.login(self.fc["user"], self.fc["password"])
                ftp.prot_p()  # encrypt data channel
                log.debug("FTP-TLS connected to %s:%s", self.fc["host"], self.fc["port"])
            else:
                ftp = ftplib.FTP()
                ftp.connect(self.fc["host"], self.fc["port"], timeout=30)
                ftp.login(self.fc["user"], self.fc["password"])
            return ftp
        except Exception as e:
            log.error("FTP connect: %s", e)
            return None

    @staticmethod
    def _ensure_dir(ftp, path):
        parts = path.strip("/").split("/")
        cur = ""
        for p in parts:
            cur += f"/{p}"
            try:
                ftp.cwd(cur)
            except ftplib.error_perm:
                try:
                    ftp.mkd(cur)
                except ftplib.error_perm:
                    pass

    @staticmethod
    def _upload(ftp, local, remote):
        rdir = "/".join(remote.rsplit("/", 1)[:-1])
        if rdir:
            FTPTransport._ensure_dir(ftp, rdir)
        with open(local, "rb") as f:
            ftp.storbinary(f"STOR {remote}", f)

    @staticmethod
    def _download(ftp, remote, local):
        Path(local).parent.mkdir(parents=True, exist_ok=True)
        with open(local, "wb") as f:
            ftp.retrbinary(f"RETR {remote}", f.write)

    @staticmethod
    def _ls(ftp, path) -> List[str]:
        orig = ftp.pwd()
        try:
            ftp.cwd(path)
            result = [e for e in ftp.nlst() if e not in (".", "..")]
            ftp.cwd(orig)
            return result
        except ftplib.error_perm:
            try:
                ftp.cwd(orig)
            except Exception:
                pass
            return []

    @staticmethod
    def _is_dir(ftp, path) -> bool:
        orig = ftp.pwd()
        try:
            ftp.cwd(path)
            ftp.cwd(orig)
            return True
        except ftplib.error_perm:
            return False

    def fetch_inbox(self, cfg, seen: set) -> int:
        """Download new messages from FTP inbox."""
        ftp = self.connect()
        if not ftp:
            return 0
        agent = cfg["agent_name"]
        mb = Path(cfg["mailbox_dir"])
        count = 0

        try:
            rdates = self._ls(ftp, f"/{agent}")
            for ds in rdates:
                if not re.match(r"\d{4}-\d{2}-\d{2}$", ds):
                    continue
                rinbox = f"/{agent}/{ds}/{INBOX}"
                entries = self._ls(ftp, rinbox)
                local_inbox = mb / agent / ds / INBOX
                local_inbox.mkdir(parents=True, exist_ok=True)

                for entry in entries:
                    ftp_id = f"ftp:{ds}/{entry}"
                    if ftp_id in seen:
                        continue
                    rpath = f"{rinbox}/{entry}"
                    lpath = local_inbox / entry
                    if self._is_dir(ftp, rpath):
                        lpath.mkdir(exist_ok=True)
                        for af in self._ls(ftp, rpath):
                            laf = lpath / af
                            if not laf.exists():
                                try:
                                    self._download(ftp, f"{rpath}/{af}", str(laf))
                                except Exception:
                                    pass
                    else:
                        if not lpath.exists():
                            try:
                                self._download(ftp, rpath, str(lpath))
                                log.info("FTP recv %s (%s)", entry, ds)
                                count += 1
                            except Exception:
                                pass
                    seen.add(ftp_id)
        finally:
            ftp.quit()
        return count

    def sync_special(self, cfg):
        """Upload identity/tasks/notes/memories to FTP (only changed files)."""
        ftp = self.connect()
        if not ftp:
            return
        agent = cfg["agent_name"]
        mb = Path(cfg["mailbox_dir"]) / agent
        try:
            for dd in sorted(mb.iterdir()) if mb.exists() else []:
                if not dd.is_dir() or not re.match(r"\d{4}-\d{2}-\d{2}$", dd.name):
                    continue
                for sub, fn in [(WHO_AM_I, "identity.txt"), (WHAT_AM_I_DOING, "tasks.txt")]:
                    lf = dd / sub / fn
                    marker = lf.with_suffix(".ftp_synced")
                    if lf.exists() and (not marker.exists() or
                                        lf.stat().st_mtime > marker.stat().st_mtime):
                        try:
                            self._upload(ftp, str(lf), f"/{agent}/{dd.name}/{sub}/{fn}")
                            marker.write_text(now_str(), encoding="utf-8")
                        except Exception:
                            pass
                for folder in (NOTES, REMEMBER):
                    fd = dd / folder
                    if fd.exists():
                        for nf in fd.glob("*.txt"):
                            marker = nf.with_suffix(".ftp_synced")
                            if not marker.exists() or nf.stat().st_mtime > marker.stat().st_mtime:
                                try:
                                    self._upload(ftp, str(nf),
                                                 f"/{agent}/{dd.name}/{folder}/{nf.name}")
                                    marker.write_text(now_str(), encoding="utf-8")
                                except Exception:
                                    pass
        finally:
            ftp.quit()

    def restore_special(self, cfg):
        """Download identity/tasks/notes/memories from FTP if missing locally."""
        ftp = self.connect()
        if not ftp:
            return
        agent = cfg["agent_name"]
        mb = Path(cfg["mailbox_dir"])
        try:
            rdates = self._ls(ftp, f"/{agent}")
            for ds in sorted(rdates, reverse=True):
                if not re.match(r"\d{4}-\d{2}-\d{2}$", ds):
                    continue
                for sub, fn in [(WHO_AM_I, "identity.txt"), (WHAT_AM_I_DOING, "tasks.txt")]:
                    rp = f"/{agent}/{ds}/{sub}/{fn}"
                    lp = mb / agent / ds / sub / fn
                    if not lp.exists():
                        try:
                            self._download(ftp, rp, str(lp))
                            log.info("FTP restored %s/%s/%s", ds, sub, fn)
                        except Exception:
                            pass
                for folder in (NOTES, REMEMBER):
                    rfolder = f"/{agent}/{ds}/{folder}"
                    for nf in self._ls(ftp, rfolder):
                        lnf = mb / agent / ds / folder / nf
                        if not lnf.exists():
                            try:
                                self._download(ftp, f"{rfolder}/{nf}", str(lnf))
                            except Exception:
                                pass
        finally:
            ftp.quit()
