"""Tests for agentazall.messages module."""

from agentazall.identity import generate_keypair, public_key_b64
from agentazall.messages import (
    format_message, parse_headers_only, parse_message, verify_message,
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


class TestSignedMessages:

    def test_format_with_signing(self):
        sk, vk = generate_keypair()
        pk_b64 = public_key_b64(vk)
        content, msg_id = format_message(
            "alice@relay", "bob@relay", "Signed",
            "Hello signed world!",
            signing_key=sk, public_key_b64=pk_b64,
        )
        assert f"Public-Key: {pk_b64}" in content
        assert "Signature: " in content

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
        # Tamper with the body
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
        assert "Public-Key" not in content
        assert "Signature" not in content
