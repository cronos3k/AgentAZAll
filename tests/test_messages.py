"""Tests for agentazall.messages module."""

from agentazall.identity import generate_keypair, public_key_b64, fingerprint_from_b64
from agentazall.messages import (
    format_message, parse_headers_only, parse_message, verify_message,
    wrap_signed_body, unwrap_signed_body, SIG_BEGIN, SIG_END,
    SIG_BLOCK_BEGIN, SIG_BLOCK_END,
)


class TestFormatMessage:
    def test_basic_format(self):
        content, msg_id = format_message(
            "alice@localhost", "bob@localhost",
            "Test Subject", "Hello Bob!"
        )
        assert "From: alice@localhost" in content
        assert "To: bob@localhost" in content
        assert "Subject: Test Subject" in content
        assert "Status: new" in content
        assert "---" in content
        assert "Hello Bob!" in content
        assert len(msg_id) == 12

    def test_custom_id(self):
        content, msg_id = format_message(
            "a@l", "b@l", "S", "Body", msg_id="custom123456"
        )
        assert msg_id == "custom123456"
        assert "Message-ID: custom123456" in content

    def test_with_attachments(self):
        content, _ = format_message(
            "a@l", "b@l", "S", "Body",
            attachments=["/path/to/file.pdf", "/path/to/image.png"]
        )
        assert "Attachments: file.pdf, image.png" in content


class TestParseMessage:
    def test_round_trip(self, tmp_path):
        content, msg_id = format_message(
            "alice@localhost", "bob@localhost",
            "Round Trip", "Body content here."
        )
        fpath = tmp_path / f"{msg_id}.txt"
        fpath.write_text(content, encoding="utf-8")

        headers, body = parse_message(fpath)
        assert headers["From"] == "alice@localhost"
        assert headers["To"] == "bob@localhost"
        assert headers["Subject"] == "Round Trip"
        assert headers["Status"] == "new"
        assert "Body content here." in body

    def test_missing_file(self):
        headers, body = parse_message("/nonexistent/file.txt")
        assert headers is None
        assert body is None

    def test_multiline_body(self, tmp_path):
        content = "From: a@l\nTo: b@l\nSubject: S\n\n---\nLine 1\nLine 2\nLine 3"
        fpath = tmp_path / "test.txt"
        fpath.write_text(content, encoding="utf-8")
        headers, body = parse_message(fpath)
        assert "Line 1" in body
        assert "Line 3" in body


class TestParseHeadersOnly:
    def test_basic(self, tmp_path):
        content = "From: a@l\nTo: b@l\nSubject: Hello\nStatus: new\n\n---\nBody"
        fpath = tmp_path / "test.txt"
        fpath.write_text(content, encoding="utf-8")
        headers = parse_headers_only(fpath)
        assert headers["From"] == "a@l"
        assert headers["Subject"] == "Hello"

    def test_stops_at_separator(self, tmp_path):
        content = "From: a@l\n\n---\nBody: not a header"
        fpath = tmp_path / "test.txt"
        fpath.write_text(content, encoding="utf-8")
        headers = parse_headers_only(fpath)
        assert "Body" not in headers


