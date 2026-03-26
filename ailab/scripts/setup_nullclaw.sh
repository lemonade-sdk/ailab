#!/bin/sh
# Configure nullclaw with opinionated local-AI defaults.
# Probes lemonade (port 8000) and ollama (port 11434) — both are proxied
# from the host by ailab so they appear as localhost services.
# Adapted from ubuclaw/snap/local/bin/setup-providers (non-snap version).
set -eu

# Honour per-container config dir set by the installer; fall back to default.
CONFIG_DIR="${NULLCLAW_CONFIG_DIR:-${HOME}/.nullclaw}"
CONFIG_FILE="${CONFIG_DIR}/config.json"
WORKSPACE="${HOME}/workspace"

# Probe an OpenAI-compatible /models endpoint.
# Prints model IDs one per line; prints nothing on failure.
probe_models() {
    curl -sf --connect-timeout 3 --max-time 5 "${1}/models" 2>/dev/null \
        | grep -o '"id"[[:space:]]*:[[:space:]]*"[^"]*"' \
        | sed 's/.*"id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/'
}

# Score a model ID for suitability as a primary chat/agent model.
score_model() {
    local id lower score
    id="$1"
    lower=$(printf '%s' "$id" | tr '[:upper:]' '[:lower:]')
    case "$lower" in
        *flux*|*sdxl*|*stable?diff*) printf '%s\n' -30; return ;;
        *kokoro*|*whisper*|*tts*|*speech*) printf '%s\n' -20; return ;;
        *embed*|*retriev*) printf '%s\n' -20; return ;;
    esac
    score=0
    # Preferred Qwen models (mirrors ubuclaw preference)
    case "$id" in
        Qwen3.5-27B-GGUF) score=$((score + 100)) ;;
        Qwen3.5-9B-GGUF)  score=$((score + 99))  ;;
        Qwen3-8B-GGUF)    score=$((score + 98))  ;;
        Qwen3.5-4B-GGUF)  score=$((score + 97))  ;;
        Qwen3-4B-GGUF)    score=$((score + 96))  ;;
        Qwen3.5-2B-GGUF)  score=$((score + 95))  ;;
        Qwen3-1.7B-GGUF)  score=$((score + 94))  ;;
    esac
    case "$lower" in *flm*)                    score=$((score + 20)) ;; esac
    case "$lower" in *gguf*)                   score=$((score + 10)) ;; esac
    case "$lower" in *instruct*|*-it-*|*chat*) score=$((score +  5)) ;; esac
    printf '%s\n' "$score"
}

# From a newline-separated list of model IDs on stdin, select the highest scorer.
pick_best() {
    local best_id best_score id s
    best_id=""
    best_score=-999
    while IFS= read -r id; do
        [ -z "$id" ] && continue
        s=$(score_model "$id")
        if [ "$s" -ge 0 ] && [ "$s" -gt "$best_score" ]; then
            best_score="$s"
            best_id="$id"
        fi
    done
    [ -n "$best_id" ] && printf '%s\n' "$best_id"
}

# Static fallback model lists used when a provider isn't reachable at setup time.
LEMONADE_STATIC="Qwen3.5-27B-GGUF
Qwen3.5-9B-GGUF
Qwen3-8B-GGUF
Qwen3.5-4B-GGUF
Qwen3-4B-GGUF
Qwen3.5-2B-GGUF
Qwen3-1.7B-GGUF"

OLLAMA_STATIC="llama3.2
qwen2.5:7b
mistral"

# ── Probe ─────────────────────────────────────────────────────────────────────

printf 'ailab: configuring nullclaw...\n'

LEMONADE_MODELS=$(probe_models "http://localhost:8000/api/v1" || true)
OLLAMA_MODELS=$(probe_models "http://localhost:11434/v1" || true)

LEMONADE_LIVE=0
OLLAMA_LIVE=0

if [ -n "$LEMONADE_MODELS" ]; then
    LEMONADE_LIVE=1
    LCOUNT=$(printf '%s\n' "$LEMONADE_MODELS" | grep -c . || true)
    printf 'ailab: lemonade found — %s model(s)\n' "$LCOUNT"
else
    printf 'ailab: lemonade not reachable — pre-configuring with defaults\n'
    LEMONADE_MODELS="$LEMONADE_STATIC"
fi

if [ -n "$OLLAMA_MODELS" ]; then
    OLLAMA_LIVE=1
    OCOUNT=$(printf '%s\n' "$OLLAMA_MODELS" | grep -c . || true)
    printf 'ailab: ollama found — %s model(s)\n' "$OCOUNT"
else
    printf 'ailab: ollama not reachable — pre-configuring with defaults\n'
    OLLAMA_MODELS="$OLLAMA_STATIC"
fi

# ── Select primary / fallback ─────────────────────────────────────────────────

LEMONADE_BEST=$(printf '%s\n' "$LEMONADE_MODELS" | pick_best)
OLLAMA_BEST=$(printf '%s\n' "$OLLAMA_MODELS"    | pick_best)

PRIMARY="lemonade/${LEMONADE_BEST:-Qwen3.5-9B-GGUF}"
FALLBACK_MODEL="ollama/${OLLAMA_BEST:-llama3.2}"

# ── Build and write config.json ───────────────────────────────────────────────

mkdir -p "$CONFIG_DIR" "$WORKSPACE"

cat > "$CONFIG_FILE" <<NULLCLAW_CFG
{
  "models": {
    "providers": {
      "lemonade": {"base_url": "http://localhost:8000", "api_key": "lemonade"},
      "ollama":   {"base_url": "http://localhost:11434"}
    }
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "${PRIMARY}",
        "fallbacks": ["${FALLBACK_MODEL}"]
      },
      "workspace": "${WORKSPACE}"
    }
  },
  "gateway": {
    "port": 3000,
    "require_pairing": false
  }
}
NULLCLAW_CFG

printf 'ailab: nullclaw configured\n'
printf '  config:   %s\n' "$CONFIG_FILE"
printf '  primary:  %s\n' "$PRIMARY"
printf '  fallback: %s\n' "$FALLBACK_MODEL"
printf '\n'
printf '  Lemonade → localhost:8000  (proxied from host)\n'
printf '  Ollama   → localhost:11434 (proxied from host)\n'
printf '  Gateway  → http://localhost:3000 (accessible on host)\n'
