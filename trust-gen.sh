#!/usr/bin/env bash
#
# AgentAZAll Trust Token Generator
# ─────────────────────────────────────────────────────────────
# Run this script on the machine where your agent's data lives.
# It generates a cryptographic trust token that proves you have
# physical access to this machine.
#
# Usage:
#   ./trust-gen.sh                     # interactive, finds agents automatically
#   ./trust-gen.sh --agent mybot       # specific agent
#   ./trust-gen.sh --bind-all gregor   # bind all agents to you (local shortcut)
#
# What this does:
#   1. Reads the agent's secret key from the filesystem (proof of access)
#   2. Generates a one-time token signed with that key
#   3. Token is valid for 10 minutes
#   4. Paste it into the web UI to bind the agent to your account
#
# For local installations (web UI on same machine):
#   Just open the web UI → Trust tab → click "Generate" → done!
#   This script is only needed for remote machines (SSH).
#

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# Find agentazall
if command -v agentazall &>/dev/null; then
    AZALL="agentazall"
elif command -v python3 &>/dev/null; then
    AZALL="python3 -m agentazall"
elif command -v python &>/dev/null; then
    AZALL="python -m agentazall"
else
    echo -e "${RED}ERROR: Python not found. Install Python 3.8+ first.${NC}"
    exit 1
fi

echo -e "${BOLD}${CYAN}"
echo "  ╔═══════════════════════════════════════════════════╗"
echo "  ║         AgentAZAll Trust Token Generator          ║"
echo "  ╚═══════════════════════════════════════════════════╝"
echo -e "${NC}"

# Parse arguments
AGENT=""
BIND_ALL=""
OWNER=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --agent|-a)
            AGENT="$2"
            shift 2
            ;;
        --bind-all)
            BIND_ALL="1"
            OWNER="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [--agent NAME] [--bind-all OWNER]"
            echo ""
            echo "Options:"
            echo "  --agent NAME      Generate token for specific agent"
            echo "  --bind-all OWNER  Bind ALL local agents to OWNER (e.g. gregor)"
            echo "  --help            Show this help"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Bind-all shortcut
if [[ -n "$BIND_ALL" ]]; then
    echo -e "${YELLOW}Binding all local agents to: ${BOLD}${OWNER}${NC}"
    echo ""
    $AZALL trust-bind-all --owner "${OWNER}@localhost"
    echo ""
    echo -e "${GREEN}Done! Run '$AZALL trust-status' to verify.${NC}"
    exit 0
fi

# Interactive mode: list agents and let user choose
if [[ -z "$AGENT" ]]; then
    echo -e "${YELLOW}Looking for agents...${NC}"
    echo ""

    # Find the mailbox directory
    MAILBOX_DIR=""
    if [[ -f "config.json" ]]; then
        MAILBOX_DIR=$(python3 -c "
import json
cfg = json.load(open('config.json'))
print(cfg.get('mailbox_dir', './data/mailboxes'))
" 2>/dev/null || echo "./data/mailboxes")
    else
        MAILBOX_DIR="./data/mailboxes"
    fi

    if [[ ! -d "$MAILBOX_DIR" ]]; then
        echo -e "${RED}No mailbox directory found at: $MAILBOX_DIR${NC}"
        echo "Run 'agentazall setup --agent yourname' first."
        exit 1
    fi

    # List agents with trust status
    AGENTS=()
    IDX=0
    for dir in "$MAILBOX_DIR"/*/; do
        name=$(basename "$dir")
        [[ "$name" == "." || "$name" == ".." ]] && continue
        [[ ! -f "$dir/.agent_key" ]] && continue

        IDX=$((IDX + 1))
        AGENTS+=("$name")

        if [[ -f "$dir/.trust" ]]; then
            owner=$(python3 -c "import json; print(json.load(open('$dir/.trust')).get('owner','?'))" 2>/dev/null || echo "?")
            echo -e "  ${IDX}. ${name}  ${GREEN}[BOUND to ${owner}]${NC}"
        else
            echo -e "  ${IDX}. ${name}  ${YELLOW}[UNBOUND]${NC}"
        fi
    done

    if [[ ${#AGENTS[@]} -eq 0 ]]; then
        echo -e "${RED}No agents found with keys.${NC}"
        exit 1
    fi

    echo ""
    read -p "Select agent number (or press Enter for #1): " CHOICE
    CHOICE=${CHOICE:-1}

    if [[ "$CHOICE" -lt 1 || "$CHOICE" -gt ${#AGENTS[@]} ]] 2>/dev/null; then
        echo -e "${RED}Invalid choice.${NC}"
        exit 1
    fi

    AGENT="${AGENTS[$((CHOICE - 1))]}"
fi

echo ""
echo -e "${CYAN}Generating trust token for: ${BOLD}${AGENT}${NC}"
echo ""

# Generate the token
$AZALL trust-gen --agent "$AGENT"

echo ""
echo -e "${GREEN}${BOLD}What to do next:${NC}"
echo ""
echo -e "  ${BOLD}Option A — Local web UI (same machine):${NC}"
echo "    Open the web UI → Trust tab → the token is already there!"
echo "    Just click 'Complete Binding' and enter your username."
echo ""
echo -e "  ${BOLD}Option B — Remote (different machine):${NC}"
echo "    Copy the entire token block above (including the frame)."
echo "    Open the web UI → Trust tab → 'Remote Bind' section."
echo "    Paste the token, enter your username, click 'Verify & Bind'."
echo ""
echo -e "  ${YELLOW}Token expires in 10 minutes. Hurry!${NC}"
