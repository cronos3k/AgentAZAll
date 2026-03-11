#!/usr/bin/env python3
"""
TTS (Text-to-Speech) Service Agent for AgentAZAll.

A non-LLM utility agent that synthesizes speech from text
using Kokoro TTS (ONNX) or any compatible TTS backend.

Message protocol:
    Subject: SPEAK [optional voice name]
    Body:    <text to synthesize>

    Subject: SPEAK
    Body:    Hello, welcome to the AgentAZAll network.

    Subject: SPEAK af_heart
    Body:    This message will be read aloud.

Replies with the synthesized audio as a WAV attachment,
plus a confirmation in the message body.

Supported voices depend on the installed model.
Default voice: "af_heart" (Kokoro default).
"""
import sys
import os
import re
import struct
import argparse
from pathlib import Path

from base_service import ServiceAgent


# ── WAV helpers ─────────────────────────────────────────────────

def write_wav(path, audio_bytes, sample_rate=24000, channels=1,
              sample_width=2):
    """Write raw PCM audio data to a WAV file."""
    data_size = len(audio_bytes)
    with open(path, "wb") as f:
        # RIFF header
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        # fmt chunk
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))                   # chunk size
        f.write(struct.pack("<H", 1))                    # PCM format
        f.write(struct.pack("<H", channels))
        f.write(struct.pack("<I", sample_rate))
        f.write(struct.pack("<I",
                            sample_rate * channels * sample_width))
        f.write(struct.pack("<H", channels * sample_width))
        f.write(struct.pack("<H", sample_width * 8))
        # data chunk
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(audio_bytes)


# ── Kokoro TTS Backend ──────────────────────────────────────────

class KokoroTTS:
    """Kokoro ONNX-based TTS synthesis."""

    def __init__(self, model_path, voices_path, device="cpu"):
        """Load Kokoro ONNX model and voice embeddings.

        Args:
            model_path: path to kokoro-v1.0.onnx
            voices_path: path to voices-v1.0.bin
            device: 'cpu' or 'cuda'
        """
        try:
            import onnxruntime as ort
            import numpy as np
        except ImportError:
            raise ImportError(
                "Kokoro TTS requires: pip install onnxruntime numpy"
            )

        self.np = np
        providers = ["CPUExecutionProvider"]
        if device == "cuda":
            providers.insert(0, "CUDAExecutionProvider")

        self.session = ort.InferenceSession(
            str(model_path), providers=providers
        )

        # Load voice embeddings
        self.voices = np.load(str(voices_path), allow_pickle=True)
        self.sample_rate = 24000
        self.default_voice = "af_heart"

    def get_voices(self):
        """List available voice names."""
        if hasattr(self.voices, "files"):
            return list(self.voices.files)
        return [self.default_voice]

    def synthesize(self, text, voice=None):
        """Synthesize text to raw PCM audio bytes (int16).

        Returns: (audio_bytes, sample_rate)
        """
        voice = voice or self.default_voice

        # Get voice embedding
        if hasattr(self.voices, "files"):
            if voice in self.voices.files:
                voice_emb = self.voices[voice]
            else:
                voice_emb = self.voices[self.default_voice]
        else:
            voice_emb = self.voices

        # Simple phoneme-to-token encoding (placeholder — real Kokoro
        # uses its own tokenizer; adapt to your actual kokoro_wrapper)
        # This would typically call kokoro_wrapper.KokoroTTS
        raise NotImplementedError(
            "Direct Kokoro synthesis requires kokoro_wrapper.py. "
            "Use --kokoro-wrapper to point to your wrapper, "
            "or use --http-url for an HTTP TTS backend."
        )


# ── Wrapper-based Backend ───────────────────────────────────────

class KokoroWrapperTTS:
    """Use kokoro_wrapper.py (the user's existing wrapper)."""

    def __init__(self, wrapper_path=None, device="cpu"):
        if wrapper_path:
            wrapper_dir = str(Path(wrapper_path).parent)
            if wrapper_dir not in sys.path:
                sys.path.insert(0, wrapper_dir)

        import kokoro_wrapper
        self.engine = kokoro_wrapper.KokoroTTS(device=device)
        self.sample_rate = 24000

    def get_voices(self):
        if hasattr(self.engine, "get_voices"):
            return self.engine.get_voices()
        return ["default"]

    def synthesize(self, text, voice=None):
        """Returns (wav_bytes, sample_rate)."""
        voice = voice or "default"
        audio_bytes = self.engine.synthesize(text, voice=voice)
        return audio_bytes, self.sample_rate


# ── HTTP Backend ────────────────────────────────────────────────

