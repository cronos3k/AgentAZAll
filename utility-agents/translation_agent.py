#!/usr/bin/env python3
"""
NLLB Translation Service Agent for AgentAZAll.

A non-LLM utility agent that translates text using Meta's
No Language Left Behind (NLLB-200) model via CTranslate2.

Message protocol:
    Subject: TRANSLATE <target_lang>
    Body:    <text to translate>

    Subject: TRANSLATE de
    Body:    Hello, how are you?

    Subject: TRANSLATE eng_Latn→deu_Latn
    Body:    The protocol works.

Replies with the translated text in the message body.

Supported language shortcuts:
    en, de, fr, es, ru, ja, zh, pt, it, nl, pl, tr, ar, ko, hi,
    vi, th, id, cs, sv, da, fi, no, ro, hu, uk, el, bg, hr, sk

Or use full NLLB codes: eng_Latn, deu_Latn, fra_Latn, etc.
"""
import sys
import os
import re
import argparse
from pathlib import Path

from base_service import ServiceAgent

# ── Language mapping ────────────────────────────────────────────

LANG_SHORTCUTS = {
    "en": "eng_Latn", "english": "eng_Latn",
    "de": "deu_Latn", "german": "deu_Latn", "deutsch": "deu_Latn",
    "fr": "fra_Latn", "french": "fra_Latn",
    "es": "spa_Latn", "spanish": "spa_Latn",
    "pt": "por_Latn", "portuguese": "por_Latn",
    "it": "ita_Latn", "italian": "ita_Latn",
    "nl": "nld_Latn", "dutch": "nld_Latn",
    "pl": "pol_Latn", "polish": "pol_Latn",
    "ru": "rus_Cyrl", "russian": "rus_Cyrl",
    "uk": "ukr_Cyrl", "ukrainian": "ukr_Cyrl",
    "ja": "jpn_Jpan", "japanese": "jpn_Jpan",
    "zh": "zho_Hans", "chinese": "zho_Hans",
    "ko": "kor_Hang", "korean": "kor_Hang",
    "ar": "arb_Arab", "arabic": "arb_Arab",
    "hi": "hin_Deva", "hindi": "hin_Deva",
    "tr": "tur_Latn", "turkish": "tur_Latn",
    "vi": "vie_Latn", "vietnamese": "vie_Latn",
    "th": "tha_Thai", "thai": "tha_Thai",
    "id": "ind_Latn", "indonesian": "ind_Latn",
    "cs": "ces_Latn", "czech": "ces_Latn",
    "sv": "swe_Latn", "swedish": "swe_Latn",
    "da": "dan_Latn", "danish": "dan_Latn",
    "fi": "fin_Latn", "finnish": "fin_Latn",
    "no": "nob_Latn", "norwegian": "nob_Latn",
    "ro": "ron_Latn", "romanian": "ron_Latn",
    "hu": "hun_Latn", "hungarian": "hun_Latn",
    "el": "ell_Grek", "greek": "ell_Grek",
    "bg": "bul_Cyrl", "bulgarian": "bul_Cyrl",
    "hr": "hrv_Latn", "croatian": "hrv_Latn",
    "sk": "slk_Latn", "slovak": "slk_Latn",
}

# All valid NLLB codes (subset — NLLB supports 200+ languages)
VALID_NLLB_CODES = set(LANG_SHORTCUTS.values())


def resolve_lang(raw):
    """Resolve a language string to an NLLB code."""
    raw = raw.strip().lower()
    # Direct NLLB code?
    if "_" in raw and len(raw) >= 7:
        return raw
    # Shortcut?
    return LANG_SHORTCUTS.get(raw)


def parse_translate_subject(subject):
    """Parse the subject line for target language.

    Formats:
        TRANSLATE de
        TRANSLATE english
        TRANSLATE eng_Latn→deu_Latn
        translate to german
        translate to de

    Returns: (source_lang or None, target_lang) or (None, None) on failure.
    """
    text = subject.strip()

    # Remove "Re: " prefixes
    while text.lower().startswith("re: "):
        text = text[4:].strip()

    # Normalize
    text = re.sub(r'^translate\s*:?\s*', '', text, flags=re.IGNORECASE).strip()

    # Arrow format: src→tgt or src->tgt
    arrow_match = re.match(r'(\S+)\s*[→\->]+\s*(\S+)', text)
    if arrow_match:
        src = resolve_lang(arrow_match.group(1))
        tgt = resolve_lang(arrow_match.group(2))
        return src, tgt

    # "to <lang>" format
    to_match = re.match(r'to\s+(.+)', text, re.IGNORECASE)
    if to_match:
        tgt = resolve_lang(to_match.group(1))
        return None, tgt

    # Single language code
    if text:
        tgt = resolve_lang(text)
        return None, tgt

    return None, None


# ── CTranslate2 NLLB Backend ───────────────────────────────────

