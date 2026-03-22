"""AgentAZClaw — Auto-backend: hardware detection, model download, server management.

Detects GPU/CPU/RAM, recommends the best ungated GGUF model,
downloads it, and starts a llama-server instance. Zero config.

All models verified ungated on HuggingFace — no tokens required.
"""

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError


# ── Model Registry ─────────────────────────────────────────────────
# Every URL here has been verified to return HTTP 302 (redirect to CDN)
# without authentication. No HuggingFace tokens required.

MODELS = [
    {
        "id": "nemotron-30b-q8",
        "name": "NVIDIA Nemotron-3-Nano-30B-A3B (Q8 — full quality)",
        "url": "https://huggingface.co/lmstudio-community/NVIDIA-Nemotron-3-Nano-30B-A3B-GGUF/resolve/main/NVIDIA-Nemotron-3-Nano-30B-A3B-Q8_0.gguf",
        "filename": "Nemotron-3-Nano-30B-A3B-Q8_0.gguf",
        "size_gb": 32.0,
        "min_vram_mb": 40000,
        "min_ram_mb": 0,
        "tier": "multi-gpu-48gb",
        "params": "30B MoE (3B active)",
        "speed_hint": "100-150 tok/s on dual GPU",
        "description": "Full quality MoE. Proven in 9-hour COBOL migration run.",
    },
    {
        "id": "nemotron-30b-q4",
        "name": "NVIDIA Nemotron-3-Nano-30B-A3B (Q4_K_M)",
        "url": "https://huggingface.co/lmstudio-community/NVIDIA-Nemotron-3-Nano-30B-A3B-GGUF/resolve/main/NVIDIA-Nemotron-3-Nano-30B-A3B-Q4_K_M.gguf",
        "filename": "Nemotron-3-Nano-30B-A3B-Q4_K_M.gguf",
        "size_gb": 16.0,
        "min_vram_mb": 20000,
        "min_ram_mb": 0,
        "tier": "single-gpu-24gb",
        "params": "30B MoE (3B active)",
        "speed_hint": "80-140 tok/s on RTX 3090/4090",
        "description": "Best tool calling MoE. Fits a single 24GB GPU.",
    },
    {
        "id": "granite-8b-q4",
        "name": "IBM Granite 3.3 8B Instruct (Q4_K_M)",
        "url": "https://huggingface.co/ibm-granite/granite-3.3-8b-instruct-GGUF/resolve/main/granite-3.3-8b-instruct-Q4_K_M.gguf",
        "filename": "granite-3.3-8b-instruct-Q4_K_M.gguf",
        "size_gb": 5.0,
        "min_vram_mb": 10000,
        "min_ram_mb": 0,
        "tier": "single-gpu-16gb",
        "params": "8B dense",
        "speed_hint": "40-80 tok/s",
        "description": "IBM enterprise model. Solid all-around at 8B.",
    },
    {
        "id": "qwen3-8b-q4",
        "name": "Qwen3-8B Instruct (Q4_K_M)",
        "url": "https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/main/Qwen3-8B-Q4_K_M.gguf",
        "filename": "Qwen3-8B-Q4_K_M.gguf",
        "size_gb": 5.0,
        "min_vram_mb": 8000,
        "min_ram_mb": 0,
        "tier": "single-gpu-12gb",
        "params": "8B dense",
        "speed_hint": "40-70 tok/s",
        "description": "Strongest code generation at 8B class.",
    },
    {
        "id": "qwen3-4b-q4",
        "name": "Qwen3-4B Instruct (Q4_K_M)",
        "url": "https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf",
        "filename": "Qwen3-4B-Q4_K_M.gguf",
        "size_gb": 2.5,
        "min_vram_mb": 5000,
        "min_ram_mb": 0,
        "tier": "single-gpu-8gb",
        "params": "4B dense",
        "speed_hint": "50-90 tok/s",
        "description": "Compact but capable. Fits 8GB GPUs.",
    },
    {
        "id": "granite-2b-q4",
        "name": "IBM Granite 3.3 2B Instruct (Q4_K_M)",
        "url": "https://huggingface.co/ibm-granite/granite-3.3-2b-instruct-GGUF/resolve/main/granite-3.3-2b-instruct-Q4_K_M.gguf",
        "filename": "granite-3.3-2b-instruct-Q4_K_M.gguf",
        "size_gb": 1.5,
        "min_vram_mb": 0,
        "min_ram_mb": 8000,
        "tier": "cpu-16gb",
        "params": "2B dense",
        "speed_hint": "8-15 tok/s on CPU",
        "description": "IBM enterprise model designed for CPU inference.",
    },
    {
        "id": "qwen3-0.6b-q8",
        "name": "Qwen3-0.6B (Q8_0 — full precision at tiny size)",
        "url": "https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/resolve/main/Qwen3-0.6B-Q8_0.gguf",
        "filename": "Qwen3-0.6B-Q8_0.gguf",
        "size_gb": 0.6,
        "min_vram_mb": 0,
        "min_ram_mb": 4000,
        "tier": "cpu-minimal",
        "params": "0.6B dense",
        "speed_hint": "10-20 tok/s on CPU",
        "description": "Smallest viable model. For testing or very limited hardware.",
    },
]


