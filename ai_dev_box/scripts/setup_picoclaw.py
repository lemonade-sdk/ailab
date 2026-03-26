#!/usr/bin/env python3
"""
Configure picoclaw with opinionated local-AI defaults.
Probes lemonade (port 8000) and ollama (port 11434) — both are proxied
from the host by ai-dev-box so they appear as localhost services.

picoclaw uses a LiteLLM-style config: model_list entries each specify a
model_name, model (provider/model-id), api_base, and optional api_key.
"""

import json
import os
import urllib.request
import urllib.error
from pathlib import Path

HOME = Path.home()
CONFIG_DIR = HOME / ".picoclaw"
CONFIG_FILE = CONFIG_DIR / "config.json"
WORKSPACE = HOME / "workspace"

LEMONADE_BASE = "http://localhost:8000/api/v1"
OLLAMA_BASE   = "http://localhost:11434/v1"

# Preferred Qwen models in priority order (mirrors openclaw/nullclaw preference)
PREFERRED_QWEN = [
    "Qwen3.5-27B-GGUF",
    "Qwen3.5-9B-GGUF",
    "Qwen3-8B-GGUF",
    "Qwen3.5-4B-GGUF",
    "Qwen3-4B-GGUF",
    "Qwen3.5-2B-GGUF",
    "Qwen3-1.7B-GGUF",
]

LEMONADE_STATIC_MODELS = PREFERRED_QWEN
OLLAMA_STATIC_MODELS   = ["llama3.2", "qwen2.5:7b", "mistral"]


def probe_models(base_url: str) -> list[str] | None:
    """Return list of model IDs from an OpenAI-compatible /models endpoint."""
    try:
        req = urllib.request.Request(f"{base_url}/models")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
        models = [m["id"] for m in data.get("data", []) if m.get("id")]
        return models if models else None
    except Exception:
        return None


def model_score(model_id: str) -> int:
    """Score a model for suitability as a primary chat/agent model."""
    s = model_id.lower()
    if any(x in s for x in ("flux", "sdxl", "stable-diff")):  return -30
    if any(x in s for x in ("kokoro", "whisper", "tts", "speech")): return -20
    if any(x in s for x in ("embed", "retriev")):              return -20
    score = 0
    if model_id in PREFERRED_QWEN:
        score += 100 - PREFERRED_QWEN.index(model_id)
    if "flm"      in s: score += 20
    if "gguf"     in s: score += 10
    if any(x in s for x in ("instruct", "-it-", "chat")): score += 5
    return score


def pick_best(models: list[str]) -> str | None:
    """Return the highest-scoring text-capable model."""
    candidates = [(m, model_score(m)) for m in models if model_score(m) >= 0]
    if not candidates:
        return None
    return max(candidates, key=lambda x: x[1])[0]


def build_model_entry(model_name: str, provider_prefix: str, model_id: str,
                      api_base: str, api_key: str | None = None) -> dict:
    entry = {
        "model_name": model_name,
        "model":      f"{provider_prefix}/{model_id}",
        "api_base":   api_base,
    }
    if api_key:
        entry["api_key"] = api_key
    return entry


def main():
    print("ai-dev-box: configuring picoclaw...")

    lemonade_models = probe_models(LEMONADE_BASE)
    ollama_models   = probe_models(OLLAMA_BASE)

    if lemonade_models:
        print(f"ai-dev-box: lemonade found — {len(lemonade_models)} model(s)")
    else:
        print("ai-dev-box: lemonade not reachable — pre-configuring with defaults")
        lemonade_models = LEMONADE_STATIC_MODELS

    if ollama_models:
        print(f"ai-dev-box: ollama found — {len(ollama_models)} model(s)")
    else:
        print("ai-dev-box: ollama not reachable — pre-configuring with defaults")
        ollama_models = OLLAMA_STATIC_MODELS

    lemonade_best = pick_best(lemonade_models) or PREFERRED_QWEN[1]  # Qwen3.5-9B-GGUF
    ollama_best   = pick_best(ollama_models)   or "llama3.2"

    # Build model_list — all discovered models registered, preferred first.
    # picoclaw / LiteLLM uses this list for routing and fallback.
    model_list = []

    # Lemonade models (openai-compatible)
    for mid in lemonade_models:
        model_list.append(build_model_entry(
            model_name=f"lemonade-{mid}",
            provider_prefix="openai",
            model_id=mid,
            api_base=LEMONADE_BASE,
            api_key="lemonade",
        ))

    # Ollama models
    for mid in ollama_models:
        model_list.append(build_model_entry(
            model_name=f"ollama-{mid}",
            provider_prefix="ollama",
            model_id=mid,
            api_base=OLLAMA_BASE,
        ))

    config = {
        "model_list": model_list,
        "general_settings": {
            # Prefer lemonade; fall back to ollama
            "default_model":    f"lemonade-{lemonade_best}",
            "fallback_models":  [f"ollama-{ollama_best}"],
            "workspace":        str(WORKSPACE),
        },
    }

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n")

    print("ai-dev-box: picoclaw configured")
    print(f"  config:   {CONFIG_FILE}")
    print(f"  primary:  lemonade-{lemonade_best}")
    print(f"  fallback: ollama-{ollama_best}")
    print()
    print("  Lemonade → localhost:8000  (proxied from host)")
    print("  Ollama   → localhost:11434 (proxied from host)")
    print("  Web UI   → http://localhost:18800 (accessible on host)")


if __name__ == "__main__":
    main()
