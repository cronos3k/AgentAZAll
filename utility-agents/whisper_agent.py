#!/usr/bin/env python3
"""
Whisper STT Service Agent for AgentAZAll.

A non-LLM utility agent that transcribes audio files using
OpenAI's Whisper model (running locally via openai-whisper).

Message protocol:
    Subject: TRANSCRIBE [optional language hint]
    Body:    (optional context or instructions)
    Attachments: audio.wav, recording.mp3, etc.

    Subject: TRANSCRIBE
    Attachment: meeting.wav

    Subject: TRANSCRIBE german
    Attachment: interview.mp3

Replies with the transcribed text in the message body.

Supported audio formats: wav, mp3, m4a, flac, ogg, webm
"""
import sys
import os
import re
import argparse
import tempfile
from pathlib import Path

from base_service import ServiceAgent

# Audio file extensions Whisper can handle
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm", ".opus"}


# ── Whisper Backend ─────────────────────────────────────────────

class WhisperTranscriber:
    """Local Whisper transcription using openai-whisper."""

    def __init__(self, model_name="large-v3-turbo", device="cuda"):
        import whisper
        self.model = whisper.load_model(model_name, device=device)
        self.device = device

    def transcribe(self, audio_path, language=None):
        """Transcribe an audio file.

        Args:
            audio_path: path to audio file
            language: optional language hint (e.g., "en", "de")

        Returns:
            dict with keys: text, language, segments
        """
        options = {}
        if language:
            options["language"] = language

        result = self.model.transcribe(str(audio_path), **options)
        return {
            "text": result.get("text", "").strip(),
            "language": result.get("language", "unknown"),
            "segments": [
                {
                    "start": s["start"],
                    "end": s["end"],
                    "text": s["text"].strip(),
                }
                for s in result.get("segments", [])
            ],
        }


# ── HTTP Backend (call uni-back-serv or similar) ────────────────

