#!/bin/bash
# Railway entrypoint: wire env vars -> ~/.hermes/.env, install soma-companion,
# then start the gateway in the foreground.
set -euo pipefail

HERMES_DIR="/root/.hermes"
mkdir -p "$HERMES_DIR"

# --- 1. Write Railway env vars into Hermes .env (gateway reads .env) ---
{
  echo "TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:?missing TELEGRAM_BOT_TOKEN}"
  echo "TELEGRAM_ALLOWED_USERS=${TELEGRAM_ALLOWED_USERS:?missing TELEGRAM_ALLOWED_USERS}"
  echo "SILICONFLOW_API_KEY=${SILICONFLOW_API_KEY:?missing SILICONFLOW_API_KEY}"
} > "$HERMES_DIR/.env"
chmod 600 "$HERMES_DIR/.env"

# --- 2. Install soma-companion from private repo (token via env, not baked) ---
if [ -n "${GITHUB_TOKEN:-}" ]; then
  echo "[entrypoint] installing soma-companion..."
  uv pip install --system \
    "git+https://${GITHUB_TOKEN}@github.com/redasm/Soma.git" \
    2>&1 | tail -2
  # enable the plugin if the CLI supports it (best-effort, non-fatal)
  hermes plugin enable soma-companion 2>/dev/null || true
else
  echo "[entrypoint] WARNING: GITHUB_TOKEN not set, skipping soma-companion"
fi

# --- 3. Seed model config if none exists (SiliconFlow DeepSeek-V3) ---
if [ ! -f "$HERMES_DIR/config.yaml" ] && [ -n "${SEED_CONFIG:-}" ]; then
  echo "$SEED_CONFIG" > "$HERMES_DIR/config.yaml"
fi

# --- 4. Start gateway in foreground (Railway expects PID 1 to stay up) ---
echo "[entrypoint] starting hermes gateway..."
exec hermes gateway run
