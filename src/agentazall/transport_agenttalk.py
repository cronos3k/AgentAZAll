"""AgentAZAll AgentTalk transport — HTTPS REST API for public relay.

AgentTalk is a proprietary agent messaging protocol (NOT email).
Messages are relayed as opaque encrypted blobs over HTTPS.
The relay server stores messages in RAM only (tmpfs).

Config keys (under cfg["agenttalk"]):
    server  — relay base URL, e.g. "https://relay.agentazall.ai:8443"
    token   — Bearer API token (issued at registration)
"""

import json
import logging
import re
import ssl
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from .config import INBOX, OUTBOX, SENT
from .helpers import (
    agent_day,
    ensure_dirs,
    generate_id,
    now_str,
    today_str,
)
from .index import build_index
from .messages import parse_message

log = logging.getLogger("agentazall")


class AgentTalkTransport:
    """HTTPS-based transport for the AgentAZAll public relay."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.ac = cfg.get("agenttalk", {})
        self.server = self.ac.get("server", "").rstrip("/")
        self.token = self.ac.get("token", "")

    # -- low-level API --

    def _request(self, method: str, path: str, payload: dict = None,
                 timeout: int = 30) -> Tuple[Optional[dict], Optional[str]]:
        """Make an authenticated HTTPS request to the relay API.

        Returns (response_dict, None) on success or (None, error_string) on failure.
        """
        url = f"{self.server}{path}"
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        # Allow self-signed certs in dev; in production the relay has Let's Encrypt
        ctx = ssl.create_default_context()
        try:
            ctx.load_default_certs()
        except Exception:
            pass

        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body), None
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            try:
                err = json.loads(body)
                return None, err.get("error", f"HTTP {e.code}")
            except json.JSONDecodeError:
                return None, f"HTTP {e.code}: {body[:200]}"
        except urllib.error.URLError as e:
            return None, f"Cannot reach relay — {e.reason}"
        except Exception as e:
            return None, str(e)

    def _post(self, path: str, payload: dict, timeout: int = 30):
        return self._request("POST", path, payload, timeout)

    def _get(self, path: str, timeout: int = 30):
        return self._request("GET", path, timeout=timeout)

    # -- high-level: send --

    def send_message(self, to: str, payload: str) -> Tuple[bool, str]:
        """Send a message payload to another agent.

        Args:
            to: recipient address (e.g. "agent2.agenttalk" or "agent2")
            payload: message content (should be encrypted by caller)

        Returns:
            (success_bool, message_id_or_error)
        """
        result, err = self._post("/send", {
            "to": to,
            "payload": payload,
        })
        if err:
            log.error("AgentTalk send to %s: %s", to, err)
            return False, err
        msg_id = result.get("message_id", "unknown")
        log.info("AgentTalk sent to %s: %s", to, msg_id)
        return True, msg_id

    # -- high-level: receive --

    def fetch_messages(self) -> Tuple[List[dict], Optional[str]]:
        """Fetch and auto-delete pending messages from the relay.

        Returns:
            (list_of_messages, error_or_none)
            Each message: {"id", "from", "to", "timestamp", "payload"}
        """
        result, err = self._get("/messages")
        if err:
            log.error("AgentTalk fetch: %s", err)
            return [], err
        messages = result.get("messages", [])
        if messages:
            log.info("AgentTalk fetched %d messages", len(messages))
        return messages, None

    # -- high-level: status --

    def server_status(self) -> Tuple[Optional[dict], Optional[str]]:
        """Get relay server status (no auth required)."""
        return self._get("/status")

    def health_check(self) -> bool:
        """Quick health check of the relay."""
        result, err = self._get("/health")
        return err is None and result and result.get("status") == "ok"

    # -- daemon-compatible interface --

    def receive(self, seen: set) -> List[Tuple[str, dict, str, list]]:
        """Fetch messages from relay and return in unified format.

        Returns same format as EmailTransport.receive():
            list of (uid, headers_dict, body_text, attachments_list)

        AgentTalk messages don't have traditional email headers, so we
        synthesize them from the message metadata.
        """
        messages, err = self.fetch_messages()
        if err:
            return []

        results = []
        for msg in messages:
            msg_id = msg.get("id", "")
            if msg_id in seen:
                continue

            # Parse the payload — it could be:
            # 1. Plain text (body only)
            # 2. JSON envelope with headers + body (for compatibility)
            payload = msg.get("payload", "")
            from_addr = msg.get("from", "")
            to_addr = msg.get("to", "")
            timestamp = msg.get("timestamp", now_str())

            # Try to parse payload as structured message
            subject = ""
            body = ""
            attachments = []
            try:
                pdata = json.loads(payload) if isinstance(payload, str) else payload
                if isinstance(pdata, dict):
                    subject = pdata.get("subject", "")
                    body = pdata.get("body", "")
                    # Attachments come as list of {name, data_b64}
                    for att in pdata.get("attachments", []):
                        import base64
                        name = att.get("name", "attachment.bin")
                        data = base64.b64decode(att.get("data", ""))
                        attachments.append((name, data))
                else:
                    body = str(pdata)
            except (json.JSONDecodeError, TypeError):
                # Plain text payload
                body = payload
                subject = "(AgentTalk message)"

            if not subject:
                subject = "(AgentTalk message)"

            headers = {
                "From": from_addr,
                "To": to_addr,
                "Subject": subject,
                "Date": timestamp,
                "Message-ID": msg_id,
            }

            seen.add(msg_id)
            results.append((msg_id, headers, body, attachments))

        return results

    def send(self, to_list, cc_list, subject, body, from_addr,
             att_paths=None) -> bool:
        """Send a message via AgentTalk relay (daemon-compatible interface).

        Packages the message into a JSON payload and sends it to each recipient.
        """
        import base64

        # Build payload envelope
        payload_data = {
            "subject": subject,
            "body": body,
            "from": from_addr,
        }

        # Add attachments if any — no client-side size limit.
        # The server decides what it accepts (local = unlimited,
        # public relay = 256 KB).  If the server rejects, we log.
        if att_paths:
            payload_data["attachments"] = []
            for ap in att_paths:
                p = Path(ap)
                if p.exists():
                    payload_data["attachments"].append({
                        "name": p.name,
                        "data": base64.b64encode(p.read_bytes()).decode("ascii"),
                    })

        payload_json = json.dumps(payload_data)

        all_ok = True
        for rcpt in to_list + cc_list:
            ok, result = self.send_message(rcpt, payload_json)
            if not ok:
                log.error("AgentTalk send to %s failed: %s", rcpt, result)
                all_ok = False

        return all_ok
