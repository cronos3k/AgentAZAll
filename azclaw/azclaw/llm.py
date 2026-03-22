"""AgentAZClaw — OpenAI-compatible LLM client.

Zero external dependencies. Uses stdlib urllib only.
Works with llama.cpp, vLLM, Ollama, LM Studio, OpenRouter,
or any endpoint that speaks /v1/chat/completions.
"""

import json
import re
import time
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def strip_think(text: str) -> str:
    """Strip <think>…</think> blocks from reasoning models."""
    if not text:
        return ""
    stripped = _THINK_RE.sub("", text).strip()
    if stripped and len(stripped) > 20:
        return stripped
    thinks = re.findall(r"<think>(.*?)</think>", text, flags=re.DOTALL)
    return "\n\n".join(t.strip() for t in thinks if t.strip()) if thinks else text.strip()


def chat_completion(
    endpoint: str,
    messages: list,
    model: str = "default",
    max_tokens: int = 8192,
    temperature: float = 0.7,
    tools: list | None = None,
    timeout: int = 600,
) -> dict:
    """Send a chat completion request. Returns dict with content, tool_calls, usage."""
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    data = json.dumps(payload).encode("utf-8")
    req = Request(
        endpoint, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    t0 = time.time()
    try:
        with urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:300]
        except Exception:
            pass
        return {"error": f"HTTP {e.code}: {body}", "elapsed": time.time() - t0}
    except URLError as e:
        return {"error": f"Connection failed: {e.reason}", "elapsed": time.time() - t0}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}", "elapsed": time.time() - t0}

    elapsed = time.time() - t0
    choice = result.get("choices", [{}])[0]
    msg = choice.get("message", {})
    usage = result.get("usage", {})

    comp_tokens = usage.get("completion_tokens", 0)
    return {
        "content": strip_think(msg.get("content", "") or ""),
        "tool_calls": msg.get("tool_calls"),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": comp_tokens,
        "tokens_per_sec": round(comp_tokens / elapsed, 1) if elapsed > 0 else 0,
        "elapsed": round(elapsed, 1),
    }


def check_health(endpoint: str) -> bool:
    """Check if a llama.cpp/vLLM server is healthy."""
    # Try /health (llama.cpp), then /v1/models (LM Studio, vLLM, Ollama)
    base = endpoint.replace("/v1/chat/completions", "")
    for path in ["/health", "/v1/models"]:
        try:
            with urlopen(base + path, timeout=5) as r:
                data = json.loads(r.read())
                if data.get("status") == "ok" or data.get("data"):
                    return True
        except Exception:
            continue
    return False