class HTTPTranscriber:
    """Call an HTTP STT API."""

    def __init__(self, url="https://192.168.10.178:8000/api/transcribe"):
        import ssl
        self.url = url
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE

    def transcribe(self, audio_path, language=None):
        import urllib.request
        import json

        audio_data = Path(audio_path).read_bytes()
        boundary = "----AgentAZAllBoundary"

        # Build multipart form
        parts = []
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="file"; '
            f'filename="{Path(audio_path).name}"\r\n'.encode()
        )
        parts.append(b"Content-Type: application/octet-stream\r\n\r\n")
        parts.append(audio_data)
        parts.append(b"\r\n")

        if language:
            parts.append(f"--{boundary}\r\n".encode())
            parts.append(
                b'Content-Disposition: form-data; name="language"\r\n\r\n'
            )
            parts.append(language.encode())
            parts.append(b"\r\n")

        parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(parts)

        req = urllib.request.Request(
            self.url, data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, context=self.ctx, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        return {
            "text": result.get("text", ""),
            "language": result.get("language", "unknown"),
            "segments": result.get("segments", []),
        }


# ── Whisper STT Agent ───────────────────────────────────────────

class WhisperAgent(ServiceAgent):
    """Whisper speech-to-text service on the AgentAZAll network."""

    def __init__(self, work_dir, model_name="large-v3-turbo",
                 device="cuda", http_url=None, **kwargs):
        super().__init__("whisper-stt", work_dir, **kwargs)

        self.backend = None
        if http_url:
            self.log.info(f"Using HTTP backend: {http_url}")
            self.backend = HTTPTranscriber(url=http_url)
        else:
            self.log.info(f"Loading Whisper model: {model_name} on {device}")
            self.backend = WhisperTranscriber(
                model_name=model_name, device=device
            )
            self.log.info("Whisper model loaded successfully")

    def _find_audio_attachments(self, msg):
        """Find audio files in message attachments."""
        audio_files = []
        for att in msg.get("attachments", []):
            ext = Path(att["name"]).suffix.lower()
            if ext in AUDIO_EXTENSIONS:
                audio_files.append(att)
        return audio_files

    def _parse_language_hint(self, subject):
        """Extract optional language hint from subject."""
        text = subject.strip()
        while text.lower().startswith("re: "):
            text = text[4:].strip()

        text = re.sub(
            r'^transcribe\s*:?\s*', '', text, flags=re.IGNORECASE
        ).strip()

        if not text:
            return None

        # Common language codes for Whisper
        lang_map = {
            "english": "en", "german": "de", "french": "fr",
            "spanish": "es", "italian": "it", "portuguese": "pt",
            "russian": "ru", "japanese": "ja", "chinese": "zh",
            "korean": "ko", "arabic": "ar", "hindi": "hi",
            "dutch": "nl", "polish": "pl", "turkish": "tr",
        }
        text_lower = text.lower()
        if text_lower in lang_map:
            return lang_map[text_lower]
        if len(text_lower) == 2:
            return text_lower
        return None

    def handle_request(self, msg):
        """Transcribe audio attachment(s)."""
        if not self.backend:
            return {"error": "Whisper backend not configured."}

        audio_files = self._find_audio_attachments(msg)

        if not audio_files:
            return {
                "body": (
                    "No audio files found in your message.\n\n"
                    "Usage:\n"
                    "  Subject: TRANSCRIBE\n"
                    "  Attach an audio file (wav, mp3, m4a, flac, ogg, webm)\n\n"
                    "Optional language hint:\n"
                    "  Subject: TRANSCRIBE german\n"
                    "  Subject: TRANSCRIBE de"
                )
            }

        language = self._parse_language_hint(msg["subject"])
        tmp = self._tmp_dir()
        results = []

        for att in audio_files:
            # Write attachment to temp file
            tmp_path = tmp / att["name"]
            tmp_path.write_bytes(att["data"])

            self.log.info(
                f"Transcribing: {att['name']} "
                f"({len(att['data'])} bytes, lang={language or 'auto'})"
            )

            try:
                result = self.backend.transcribe(tmp_path, language=language)
                results.append({
                    "file": att["name"],
                    "text": result["text"],
                    "language": result["language"],
                    "segments": result.get("segments", []),
                })
            except Exception as e:
                self.log.exception(f"Transcription failed for {att['name']}")
                results.append({
                    "file": att["name"],
                    "text": f"[ERROR: {e}]",
                    "language": "unknown",
                })
            finally:
                # Cleanup temp file
                try:
                    tmp_path.unlink()
                except Exception:
                    pass

        # Build reply
        if len(results) == 1:
            r = results[0]
            body = (
                f"Transcription of {r['file']} "
                f"(detected language: {r['language']}):\n\n"
                f"{r['text']}"
            )
            # Add segment timestamps if available
            if r.get("segments") and len(r["segments"]) > 1:
                body += "\n\n--- Timestamped segments ---\n"
                for seg in r["segments"]:
                    start = f"{seg['start']:.1f}s"
                    end = f"{seg['end']:.1f}s"
                    body += f"[{start} → {end}] {seg['text']}\n"
        else:
            body = f"Transcription of {len(results)} audio files:\n\n"
            for r in results:
                body += (
                    f"=== {r['file']} "
                    f"(language: {r['language']}) ===\n"
                    f"{r['text']}\n\n"
                )

        # Also save transcription as text file attachment
        out_attachments = []
        for r in results:
            if r["text"] and not r["text"].startswith("[ERROR"):
                txt_name = Path(r["file"]).stem + "_transcript.txt"
                txt_path = tmp / txt_name
                txt_path.write_text(r["text"], encoding="utf-8")
                out_attachments.append(str(txt_path))

        return {"body": body, "attachments": out_attachments}


# ── CLI ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="AgentAZAll Whisper STT Service Agent"
    )
    parser.add_argument(
        "--work-dir", type=str, default="./agent_whisper",
        help="Working directory (contains config.json)",
    )
    parser.add_argument(
        "--model", type=str, default="large-v3-turbo",
        help="Whisper model name (tiny, base, small, medium, large-v3-turbo)",
    )
    parser.add_argument(
        "--http-url", type=str, default=None,
        help="HTTP API endpoint for transcription (fallback backend)",
    )
    parser.add_argument(
        "--device", type=str, default="cuda",
        help="Device: cuda or cpu",
    )
    parser.add_argument(
        "--poll", type=int, default=10,
        help="Poll interval in seconds",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Process inbox once and exit",
    )
    args = parser.parse_args()

    agent = WhisperAgent(
        work_dir=args.work_dir,
        model_name=args.model,
        http_url=args.http_url,
        device=args.device,
        poll_interval=args.poll,
    )

    if args.once:
        agent.run_once()
    else:
        agent.run()


if __name__ == "__main__":
    main()
