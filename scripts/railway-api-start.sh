#!/bin/sh
# ReviewPulse API entrypoint for Railway (docs/deployment-plan.md §5.1, §7).
# Works for both Railpack (repo root) and Dockerfile.api (/app).
set -eu

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
PERSIST="${RAILWAY_VOLUME_MOUNT_PATH:-/persistent}"

if [ -d "$PERSIST" ] || mkdir -p "$PERSIST" 2>/dev/null; then
  mkdir -p "$PERSIST/data" "$PERSIST/runs" "$PERSIST/config" "$PERSIST/hf"
  if [ ! -f "$PERSIST/config/settings.toml" ] && [ -f "$ROOT/config/settings.example.toml" ]; then
    cp "$ROOT/config/settings.example.toml" "$PERSIST/config/settings.toml"
  fi
  export REVIEWPULSE_DATA_DIR="${REVIEWPULSE_DATA_DIR:-$PERSIST/data}"
  export REVIEWPULSE_RUNS_DIR="${REVIEWPULSE_RUNS_DIR:-$PERSIST/runs}"
  export REVIEWPULSE_SETTINGS="${REVIEWPULSE_SETTINGS:-$PERSIST/config/settings.toml}"
  export HF_HOME="${HF_HOME:-$PERSIST/hf}"
  export TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE:-$HF_HOME}"
  export HUGGINGFACE_HUB_CACHE="${HUGGINGFACE_HUB_CACHE:-$HF_HOME}"
  export SENTENCE_TRANSFORMERS_HOME="${SENTENCE_TRANSFORMERS_HOME:-$HF_HOME}"
fi

export REVIEWPULSE_BIND_ALL="${REVIEWPULSE_BIND_ALL:-1}"
PORT_VALUE="${PORT:-8080}"

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
cd "$ROOT"

if command -v reviewpulse >/dev/null 2>&1; then
  exec reviewpulse serve --host 0.0.0.0 --port "$PORT_VALUE"
fi

if [ -f "$ROOT/main.py" ]; then
  exec python "$ROOT/main.py"
fi

exec python -m uvicorn reviewpulse.api.app:app --host 0.0.0.0 --port "$PORT_VALUE"
