# Changelog

## [1.0.0] — 2026-03-08

### Added
- Initial public release as pip-installable Python package
- Persistent memory system (`remember`, `recall`) surviving context resets
- Inter-agent communication via email (SMTP/IMAP/POP3) and FTP transports
- Zero-dependency local email server (SMTP + IMAP + POP3)
- Daemon mode for automatic mailbox synchronization
- Gradio web UI for human participants
- 35+ CLI commands: setup, inbox, read, send, reply, search, whoami, doing,
  note, notes, remember, recall, directory, index, status, tree, dates,
  daemon, server, export, onboard, and more
- Agent onboarding flow with auto-generated identity
- Daily directory structure with automatic archival
- Cross-day memory index for persistent recall
- SHA256-based message deduplication
- ZIP export/backup via `portation` module
- Example configs and synthetic demo data
- GitHub Actions CI (ruff + pytest, Python 3.10–3.13)
