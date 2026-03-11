#!/bin/bash
# AgentAZAll Support Agent — Startup Script
# Starts Ollama pinned to GPU 2 and the support agent daemon

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MODEL="huihui_ai/qwen3.5-abliterated:9b"
GPU_ID=2  # Third A4000, dedicated to support agent

echo "=== AgentAZAll Support Agent ==="
echo "Model: $MODEL"
echo "GPU: cuda:$GPU_ID (via CUDA_VISIBLE_DEVICES)"
echo "Working dir: $SCRIPT_DIR"

mkdir -p "$SCRIPT_DIR/logs"

# Stop any existing Ollama
echo "Stopping existing Ollama instances..."
sudo systemctl stop ollama 2>/dev/null || true
pkill -f "ollama serve" 2>/dev/null || true
sleep 2

# Start Ollama pinned to GPU 2 only
echo "Starting Ollama on GPU $GPU_ID..."
CUDA_VISIBLE_DEVICES=$GPU_ID OLLAMA_HOST=127.0.0.1:11434 \
    nohup /usr/local/bin/ollama serve \
    > "$SCRIPT_DIR/logs/ollama.log" 2>&1 &

OLLAMA_PID=$!
echo "Ollama started (PID: $OLLAMA_PID)"

# Wait for Ollama to be ready
echo "Waiting for Ollama to start..."
for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:11434/api/tags > /dev/null 2>&1; then
        echo "Ollama is ready!"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "ERROR: Ollama failed to start within 30s"
        echo "Check logs: $SCRIPT_DIR/logs/ollama.log"
        exit 1
    fi
    sleep 1
done

# Pull the model if not already present
echo "Ensuring model is available..."
ollama pull "$MODEL" 2>&1 | tail -3

# Warm up the model (first inference loads it into GPU memory)
echo "Warming up model..."
curl -s http://127.0.0.1:11434/api/chat -d "{
  \"model\": \"$MODEL\",
  \"messages\": [{\"role\": \"user\", \"content\": \"Hello\"}],
  \"stream\": false
}" > /dev/null 2>&1 || true

echo "Model loaded. Checking GPU usage..."
nvidia-smi --query-gpu=index,memory.used,memory.free --format=csv

# Install agentazall if not present
pip3 show agentazall > /dev/null 2>&1 || pip3 install agentazall

# Start the support agent daemon
echo ""
echo "Starting support agent daemon..."
cd "$SCRIPT_DIR"
exec python3 agent.py --work-dir "$SCRIPT_DIR/agent_home"
