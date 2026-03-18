#!/bin/bash
set -e

export FASTAPI_PORT=${FASTAPI_PORT:-8001}

echo "[start] Starting FastAPI on internal port $FASTAPI_PORT..."
uvicorn app.main:app --host 127.0.0.1 --port "$FASTAPI_PORT" &

# Give FastAPI a moment to start
sleep 2

echo "[start] Starting Node.js front server on port ${PORT:-8000}..."
node node-bridge.mjs
