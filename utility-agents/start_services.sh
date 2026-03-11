#!/bin/bash
# ──────────────────────────────────────────────────────────────
# AgentAZAll Utility Services — SRV99 Startup Script
#
# Starts the NLLB translation and Whisper STT service agents.
# Both agents use the existing uni-back-serv HTTP backend
# (already running on SRV99 with NLLB on cuda:0, Whisper on cuda:1).
#
# Prerequisites:
#   pip3 install agentazall
#   Each agent needs its own agent_home/ directory with config.json
#
# Usage:
#   ./start_services.sh              # Start both agents
#   ./start_services.sh translation  # Start only translation
#   ./start_services.sh whisper      # Start only Whisper STT
# ──────────────────────────────────────────────────────────────

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── Configuration ──────────────────────────────────────────────

# uni-back-serv endpoints (already running on SRV99)
TRANSLATE_HTTP="https://127.0.0.1:8000/api/translate"
WHISPER_HTTP="https://127.0.0.1:8000/api/transcribe"

# OR use direct model loading (uncomment if uni-back-serv not running):
# NLLB_MODEL_DIR="/home/gregor/models/nllb_ct2"
# WHISPER_MODEL="large-v3-turbo"
# WHISPER_DEVICE="cuda"

POLL_INTERVAL=10

# ── Helper functions ───────────────────────────────────────────

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"; }

check_agentazall() {
    if ! python3 -m agentazall --version >/dev/null 2>&1; then
        log "ERROR: agentazall not installed. Run: pip3 install agentazall"
        exit 1
    fi
    log "agentazall: $(python3 -m agentazall --version 2>&1 | head -1)"
}

setup_agent_home() {
    local name="$1"
    local dir="$SCRIPT_DIR/agent_${name}"

    if [ ! -d "$dir" ]; then
        log "Creating agent home: $dir"
        mkdir -p "$dir"
    fi

    if [ ! -f "$dir/config.json" ]; then
        log "Registering agent: $name"
        AGENTAZALL_ROOT="$dir" python3 -m agentazall register \
            --agent "${name}-service" 2>/dev/null || true
        log "Agent registered. Edit $dir/config.json to set transport."
    fi
}

# ── Main ───────────────────────────────────────────────────────

log "AgentAZAll Utility Services — Starting"
check_agentazall

SERVICE="${1:-all}"

# Setup agent homes
if [ "$SERVICE" = "all" ] || [ "$SERVICE" = "translation" ]; then
    setup_agent_home "translation"
fi
if [ "$SERVICE" = "all" ] || [ "$SERVICE" = "whisper" ]; then
    setup_agent_home "whisper"
fi

# Start services
PIDS=()

if [ "$SERVICE" = "all" ] || [ "$SERVICE" = "translation" ]; then
    log "Starting Translation Agent..."

    # Use HTTP backend if uni-back-serv is available
    if curl -sk "$TRANSLATE_HTTP" >/dev/null 2>&1; then
        log "  Using HTTP backend: $TRANSLATE_HTTP"
        python3 "$SCRIPT_DIR/translation_agent.py" \
            --work-dir "$SCRIPT_DIR/agent_translation" \
            --http-url "$TRANSLATE_HTTP" \
            --poll "$POLL_INTERVAL" &
    elif [ -n "$NLLB_MODEL_DIR" ] && [ -d "$NLLB_MODEL_DIR" ]; then
        log "  Using direct CTranslate2 backend: $NLLB_MODEL_DIR"
        python3 "$SCRIPT_DIR/translation_agent.py" \
            --work-dir "$SCRIPT_DIR/agent_translation" \
            --model-dir "$NLLB_MODEL_DIR" \
            --device cuda --device-index 0 \
            --poll "$POLL_INTERVAL" &
    else
        log "  WARNING: No translation backend available!"
        log "  Set TRANSLATE_HTTP or NLLB_MODEL_DIR in this script."
    fi
    PIDS+=($!)
    log "  Translation Agent PID: ${PIDS[-1]}"
fi

if [ "$SERVICE" = "all" ] || [ "$SERVICE" = "whisper" ]; then
    log "Starting Whisper STT Agent..."

    if curl -sk "$WHISPER_HTTP" >/dev/null 2>&1; then
        log "  Using HTTP backend: $WHISPER_HTTP"
        python3 "$SCRIPT_DIR/whisper_agent.py" \
            --work-dir "$SCRIPT_DIR/agent_whisper" \
            --http-url "$WHISPER_HTTP" \
            --poll "$POLL_INTERVAL" &
    elif python3 -c "import whisper" 2>/dev/null; then
        log "  Using direct Whisper backend: ${WHISPER_MODEL:-large-v3-turbo}"
        python3 "$SCRIPT_DIR/whisper_agent.py" \
            --work-dir "$SCRIPT_DIR/agent_whisper" \
            --model "${WHISPER_MODEL:-large-v3-turbo}" \
            --device "${WHISPER_DEVICE:-cuda}" \
            --poll "$POLL_INTERVAL" &
    else
        log "  WARNING: No Whisper backend available!"
        log "  Install openai-whisper or set WHISPER_HTTP."
    fi
    PIDS+=($!)
    log "  Whisper STT Agent PID: ${PIDS[-1]}"
fi

log "All services started. PIDs: ${PIDS[*]}"
log "Press Ctrl+C to stop all services."

# Trap SIGINT/SIGTERM to kill all children
trap 'log "Shutting down..."; kill "${PIDS[@]}" 2>/dev/null; wait; log "Done."' INT TERM

# Wait for all children
wait