# ── Hardware Detection ──────────────────────────────────────────────

def detect_hardware() -> dict:
    """Detect GPUs, RAM, disk space, and OS."""
    info = {
        "gpus": [],
        "total_vram_mb": 0,
        "ram_mb": 0,
        "disk_free_gb": 0,
        "os": platform.system(),
        "arch": platform.machine(),
        "has_nvidia": False,
        "has_apple_silicon": False,
    }

    # NVIDIA GPU detection via nvidia-smi
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            for line in r.stdout.strip().split("\n"):
                if "," in line:
                    name, vram = line.rsplit(",", 1)
                    vram_mb = int(vram.strip())
                    info["gpus"].append({"name": name.strip(), "vram_mb": vram_mb})
                    info["total_vram_mb"] += vram_mb
            info["has_nvidia"] = len(info["gpus"]) > 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Apple Silicon detection
    if info["os"] == "Darwin" and info["arch"] == "arm64":
        info["has_apple_silicon"] = True
        # On Apple Silicon, unified memory is shared between CPU and GPU
        # We'll use total RAM as approximate "VRAM"
        try:
            r = subprocess.run(["sysctl", "-n", "hw.memsize"],
                               capture_output=True, text=True, timeout=5)
            total_bytes = int(r.stdout.strip())
            # Apple Silicon can use ~75% of unified memory for GPU
            apple_vram = int(total_bytes * 0.75 / (1024 * 1024))
            info["gpus"].append({"name": "Apple Silicon (Metal)", "vram_mb": apple_vram})
            info["total_vram_mb"] = apple_vram
        except Exception:
            pass

    # System RAM
    try:
        if info["os"] == "Windows":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            c_ulonglong = ctypes.c_ulonglong

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", c_ulonglong),
                    ("ullAvailPhys", c_ulonglong),
                    ("ullTotalPageFile", c_ulonglong),
                    ("ullAvailPageFile", c_ulonglong),
                    ("ullTotalVirtual", c_ulonglong),
                    ("ullAvailVirtual", c_ulonglong),
                    ("ullAvailExtendedVirtual", c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            info["ram_mb"] = stat.ullTotalPhys // (1024 * 1024)
        else:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal"):
                        info["ram_mb"] = int(line.split()[1]) // 1024
                        break
    except Exception:
        info["ram_mb"] = 8000  # assume 8GB as fallback

    # Disk space
    try:
        usage = shutil.disk_usage(".")
        info["disk_free_gb"] = usage.free // (1024 ** 3)
    except Exception:
        info["disk_free_gb"] = 10

    return info


def recommend_model(info: dict) -> dict:
    """Pick the best model for the detected hardware."""
    vram = info["total_vram_mb"]
    ram = info["ram_mb"]

    for model in MODELS:
        if model["min_vram_mb"] > 0:
            # GPU model — check VRAM
            if vram >= model["min_vram_mb"]:
                return model
        else:
            # CPU model — check RAM
            if ram >= model["min_ram_mb"]:
                return model

    # Absolute fallback
    return MODELS[-1]


def show_all_models(info: dict) -> list[dict]:
    """Show all models with compatibility status."""
    vram = info["total_vram_mb"]
    ram = info["ram_mb"]
    result = []
    for m in MODELS:
        fits = False
        if m["min_vram_mb"] > 0:
            fits = vram >= m["min_vram_mb"]
        else:
            fits = ram >= m["min_ram_mb"]
        result.append({**m, "fits": fits})
    return result


# ── Model Download ──────────────────────────────────────────────────

def download_model(model: dict, target_dir: str,
                   progress_callback=None) -> str:
    """Download a GGUF model file. Returns the local file path."""
    os.makedirs(target_dir, exist_ok=True)
    filepath = os.path.join(target_dir, model["filename"])

    # Skip if already downloaded
    if os.path.exists(filepath):
        actual_size = os.path.getsize(filepath)
        expected_bytes = int(model["size_gb"] * 1024 * 1024 * 1024)
        # Allow 10% tolerance (quantization sizes vary)
        if actual_size > expected_bytes * 0.8:
            print(f"  Model already downloaded: {filepath}")
            return filepath
        else:
            print(f"  Incomplete download detected, re-downloading...")
            os.remove(filepath)

    url = model["url"]
    print(f"  Downloading {model['name']}...")
    print(f"  URL: {url}")
    print(f"  Size: ~{model['size_gb']:.1f} GB")
    print(f"  Target: {filepath}")

    req = Request(url, headers={"User-Agent": "AgentAZClaw/0.1"})
    try:
        with urlopen(req, timeout=30) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 1024 * 1024  # 1MB chunks

            with open(filepath + ".partial", "wb") as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)

                    if total > 0:
                        pct = downloaded / total * 100
                        bar_len = 40
                        filled = int(bar_len * downloaded / total)
                        bar = "=" * filled + "-" * (bar_len - filled)
                        mb_done = downloaded / (1024 * 1024)
                        mb_total = total / (1024 * 1024)
                        sys.stdout.write(
                            f"\r  [{bar}] {pct:.1f}% ({mb_done:.0f}/{mb_total:.0f} MB)")
                        sys.stdout.flush()

                        if progress_callback:
                            progress_callback(downloaded, total)

            print()  # newline after progress bar

        # Rename from .partial to final
        os.rename(filepath + ".partial", filepath)
        print(f"  Download complete: {filepath}")
        return filepath

    except Exception as e:
        # Clean up partial download
        partial = filepath + ".partial"
        if os.path.exists(partial):
            os.remove(partial)
        raise RuntimeError(f"Download failed: {e}")


