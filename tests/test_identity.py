"""Tests for identity module — Ed25519 keypair, signing, keyring."""

import json
import pytest
from pathlib import Path

from agentazall.identity import (
    generate_keypair, save_keypair, load_keypair, fingerprint,
    public_key_b64, sign_message, verify_signature,
    fingerprint_from_b64, Keyring,
)


# ── Keypair ──────────────────────────────────────────────────────────────────

class TestKeypair:

    def test_generate_returns_pair(self):
        sk, vk = generate_keypair()
        assert sk is not None
        assert vk is not None
        assert len(sk.encode()) == 32
        assert len(vk.encode()) == 32

    def test_save_load_roundtrip(self, tmp_path):
        sk, vk = generate_keypair()
        save_keypair(tmp_path, sk)
        loaded = load_keypair(tmp_path)
        assert loaded is not None
        sk2, vk2 = loaded
        assert sk2.encode() == sk.encode()
        assert vk2.encode() == vk.encode()

    def test_load_missing_returns_none(self, tmp_path):
        assert load_keypair(tmp_path) is None

    def test_save_creates_file(self, tmp_path):
        sk, _ = generate_keypair()
        save_keypair(tmp_path, sk)
        assert (tmp_path / ".identity_key").exists()
        data = json.loads((tmp_path / ".identity_key").read_text())
        assert "private_key_hex" in data
        assert "public_key_hex" in data
        assert "fingerprint" in data

    def test_fingerprint_deterministic(self):
        sk, vk = generate_keypair()
        fp1 = fingerprint(vk)
        fp2 = fingerprint(vk)
        assert fp1 == fp2
        assert len(fp1) == 16

    def test_fingerprint_different_keys(self):
        _, vk1 = generate_keypair()
        _, vk2 = generate_keypair()
        assert fingerprint(vk1) != fingerprint(vk2)

    def test_public_key_b64(self):
        _, vk = generate_keypair()
        b64 = public_key_b64(vk)
        assert len(b64) > 0
        # Base64 of 32 bytes = 44 chars
        assert len(b64) == 44


# ── Signing ──────────────────────────────────────────────────────────────────

class TestSigning:

    def test_sign_verify_roundtrip(self):
        sk, vk = generate_keypair()
        msg = "From: a@b\nTo: c@d\n---\nHello world"
        sig = sign_message(sk, msg)
        pk_b64 = public_key_b64(vk)
        assert verify_signature(pk_b64, sig, msg) is True

    def test_tampered_message_fails(self):
        sk, vk = generate_keypair()
        msg = "From: a@b\nTo: c@d\n---\nHello world"
        sig = sign_message(sk, msg)
        pk_b64 = public_key_b64(vk)
        assert verify_signature(pk_b64, sig, msg + " TAMPERED") is False

    def test_wrong_key_fails(self):
        sk1, _ = generate_keypair()
        _, vk2 = generate_keypair()
        msg = "test message"
        sig = sign_message(sk1, msg)
        pk_b64 = public_key_b64(vk2)
        assert verify_signature(pk_b64, sig, msg) is False

    def test_invalid_b64_returns_false(self):
        assert verify_signature("not-valid-b64!", "not-valid!", "msg") is False

    def test_fingerprint_from_b64(self):
        _, vk = generate_keypair()
        fp = fingerprint(vk)
        b64 = public_key_b64(vk)
        fp2 = fingerprint_from_b64(b64)
        assert fp == fp2


# ── Keyring ──────────────────────────────────────────────────────────────────

class TestKeyring:

    def test_empty_keyring(self, tmp_path):
        kr = Keyring(tmp_path)
        assert kr.count() == 0

    def test_add_and_lookup(self, tmp_path):
        kr = Keyring(tmp_path)
        kr.add("abc123", "PUBKEY_B64", "agent1@relay")
        entry = kr.lookup("abc123")
        assert entry is not None
        assert entry["public_key_b64"] == "PUBKEY_B64"
        assert "agent1@relay" in entry["addresses"]

    def test_lookup_by_address(self, tmp_path):
        kr = Keyring(tmp_path)
        kr.add("abc123", "PUBKEY_B64", "agent1@relay")
        entry = kr.lookup_by_address("agent1@relay")
        assert entry is not None
        assert entry["fingerprint"] == "abc123"

    def test_lookup_missing(self, tmp_path):
        kr = Keyring(tmp_path)
        assert kr.lookup("nonexistent") is None
        assert kr.lookup_by_address("nobody@nowhere") is None

    def test_multi_address_same_key(self, tmp_path):
        kr = Keyring(tmp_path)
        kr.add("abc123", "PUBKEY_B64", "agent1@relay1")
        kr.add("abc123", "PUBKEY_B64", "agent1@email")
        entry = kr.lookup("abc123")
        assert len(entry["addresses"]) == 2
        assert "agent1@relay1" in entry["addresses"]
        assert "agent1@email" in entry["addresses"]

    def test_persistence(self, tmp_path):
        kr1 = Keyring(tmp_path)
        kr1.add("abc123", "PUBKEY_B64", "agent@relay")
        # Load fresh instance from same directory
        kr2 = Keyring(tmp_path)
        assert kr2.count() == 1
        assert kr2.lookup("abc123") is not None

    def test_update_last_seen(self, tmp_path):
        kr = Keyring(tmp_path)
        kr.add("abc123", "PUBKEY_B64", "agent@relay")
        first_seen = kr.lookup("abc123")["first_seen"]
        kr.add("abc123", "PUBKEY_B64", "agent@relay")
        entry = kr.lookup("abc123")
        assert entry["first_seen"] == first_seen  # unchanged
        assert entry["last_seen"] >= first_seen