class NLLBTranslator:
    """NLLB-200 translation via CTranslate2 (int8 quantized)."""

    def __init__(self, model_dir, device="cuda", device_index=0):
        import ctranslate2
        import sentencepiece as spm

        self.model_dir = Path(model_dir)
        self.log_prefix = f"NLLB[{device}:{device_index}]"

        # Load CTranslate2 model
        self.translator = ctranslate2.Translator(
            str(self.model_dir),
            device=device,
            device_index=device_index,
            compute_type="int8",
        )

        # Load tokenizer
        sp_path = self.model_dir / "sentencepiece.model"
        if not sp_path.exists():
            # Try alternative name
            sp_path = self.model_dir / "tokenizer.model"
        if not sp_path.exists():
            raise FileNotFoundError(
                f"No sentencepiece model found in {self.model_dir}"
            )
        self.tokenizer = spm.SentencePieceProcessor()
        self.tokenizer.Load(str(sp_path))

    def translate(self, text, source_lang=None, target_lang="deu_Latn"):
        """Translate text. Returns translated string.

        If source_lang is None, defaults to eng_Latn.
        """
        if not source_lang:
            source_lang = "eng_Latn"

        # Tokenize with source language prefix
        tokens = self.tokenizer.Encode(text, out_type=str)

        # NLLB expects the source language as the first token
        # and target language as the target prefix
        results = self.translator.translate(
            [tokens],
            target_prefix=[[target_lang]],
            beam_size=4,
            max_input_length=512,
            max_decoding_length=512,
        )

        # Decode — skip the language token
        translated_tokens = results[0].hypotheses[0]
        if translated_tokens and translated_tokens[0] == target_lang:
            translated_tokens = translated_tokens[1:]

        translated = self.tokenizer.Decode(translated_tokens)

        # De-duplicate CT2 beam search artifact
        # (sometimes "Spiel starten Spiel starten" → "Spiel starten")
        half = len(translated) // 2
        if half > 10 and translated[:half].strip() == translated[half:].strip():
            translated = translated[:half].strip()

        return translated


# ── HTTP API Backend (fallback) ─────────────────────────────────

class HTTPTranslator:
    """Call an HTTP translation API (e.g., uni-back-serv on SRV99)."""

    def __init__(self, url="https://192.168.10.178:8000/api/translate"):
        import urllib.request
        import ssl
        self.url = url
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE

    def translate(self, text, source_lang=None, target_lang="deu_Latn"):
        import urllib.request
        import json

        payload = json.dumps({
            "text": text,
            "source_lang": source_lang or "eng_Latn",
            "target_lang": target_lang,
        }).encode("utf-8")

        req = urllib.request.Request(
            self.url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, context=self.ctx, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return result.get("translated", result.get("text", ""))


# ── Translation Agent ───────────────────────────────────────────

class TranslationAgent(ServiceAgent):
    """NLLB translation service on the AgentAZAll network."""

    def __init__(self, work_dir, model_dir=None, device="cuda",
                 device_index=0, http_url=None, **kwargs):
        super().__init__("translation", work_dir, **kwargs)

        # Initialize backend
        self.backend = None
        if http_url:
            self.log.info(f"Using HTTP backend: {http_url}")
            self.backend = HTTPTranslator(url=http_url)
        elif model_dir:
            self.log.info(f"Loading NLLB model from {model_dir}")
            self.backend = NLLBTranslator(
                model_dir, device=device, device_index=device_index
            )
            self.log.info("NLLB model loaded successfully")
        else:
            self.log.error(
                "No backend configured! Pass --model-dir or --http-url"
            )

    def handle_request(self, msg):
        """Translate the message body to the requested language."""
        subject = msg["subject"]
        body = msg["body"].strip()

        if not self.backend:
            return {"error": "Translation backend not configured."}

        if not body:
            return {"error": "Empty message body. Send the text to translate."}

        # Parse language from subject
        source_lang, target_lang = parse_translate_subject(subject)

        if not target_lang:
            # Try to find language hint in first line of body
            lines = body.split("\n", 1)
            if len(lines) > 1 and lines[0].lower().startswith("to:"):
                _, tgt = parse_translate_subject(f"TRANSLATE {lines[0][3:]}")
                if tgt:
                    target_lang = tgt
                    body = lines[1].strip()

        if not target_lang:
            lang_list = ", ".join(sorted(set(
                k for k in LANG_SHORTCUTS.keys() if len(k) == 2
            )))
            return {
                "body": (
                    "Could not determine target language.\n\n"
                    "Usage: Set the subject to one of:\n"
                    "  TRANSLATE de\n"
                    "  TRANSLATE english\n"
                    "  TRANSLATE eng_Latn→deu_Latn\n"
                    "  translate to german\n\n"
                    f"Supported shortcuts: {lang_list}\n\n"
                    "Or use any NLLB-200 language code (e.g., deu_Latn)."
                )
            }

        # Translate
        self.log.info(
            f"Translating {len(body)} chars: "
            f"{source_lang or 'auto'}→{target_lang}"
        )
        try:
            translated = self.backend.translate(
                body, source_lang=source_lang, target_lang=target_lang
            )
        except Exception as e:
            self.log.exception(f"Translation failed: {e}")
            return {"error": f"Translation failed: {e}"}

        src_label = source_lang or "eng_Latn"
        return {
            "body": (
                f"Translation ({src_label} → {target_lang}):\n\n"
                f"{translated}"
            )
        }


# ── CLI ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="AgentAZAll NLLB Translation Service Agent"
    )
    parser.add_argument(
        "--work-dir", type=str, default="./agent_translation",
        help="Working directory (contains config.json)",
    )
    parser.add_argument(
        "--model-dir", type=str, default=None,
        help="Path to CTranslate2 NLLB model directory",
    )
    parser.add_argument(
        "--http-url", type=str, default=None,
        help="HTTP API endpoint for translation (fallback backend)",
    )
    parser.add_argument(
        "--device", type=str, default="cuda",
        help="Device: cuda or cpu",
    )
    parser.add_argument(
        "--device-index", type=int, default=0,
        help="CUDA device index",
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

    agent = TranslationAgent(
        work_dir=args.work_dir,
        model_dir=args.model_dir,
        http_url=args.http_url,
        device=args.device,
        device_index=args.device_index,
        poll_interval=args.poll,
    )

    if args.once:
        agent.run_once()
    else:
        agent.run()


if __name__ == "__main__":
    main()