# ── llama-server Management ─────────────────────────────────────────

def find_llama_server() -> str | None:
    """Find llama-server binary on the system."""
    # Check common locations
    candidates = [
        "llama-server",                    # on PATH
        "llama.cpp/build/bin/llama-server", # built from source (relative)
    ]

    # Platform-specific paths
    if platform.system() == "Windows":
        candidates.extend([
            "llama-server.exe",
            os.path.expanduser("~/llama.cpp/build/bin/Release/llama-server.exe"),
        ])
    else:
        candidates.extend([
            os.path.expanduser("~/llama.cpp/build/bin/llama-server"),
            "/usr/local/bin/llama-server",
            os.path.expanduser("~/.local/bin/llama-server"),
        ])

    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return os.path.abspath(c)
        # Also try which/where
        try:
            r = subprocess.run(
                ["which", c] if platform.system() != "Windows" else ["where", c],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                return r.stdout.strip().split("\n")[0]
        except Exception:
            pass

    return None


def start_server(model_path: str, port: int = 8400,
                 llama_server: str | None = None,
                 gpu_layers: int = -1,
                 ctx_size: int = 32768) -> dict:
    """Start a llama-server instance. Returns server info dict."""
    server = llama_server or find_llama_server()
    if not server:
        raise RuntimeError(
            "llama-server not found. Install llama.cpp or provide the path:\n"
            "  git clone https://github.com/ggml-org/llama.cpp\n"
            "  cd llama.cpp && cmake -B build -DGGML_CUDA=ON && cmake --build build --config Release\n"
            "Or install via: brew install llama.cpp (macOS)"
        )

    # Check if port is already in use
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
        sock.close()
    except OSError:
        # Port in use — try next 10 ports
        for p in range(port + 1, port + 11):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.bind(("127.0.0.1", p))
                sock.close()
                port = p
                break
            except OSError:
                continue
        else:
            raise RuntimeError(f"No free port found in range {port}-{port+10}")

    cmd = [
        server,
        "--model", model_path,
        "--port", str(port),
        "--host", "127.0.0.1",
        "--n-gpu-layers", str(gpu_layers),
        "--ctx-size", str(ctx_size),
        "--parallel", "1",
    ]

    # Add flash attention if supported
    cmd.extend(["--flash-attn", "on"])

    print(f"  Starting llama-server on port {port}...")
    print(f"  Command: {' '.join(cmd)}")

    # Start in background
    log_path = os.path.join(os.getcwd(), "logs", "llama-server.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    log_file = open(log_path, "w")

    if platform.system() == "Windows":
        proc = subprocess.Popen(
            cmd, stdout=log_file, stderr=log_file,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        proc = subprocess.Popen(
            cmd, stdout=log_file, stderr=log_file,
            start_new_session=True,
        )

    # Wait for server to become healthy
    endpoint = f"http://127.0.0.1:{port}/v1/chat/completions"
    health_url = f"http://127.0.0.1:{port}/health"

    print(f"  Waiting for server to start...", end="")
    for i in range(60):  # wait up to 60 seconds
        time.sleep(1)
        sys.stdout.write(".")
        sys.stdout.flush()

        # Check if process died
        if proc.poll() is not None:
            log_file.close()
            with open(log_path) as f:
                tail = f.read()[-500:]
            raise RuntimeError(f"llama-server exited with code {proc.returncode}:\n{tail}")

        try:
            with urlopen(health_url, timeout=2) as r:
                data = json.loads(r.read())
                if data.get("status") == "ok":
                    print(f" ready!")
                    return {
                        "pid": proc.pid,
                        "port": port,
                        "endpoint": endpoint,
                        "model_path": model_path,
                        "log": log_path,
                    }
        except Exception:
            pass

    # Timeout
    proc.terminate()
    log_file.close()
    raise RuntimeError(f"llama-server failed to start within 60 seconds. Check {log_path}")


def stop_server(pid: int):
    """Stop a running llama-server by PID."""
    try:
        if platform.system() == "Windows":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, timeout=5)
        else:
            os.kill(pid, 15)  # SIGTERM
    except Exception:
        pass


# ── Interactive Setup ───────────────────────────────────────────────

def interactive_setup(data_dir: str = "./azclaw-data") -> dict:
    """Interactive hardware detection and model setup. Returns config dict."""
    print("\n  AgentAZClaw — Backend Setup\n")
    print("  Scanning hardware...")

    info = detect_hardware()

    # Display hardware
    if info["gpus"]:
        for g in info["gpus"]:
            print(f"  GPU: {g['name']} ({g['vram_mb']} MB)")
        print(f"  Total VRAM: {info['total_vram_mb']} MB")
    else:
        print("  GPU: none detected (CPU-only mode)")
    print(f"  RAM: {info['ram_mb'] // 1024} GB")
    print(f"  Disk: {info['disk_free_gb']} GB free")
    print(f"  OS: {info['os']} {info['arch']}")
    print()

    # Recommend model
    recommended = recommend_model(info)
    print(f"  Recommended: {recommended['name']}")
    print(f"  → {recommended['params']}, ~{recommended['size_gb']:.1f} GB download")
    print(f"  → {recommended['speed_hint']}")
    print(f"  → {recommended['description']}")
    print()

    print("  [1] Accept recommendation")
    print("  [2] Show all models")
    print("  [3] I already have a server running (enter URL)")
    print("  [4] Skip — I'll configure manually later")

    try:
        choice = input("\n  Choice [1]: ").strip() or "1"
    except (EOFError, KeyboardInterrupt):
        choice = "4"

    config = {"backend": "none", "endpoint": ""}

    if choice == "1":
        model_dir = os.path.join(data_dir, "models")
        model_path = download_model(recommended, model_dir)
        server_info = start_server(model_path)
        config = {
            "backend": "llama-server",
            "endpoint": server_info["endpoint"],
            "model": recommended["id"],
            "model_path": model_path,
            "server_pid": server_info["pid"],
            "port": server_info["port"],
        }

    elif choice == "2":
        all_models = show_all_models(info)
        print()
        for i, m in enumerate(all_models):
            fits = "OK" if m["fits"] else "--"
            print(f"  [{i+1}] [{fits}] {m['name']} ({m['size_gb']:.1f}GB) — {m['description']}")
        print()
        try:
            idx = int(input("  Choose model number: ").strip()) - 1
            if 0 <= idx < len(all_models):
                selected = all_models[idx]
                model_dir = os.path.join(data_dir, "models")
                model_path = download_model(selected, model_dir)
                server_info = start_server(model_path)
                config = {
                    "backend": "llama-server",
                    "endpoint": server_info["endpoint"],
                    "model": selected["id"],
                    "model_path": model_path,
                    "server_pid": server_info["pid"],
                    "port": server_info["port"],
                }
        except (ValueError, IndexError, EOFError):
            print("  Invalid choice. Skipping backend setup.")

    elif choice == "3":
        try:
            url = input("  Enter endpoint URL: ").strip()
            if url:
                config = {"backend": "external", "endpoint": url}
        except (EOFError, KeyboardInterrupt):
            pass

    # Save config
    config_path = os.path.join(data_dir, "backend.json")
    os.makedirs(data_dir, exist_ok=True)
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    print(f"\n  Config saved: {config_path}")

    if config.get("endpoint"):
        print(f"  Endpoint: {config['endpoint']}")
        print(f"\n  Ready! Run: azclaw run --task \"Build a todo app\"")

    return config


# ── Non-Interactive (for scripts/CI) ────────────────────────────────

def auto_setup(data_dir: str = "./azclaw-data",
               model_id: str | None = None) -> dict:
    """Non-interactive setup. Detects hardware, downloads model, starts server."""
    info = detect_hardware()

    if model_id:
        model = next((m for m in MODELS if m["id"] == model_id), None)
        if not model:
            raise ValueError(f"Unknown model: {model_id}. Available: {[m['id'] for m in MODELS]}")
    else:
        model = recommend_model(info)

    model_dir = os.path.join(data_dir, "models")
    model_path = download_model(model, model_dir)
    server_info = start_server(model_path)

    config = {
        "backend": "llama-server",
        "endpoint": server_info["endpoint"],
        "model": model["id"],
        "model_path": model_path,
        "server_pid": server_info["pid"],
        "port": server_info["port"],
    }

    config_path = os.path.join(data_dir, "backend.json")
    os.makedirs(data_dir, exist_ok=True)
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    return config
