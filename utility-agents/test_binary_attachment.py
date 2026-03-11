#!/usr/bin/env python3
"""
Test binary attachment round-trip through AgentAZAll transports.

Creates a small WAV file, sends it as an attachment via the configured
transport (AgentTalk relay / email / FTP), then checks if it arrives
intact by comparing checksums.

Usage:
    python test_binary_attachment.py --config F:/AgentoAll-pub/config.json

This validates that binary payloads survive the full transport cycle:
    outbox → daemon → transport → relay → daemon → inbox
"""
import sys
import os
import struct
import hashlib
import time
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def generate_test_wav(path, duration_s=1.0, freq_hz=440, sample_rate=16000):
    """Generate a simple sine wave WAV file for testing.

    Returns the SHA256 hash of the file.
    """
    import math

    num_samples = int(sample_rate * duration_s)
    samples = []
    for i in range(num_samples):
        t = i / sample_rate
        value = int(32767 * 0.5 * math.sin(2 * math.pi * freq_hz * t))
        samples.append(struct.pack("<h", value))

    audio_data = b"".join(samples)

    # Write WAV
    with open(path, "wb") as f:
        data_size = len(audio_data)
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))
        f.write(struct.pack("<H", 1))       # PCM
        f.write(struct.pack("<H", 1))       # mono
        f.write(struct.pack("<I", sample_rate))
        f.write(struct.pack("<I", sample_rate * 2))
        f.write(struct.pack("<H", 2))
        f.write(struct.pack("<H", 16))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(audio_data)

    file_hash = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return file_hash


def generate_test_png(path):
    """Generate a minimal valid 1x1 red PNG for testing.

    Returns the SHA256 hash of the file.
    """
    # Minimal PNG: 1x1 pixel, red, 8-bit RGB
    import zlib

    def chunk(chunk_type, data):
        c = chunk_type + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I",
            zlib.crc32(c) & 0xFFFFFFFF)

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    # Pixel: filter=0 + R=255, G=0, B=0
    raw = zlib.compress(b"\x00\xff\x00\x00")
    idat = chunk(b"IDAT", raw)
    iend = chunk(b"IEND", b"")

    Path(path).write_bytes(signature + ihdr + idat + iend)
    file_hash = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return file_hash


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Test binary attachment round-trip"
    )
    parser.add_argument(
        "--config", type=str, default=None,
        help="Path to config.json (default: auto-detect)",
    )
    parser.add_argument(
        "--to", type=str, default=None,
        help="Recipient address (default: send to self)",
    )
    parser.add_argument(
        "--wait", type=int, default=30,
        help="Seconds to wait for message delivery",
    )
    args = parser.parse_args()

    from agentazall.config import load_config
    from agentazall.helpers import agent_day, today_str, ensure_dirs
    from agentazall.messages import format_message, parse_message
    from agentazall.daemon import Daemon

    # Load config
    if args.config:
        cfg = load_config(Path(args.config))
    else:
        cfg = load_config()

    agent_name = cfg.get("agent_name", "unknown")
    recipient = args.to or agent_name  # self-send by default

    print(f"Agent:     {agent_name}")
    print(f"Recipient: {recipient}")
    print(f"Transport: {cfg.get('transport', 'unknown')}")
    print()

    # Generate test files
    tmp_dir = Path("./test_attachments_tmp")
    tmp_dir.mkdir(exist_ok=True)

    wav_path = tmp_dir / "test_tone_440hz.wav"
    png_path = tmp_dir / "test_pixel_red.png"

    wav_hash = generate_test_wav(wav_path)
    png_hash = generate_test_png(png_path)

    wav_size = wav_path.stat().st_size
    png_size = png_path.stat().st_size

    print(f"Test WAV: {wav_size} bytes, SHA256={wav_hash[:16]}...")
    print(f"Test PNG: {png_size} bytes, SHA256={png_hash[:16]}...")
    print()

    # Create message with attachments
    d = today_str()
    ensure_dirs(cfg, d)

    body = (
        f"Binary attachment round-trip test.\n\n"
        f"Attached files:\n"
        f"  1. test_tone_440hz.wav ({wav_size} bytes) SHA256={wav_hash}\n"
        f"  2. test_pixel_red.png ({png_size} bytes) SHA256={png_hash}\n\n"
        f"If you receive this message with intact attachments,\n"
        f"binary payloads are working correctly."
    )

    content, msg_id = format_message(
        from_a=agent_name,
        to_a=recipient,
        subject="BINARY_TEST: Attachment round-trip validation",
        body=body,
        attachments=[str(wav_path), str(png_path)],
    )

    # Write to outbox
    outbox = agent_day(cfg, d) / "outbox"
    msg_file = outbox / f"{msg_id}.txt"
    msg_file.write_text(content, encoding="utf-8")

    # Copy attachment files to outbox attachment dir
    import shutil
    att_dir = outbox / msg_id
    att_dir.mkdir(exist_ok=True)
    shutil.copy2(str(wav_path), str(att_dir / wav_path.name))
    shutil.copy2(str(png_path), str(att_dir / png_path.name))

    print(f"Message queued: {msg_id}")
    print(f"  Outbox: {msg_file}")
    print(f"  Attachments: {att_dir}")
    print()

    # Run daemon to send
    print("Running daemon sync (sending)...")
    daemon = Daemon(cfg)
    daemon.run(once=True)
    print("  Sent.")
    print()

    if recipient == agent_name:
        # Self-send: wait and check inbox
        print(f"Waiting {args.wait}s for delivery...")
        for i in range(args.wait):
            time.sleep(1)
            if i > 0 and i % 5 == 0:
                print(f"  {i}s... running daemon sync")
                daemon.run(once=True)

        print("Running final daemon sync (receiving)...")
        daemon.run(once=True)
        print()

        # Check inbox for our message
        inbox = agent_day(cfg, d) / "inbox"
        found = False
        if inbox.exists():
            for mf in inbox.glob("*.txt"):
                headers, mbody = parse_message(mf)
                if headers and "BINARY_TEST" in headers.get("Subject", ""):
                    print(f"Message received: {mf.name}")

                    # Check attachment directory
                    att_inbox = mf.parent / mf.stem
                    if att_inbox.is_dir():
                        print(f"  Attachment dir: {att_inbox}")
                        for af in sorted(att_inbox.iterdir()):
                            data = af.read_bytes()
                            h = hashlib.sha256(data).hexdigest()
                            print(f"  {af.name}: {len(data)} bytes, SHA256={h[:16]}...")

                            # Verify
                            if af.name == wav_path.name:
                                ok = (h == wav_hash)
                                print(f"    WAV integrity: {'PASS' if ok else 'FAIL'}")
                            elif af.name == png_path.name:
                                ok = (h == png_hash)
                                print(f"    PNG integrity: {'PASS' if ok else 'FAIL'}")

                        found = True
                    else:
                        print("  WARNING: No attachment directory found!")
                        print(f"  Expected: {att_inbox}")

        if not found:
            print("Message not yet received in inbox.")
            print("This is expected for relay transport (async delivery).")
            print("Run this script again with --wait 60 for longer transports.")
    else:
        print(f"Message sent to {recipient}.")
        print("Check the recipient's inbox for the attachment.")

    # Cleanup
    import shutil as sh
    sh.rmtree(tmp_dir, ignore_errors=True)
    print("\nDone.")


if __name__ == "__main__":
    main()
