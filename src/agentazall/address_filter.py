"""Address filtering — blacklist/whitelist with glob patterns.

Provides pre-disk message filtering for all transports.
Blocked messages are discarded before they touch the filesystem.
"""

import fnmatch
import logging

log = logging.getLogger("agentazall")


def should_accept(cfg: dict, sender: str) -> bool:
    """Return True if a message from *sender* should be accepted.

    Modes:
        blacklist (default) — accept all EXCEPT blacklisted addresses.
        whitelist           — reject all EXCEPT whitelisted addresses.
        off                 — no filtering, accept everything.

    Blacklist is always checked first.  If an address appears on both
    lists, the blacklist wins (blocked).
    """
    af = cfg.get("address_filter", {})
    mode = af.get("mode", "blacklist")

    if mode == "off":
        return True

    sender_lower = sender.strip().lower()
    if not sender_lower:
        return True  # empty sender = local message, always accept

    blacklist = [p.lower() for p in af.get("blacklist", [])]
    whitelist = [p.lower() for p in af.get("whitelist", [])]

    # Blacklist always checked first — blacklist wins over whitelist
    for pattern in blacklist:
        if fnmatch.fnmatch(sender_lower, pattern):
            if af.get("log_blocked", True):
                log.info("Blocked message from %s (blacklist: %s)", sender, pattern)
            return False

    if mode == "whitelist":
        if not whitelist:
            return True  # empty whitelist = accept all (safe default)
        for pattern in whitelist:
            if fnmatch.fnmatch(sender_lower, pattern):
                return True
        if af.get("log_blocked", True):
            log.info("Blocked message from %s (not on whitelist)", sender)
        return False

    return True  # blacklist mode, sender not on blacklist → accept


def add_to_list(cfg: dict, list_name: str, address: str) -> list:
    """Add address/pattern to blacklist or whitelist.  Saves config."""
    from .config import save_config

    af = cfg.setdefault("address_filter", {
        "mode": "blacklist", "blacklist": [], "whitelist": [], "log_blocked": True,
    })
    lst = af.setdefault(list_name, [])
    addr = address.strip()
    if addr.lower() not in [x.lower() for x in lst]:
        lst.append(addr)
        save_config(cfg)
    return list(lst)


def remove_from_list(cfg: dict, list_name: str, address: str) -> list:
    """Remove address/pattern from blacklist or whitelist.  Saves config."""
    from .config import save_config

    af = cfg.get("address_filter", {})
    lst = af.get(list_name, [])
    addr_lower = address.strip().lower()
    af[list_name] = [x for x in lst if x.lower() != addr_lower]
    save_config(cfg)
    return list(af[list_name])


def set_mode(cfg: dict, mode: str):
    """Set filter mode: 'blacklist', 'whitelist', or 'off'."""
    from .config import save_config

    if mode not in ("blacklist", "whitelist", "off"):
        raise ValueError(f"Invalid mode: {mode!r}  (use: blacklist, whitelist, off)")
    af = cfg.setdefault("address_filter", {
        "mode": "blacklist", "blacklist": [], "whitelist": [], "log_blocked": True,
    })
    af["mode"] = mode
    save_config(cfg)


def get_filter_status(cfg: dict) -> dict:
    """Return current filter configuration."""
    af = cfg.get("address_filter", {})
    return {
        "mode": af.get("mode", "blacklist"),
        "blacklist": list(af.get("blacklist", [])),
        "whitelist": list(af.get("whitelist", [])),
        "log_blocked": af.get("log_blocked", True),
    }
