"""AgentAZAll commands: filter — manage address blacklist/whitelist."""

from ..config import load_config
from ..address_filter import (
    add_to_list,
    get_filter_status,
    remove_from_list,
    set_mode,
)


def cmd_filter(args):
    """Show or modify address filter configuration."""
    cfg = load_config()

    # Mode change
    if args.mode:
        set_mode(cfg, args.mode)
        print(f"Filter mode set to: {args.mode}")
        return

    # Blacklist operations
    if args.block:
        lst = add_to_list(cfg, "blacklist", args.block)
        print(f"Blocked: {args.block}")
        print(f"Blacklist ({len(lst)}): {', '.join(lst)}")
        return

    if args.unblock:
        lst = remove_from_list(cfg, "blacklist", args.unblock)
        print(f"Unblocked: {args.unblock}")
        print(f"Blacklist ({len(lst)}): {', '.join(lst) or '(empty)'}")
        return

    # Whitelist operations
    if args.allow:
        lst = add_to_list(cfg, "whitelist", args.allow)
        print(f"Allowed: {args.allow}")
        print(f"Whitelist ({len(lst)}): {', '.join(lst)}")
        return

    if args.disallow:
        lst = remove_from_list(cfg, "whitelist", args.disallow)
        print(f"Disallowed: {args.disallow}")
        print(f"Whitelist ({len(lst)}): {', '.join(lst) or '(empty)'}")
        return

    # Default: show current status
    status = get_filter_status(cfg)
    print(f"=== Address Filter ===")
    print(f"Mode: {status['mode']}")
    print(f"Log blocked: {status['log_blocked']}")
    print()
    bl = status["blacklist"]
    print(f"Blacklist ({len(bl)}):")
    if bl:
        for addr in bl:
            print(f"  - {addr}")
    else:
        print("  (empty)")
    print()
    wl = status["whitelist"]
    print(f"Whitelist ({len(wl)}):")
    if wl:
        for addr in wl:
            print(f"  - {addr}")
    else:
        print("  (empty)")
