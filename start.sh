#!/bin/bash
set -e

export FASTAPI_PORT=${FASTAPI_PORT:-8001}

echo "[start] Starting FastAPI on internal port $FASTAPI_PORT..."
uvicorn app.main:app --host 127.0.0.1 --port "$FASTAPI_PORT" &

# Wait for FastAPI to be ready before starting Node
echo "[start] Waiting for FastAPI..."
for i in $(seq 1 30); do
  if curl -s -o /dev/null http://127.0.0.1:"$FASTAPI_PORT"/docs 2>/dev/null; then
    echo "[start] FastAPI is ready."
    break
  fi
  sleep 1
done

echo "[start] Starting Node.js front server on port ${PORT:-8000}..."
node node-bridge.mjs