class HTTPSynthesizer:
    """Call an HTTP TTS API."""

    def __init__(self, url="http://localhost:9120/v1/audio/synthesize"):
        self.url = url
        self.sample_rate = 24000

    def get_voices(self):
        return ["default"]

    def synthesize(self, text, voice=None):
        import urllib.request
        import json

        payload = json.dumps({
            "text": text,
            "voice": voice or "default",
        }).encode("utf-8")

        req = urllib.request.Request(
            self.url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            audio_bytes = resp.read()

        return audio_bytes, self.sample_rate


# ── TTS Agent ───────────────────────────────────────────────────

class TTSAgent(ServiceAgent):
    """Text-to-speech service on the AgentAZAll network."""

    def __init__(self, work_dir, kokoro_wrapper=None,
                 model_path=None, voices_path=None,
                 device="cpu", http_url=None, **kwargs):
        super().__init__("tts", work_dir, **kwargs)

        self.backend = None
        if http_url:
            self.log.info(f"Using HTTP TTS backend: {http_url}")
            self.backend = HTTPSynthesizer(url=http_url)
        elif kokoro_wrapper:
            self.log.info(f"Using kokoro_wrapper: {kokoro_wrapper}")
            self.backend = KokoroWrapperTTS(
                wrapper_path=kokoro_wrapper, device=device
            )
            self.log.info("Kokoro TTS loaded successfully")
        elif model_path and voices_path:
            self.log.info(f"Loading Kokoro ONNX: {model_path}")
            self.backend = KokoroTTS(
                model_path=model_path,
                voices_path=voices_path,
                device=device,
            )
            self.log.info("Kokoro ONNX loaded successfully")
        else:
            self.log.error(
                "No TTS backend! Pass --kokoro-wrapper, "
                "--model-path + --voices-path, or --http-url"
            )

    def _parse_voice(self, subject):
        """Extract voice name from subject line."""
        text = subject.strip()
        while text.lower().startswith("re: "):
            text = text[4:].strip()
        text = re.sub(
            r'^speak\s*:?\s*', '', text, flags=re.IGNORECASE
        ).strip()
        return text if text else None

    def handle_request(self, msg):
        """Synthesize speech from message body."""
        if not self.backend:
            return {"error": "TTS backend not configured."}

        body = msg["body"].strip()
        if not body:
            voices = self.backend.get_voices()
            return {
                "body": (
                    "Empty message body. Send the text to speak.\n\n"
                    "Usage:\n"
                    "  Subject: SPEAK\n"
                    "  Body: The text you want synthesized.\n\n"
                    "  Subject: SPEAK af_heart\n"
                    "  Body: With a specific voice.\n\n"
                    f"Available voices: {', '.join(voices)}"
                )
            }

        voice = self._parse_voice(msg["subject"])

        # Limit text length
        max_chars = 5000
        if len(body) > max_chars:
            body = body[:max_chars]
            truncated = True
        else:
            truncated = False

        self.log.info(
            f"Synthesizing {len(body)} chars, voice={voice or 'default'}"
        )

        try:
            audio_data, sample_rate = self.backend.synthesize(
                body, voice=voice
            )
        except Exception as e:
            self.log.exception(f"TTS synthesis failed: {e}")
            return {"error": f"Synthesis failed: {e}"}

        # Save WAV to temp
        tmp = self._tmp_dir()
        wav_path = tmp / "speech_output.wav"

        # If the backend returns raw PCM, wrap in WAV
        if not audio_data[:4] == b"RIFF":
            write_wav(wav_path, audio_data, sample_rate=sample_rate)
        else:
            wav_path.write_bytes(audio_data)

        wav_size = wav_path.stat().st_size
        duration_est = wav_size / (sample_rate * 2)  # 16-bit mono

        reply_body = (
            f"Speech synthesized successfully.\n"
            f"  Voice: {voice or 'default'}\n"
            f"  Duration: ~{duration_est:.1f}s\n"
            f"  Size: {wav_size // 1024} KB\n"
            f"  Format: WAV, {sample_rate} Hz, 16-bit mono"
        )
        if truncated:
            reply_body += f"\n  (Input truncated to {max_chars} characters)"

        return {
            "body": reply_body,
            "attachments": [str(wav_path)],
        }


# ── CLI ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="AgentAZAll TTS Service Agent"
    )
    parser.add_argument(
        "--work-dir", type=str, default="./agent_tts",
        help="Working directory (contains config.json)",
    )
    parser.add_argument(
        "--kokoro-wrapper", type=str, default=None,
        help="Path to kokoro_wrapper.py",
    )
    parser.add_argument(
        "--model-path", type=str, default=None,
        help="Path to kokoro-v1.0.onnx",
    )
    parser.add_argument(
        "--voices-path", type=str, default=None,
        help="Path to voices-v1.0.bin",
    )
    parser.add_argument(
        "--http-url", type=str, default=None,
        help="HTTP API endpoint for TTS synthesis",
    )
    parser.add_argument(
        "--device", type=str, default="cpu",
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

    agent = TTSAgent(
        work_dir=args.work_dir,
        kokoro_wrapper=args.kokoro_wrapper,
        model_path=args.model_path,
        voices_path=args.voices_path,
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
