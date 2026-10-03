#!/usr/bin/env bash
# Chạy đồng thời backend (FastAPI/uvicorn) và frontend (Vite).
# Ctrl+C một lần sẽ dừng cả hai.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT/backend"
FRONTEND_DIR="$ROOT/frontend"

BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
CONDA_ENV="${CONDA_ENV:-aic}"   # conda env chứa uvicorn/torch/faiss/transformers

pids=()

cleanup() {
  echo
  echo "[run] stopping..."
  for pid in "${pids[@]}"; do
    # kill cả nhóm tiến trình con (vite/uvicorn reload spawn process con)
    kill -- -"$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  echo "[run] stopped."
}
trap cleanup INT TERM EXIT

# --- Backend ---
echo "[run] backend  -> http://$BACKEND_HOST:$BACKEND_PORT (conda env: $CONDA_ENV)"
if command -v conda >/dev/null 2>&1; then
  BACKEND_CMD="conda run --no-capture-output -n '$CONDA_ENV' uvicorn"
else
  BACKEND_CMD="uvicorn"   # fallback: uvicorn trên PATH
fi
setsid bash -c "cd '$BACKEND_DIR' && exec $BACKEND_CMD main:app --host '$BACKEND_HOST' --port '$BACKEND_PORT' --reload" &
pids+=($!)

# --- Frontend ---
echo "[run] frontend -> Vite (xem URL bên dưới)"
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  echo "[run] node_modules chưa có, chạy npm install..."
  ( cd "$FRONTEND_DIR" && npm install )
fi
setsid bash -c "cd '$FRONTEND_DIR' && exec npm run dev" &
pids+=($!)

echo "[run] đang chạy. Nhấn Ctrl+C để dừng cả hai."
wait
