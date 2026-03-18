#!/bin/bash
set -e

echo "[start] Starting Node.js WhatsApp bridge..."
node node-bridge.mjs &

echo "[start] Starting FastAPI..."
uvicorn app.main:app --host 0.0.0.0 --port 8000