class TestInlineSignature:
    """Tests for PGP-style inline body signatures (v1.0.18+)."""

    def test_wrap_unwrap_roundtrip(self):
        sk, vk = generate_keypair()
        pk_b64 = public_key_b64(vk)
        fp = fingerprint_from_b64(pk_b64)
        body = "Hello, this is a test message."
        wrapped = wrap_signed_body(body, sk, pk_b64, fp)
        assert SIG_BEGIN in wrapped
        assert SIG_END in wrapped
        assert SIG_BLOCK_BEGIN in wrapped
        assert SIG_BLOCK_END in wrapped
        original, pk, fp_out, sig = unwrap_signed_body(wrapped)
        assert original == body
        assert pk == pk_b64
        assert fp_out == fp
        assert sig is not None

    def test_unwrap_unsigned_returns_original(self):
        body = "Just a plain message"
        original, pk, fp, sig = unwrap_signed_body(body)
        assert original == body
        assert pk is None
        assert fp is None
        assert sig is None

    def test_format_with_inline_signing(self):
        sk, vk = generate_keypair()
        pk_b64 = public_key_b64(vk)
        content, msg_id = format_message(
            "alice@relay", "bob@relay", "Signed",
            "Hello signed world!",
            signing_key=sk, public_key_b64=pk_b64,
        )
        # Inline markers should be in body, NOT in headers
        assert SIG_BEGIN in content
        assert SIG_BLOCK_BEGIN in content
        # No header-based crypto (v1.0.17 legacy)
        lines_before_sep = content.split("\n---\n")[0]
        assert "Public-Key:" not in lines_before_sep
        assert "Signature:" not in lines_before_sep

    def test_signed_roundtrip_verifies(self, tmp_path):
        sk, vk = generate_keypair()
        pk_b64 = public_key_b64(vk)
        content, msg_id = format_message(
            "alice@relay", "bob@relay", "Signed RT",
            "Verify me!",
            signing_key=sk, public_key_b64=pk_b64,
        )
        fpath = tmp_path / f"{msg_id}.txt"
        fpath.write_text(content, encoding="utf-8")
        headers, body = parse_message(fpath)
        result = verify_message(headers, body)
        assert result is True

    def test_tampered_body_fails(self, tmp_path):
        sk, vk = generate_keypair()
        pk_b64 = public_key_b64(vk)
        content, msg_id = format_message(
            "alice@relay", "bob@relay", "Tamper Test",
            "Original body",
            signing_key=sk, public_key_b64=pk_b64,
        )
        content = content.replace("Original body", "Tampered body")
        fpath = tmp_path / f"{msg_id}.txt"
        fpath.write_text(content, encoding="utf-8")
        headers, body = parse_message(fpath)
        result = verify_message(headers, body)
        assert result is False

    def test_unsigned_returns_none(self, tmp_path):
        content, msg_id = format_message(
            "alice@relay", "bob@relay", "Unsigned", "No sig here"
        )
        fpath = tmp_path / f"{msg_id}.txt"
        fpath.write_text(content, encoding="utf-8")
        headers, body = parse_message(fpath)
        result = verify_message(headers, body)
        assert result is None

    def test_format_without_signing_unchanged(self):
        content, _ = format_message(
            "a@l", "b@l", "Nosign", "Body"
        )
        assert SIG_BEGIN not in content

    def test_multiline_body_signing(self, tmp_path):
        sk, vk = generate_keypair()
        pk_b64 = public_key_b64(vk)
        body = "Line 1\nLine 2\nLine 3\n\nParagraph 2"
        content, msg_id = format_message(
            "a@relay", "b@relay", "Multi",
            body, signing_key=sk, public_key_b64=pk_b64,
        )
        fpath = tmp_path / f"{msg_id}.txt"
        fpath.write_text(content, encoding="utf-8")
        headers, parsed_body = parse_message(fpath)
        assert verify_message(headers, parsed_body) is True
        # Unwrap recovers original body
        original, _, _, _ = unwrap_signed_body(parsed_body)
        assert original == body

    def test_signature_survives_header_stripping(self):
        """Simulate relay stripping headers — inline sig still verifiable."""
        sk, vk = generate_keypair()
        pk_b64 = public_key_b64(vk)
        content, msg_id = format_message(
            "alice@relay", "bob@relay", "Relay Test",
            "Important message",
            signing_key=sk, public_key_b64=pk_b64,
        )
        # Simulate relay: only the body survives
        body_only = content.split("\n---\n", 1)[1]
        result = verify_message({}, body_only)
        assert result is True

    def test_legacy_header_sig_still_works(self, tmp_path):
        """v1.0.17 header-based signatures should still verify."""
        from agentazall.identity import sign_message
        sk, vk = generate_keypair()
        pk_b64 = public_key_b64(vk)
        # Manually construct a v1.0.17-style message with header sigs
        header_lines = [
            "From: alice@relay",
            "To: bob@relay",
            "Subject: Legacy",
            "Date: 2026-03-11",
            "Message-ID: legacy123",
            "Status: new",
            f"Public-Key: {pk_b64}",
        ]
        body = "Legacy signed body"
        signable = "\n".join(header_lines) + "\n---\n" + body
        sig = sign_message(sk, signable)
        header_lines.append(f"Signature: {sig}")
        content = "\n".join(header_lines) + "\n\n---\n" + body
        fpath = tmp_path / "legacy.txt"
        fpath.write_text(content, encoding="utf-8")
        headers, parsed_body = parse_message(fpath)
        result = verify_message(headers, parsed_body)
        assert result is True
