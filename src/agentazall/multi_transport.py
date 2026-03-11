"""AgentAZAll multi-transport — config migration + array management.

Converts legacy single-transport config (one email, one ftp, one agenttalk)
to arrays (email_accounts, ftp_servers, relays).  Migration is idempotent —
running it twice produces the same result. Old singular keys are preserved
for backward compatibility.
"""

import copy
import logging

log = logging.getLogger("agentazall")


def migrate_config(cfg: dict) -> dict:
    """Migrate single-transport config to multi-transport arrays (idempotent).

    - cfg["email"]     → cfg["email_accounts"] (list of one)
    - cfg["ftp"]       → cfg["ftp_servers"]    (list of one)
    - cfg["agenttalk"] → cfg["relays"]         (list of one, if server non-empty)

    Old singular keys are kept intact for backward compat.
    """
    # Email accounts
    if "email_accounts" not in cfg:
        email = cfg.get("email", {})
        if email and email.get("imap_server"):
            cfg["email_accounts"] = [copy.deepcopy(email)]
        else:
            cfg["email_accounts"] = []

    # FTP servers
    if "ftp_servers" not in cfg:
        ftp = cfg.get("ftp", {})
        if ftp and ftp.get("host"):
            cfg["ftp_servers"] = [copy.deepcopy(ftp)]
        else:
            cfg["ftp_servers"] = []

    # Relays (agenttalk)
    if "relays" not in cfg:
        at = cfg.get("agenttalk", {})
        if at and at.get("server"):
            cfg["relays"] = [{
                "server": at["server"],
                "token": at.get("token", ""),
                "address": cfg.get("agent_name", ""),
            }]
        else:
            cfg["relays"] = []

    return cfg


def add_relay(cfg: dict, server_url: str, token: str = "",
              address: str = "") -> dict:
    """Add a relay server to the config. Returns updated cfg."""
    relays = cfg.setdefault("relays", [])
    for r in relays:
        if r.get("server") == server_url:
            if token:
                r["token"] = token
            if address:
                r["address"] = address
            return cfg
    entry = {"server": server_url}
    if token:
        entry["token"] = token
    if address:
        entry["address"] = address
    relays.append(entry)
    # Keep legacy key in sync with first relay
    if len(relays) == 1 or not cfg.get("agenttalk", {}).get("server"):
        cfg["agenttalk"] = {"server": server_url, "token": token}
    return cfg


def remove_relay(cfg: dict, server_url: str) -> dict:
    """Remove a relay server from the config. Returns updated cfg."""
    relays = cfg.get("relays", [])
    cfg["relays"] = [r for r in relays if r.get("server") != server_url]
    # Update legacy key
    if cfg["relays"]:
        cfg["agenttalk"] = {
            "server": cfg["relays"][0]["server"],
            "token": cfg["relays"][0].get("token", ""),
        }
    else:
        cfg["agenttalk"] = {"server": "", "token": ""}
    return cfg


def add_email_account(cfg: dict, account: dict) -> dict:
    """Add an email account to the config. Returns updated cfg."""
    accounts = cfg.setdefault("email_accounts", [])
    # Deduplicate by imap_server + username
    key = (account.get("imap_server"), account.get("username"))
    for a in accounts:
        if (a.get("imap_server"), a.get("username")) == key:
            a.update(account)
            return cfg
    accounts.append(account)
    # Keep legacy key in sync with first account
    if len(accounts) == 1:
        cfg["email"] = account
    return cfg


def add_ftp_server(cfg: dict, server: dict) -> dict:
    """Add an FTP server to the config. Returns updated cfg."""
    servers = cfg.setdefault("ftp_servers", [])
    # Deduplicate by host + port
    key = (server.get("host"), server.get("port"))
    for s in servers:
        if (s.get("host"), s.get("port")) == key:
            s.update(server)
            return cfg
    servers.append(server)
    # Keep legacy key in sync with first server
    if len(servers) == 1:
        cfg["ftp"] = server
    return cfg


def transport_summary(cfg: dict) -> str:
    """Return a human-readable summary of configured transports."""
    parts = []
    relays = cfg.get("relays", [])
    emails = cfg.get("email_accounts", [])
    ftps = cfg.get("ftp_servers", [])

    if relays:
        servers = [r.get("server", "?") for r in relays]
        parts.append(f"AgentTalk: {len(relays)} relay(s) [{', '.join(servers)}]")
    if emails:
        users = [a.get("username", "?") for a in emails]
        parts.append(f"Email: {len(emails)} account(s) [{', '.join(users)}]")
    if ftps:
        hosts = [f"{s.get('host', '?')}:{s.get('port', '?')}" for s in ftps]
        parts.append(f"FTP: {len(ftps)} server(s) [{', '.join(hosts)}]")

    if not parts:
        return "No transports configured."
    return " | ".join(parts)
