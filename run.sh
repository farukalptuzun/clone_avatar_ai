#!/bin/bash
# RunPod / sunucuda tek script ile kurulum + çalıştırma
#
# Kullanım:
#   chmod +x run.sh && ./run.sh
#   veya: bash run.sh
#
# Ortam (isteğe bağlı):
#   WORKSPACE_ROOT=/workspace   (kalıcı disk; storage + venv buraya gider)
#   REDIS_URL=redis://...      (harici Redis; yoksa localhost)
#   STORAGE_BASE_PATH=...      (WORKSPACE_ROOT varsa $WORKSPACE_ROOT/storage)
#   API_PORT=8000
#
# RunPod: WORKSPACE_ROOT=/workspace veya /runpod kullan; Redis yoksa run.sh dener.

set -e
cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"
export PROJECT_DIR

# --- Workspace: kalıcı disk kullanıyorsa storage + venv oraya ---
WORKSPACE_ROOT="${WORKSPACE_ROOT:-}"
if [ -n "$WORKSPACE_ROOT" ]; then
  export STORAGE_BASE_PATH="${STORAGE_BASE_PATH:-$WORKSPACE_ROOT/storage}"
  VENV_DIR="${VENV_DIR:-$WORKSPACE_ROOT/venv}"
else
  export STORAGE_BASE_PATH="${STORAGE_BASE_PATH:-$PROJECT_DIR/storage}"
  VENV_DIR="${VENV_DIR:-$PROJECT_DIR/venv}"
fi
export REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/0}"
export CELERY_BROKER_URL="${CELERY_BROKER_URL:-$REDIS_URL}"
export CELERY_RESULT_BACKEND="${CELERY_RESULT_BACKEND:-$REDIS_URL}"
API_PORT="${API_PORT:-8000}"

echo "[run.sh] Proje: $PROJECT_DIR"
echo "[run.sh] Storage: $STORAGE_BASE_PATH"
echo "[run.sh] API port: $API_PORT"

# --- Redis (localhost ise yoksa kur/başlat; harici REDIS_URL varsa atla) ---
if echo "$REDIS_URL" | grep -qE '^redis://127\.0\.0\.1|^redis://localhost'; then
  if ! command -v redis-server &>/dev/null; then
    echo "[run.sh] redis-server bulunamadı."
    if command -v apt-get &>/dev/null && [ -w /usr ]; then
      echo "[run.sh] Kuruluyor (sudo gerekebilir)..."
      apt-get update -qq && apt-get install -y redis-server || true
    fi
  fi
  if command -v redis-server &>/dev/null; then
    if ! redis-cli ping &>/dev/null 2>&1; then
      echo "[run.sh] Redis başlatılıyor..."
      redis-server --daemonize yes
      sleep 1
    fi
    redis-cli ping || { echo "[run.sh] Redis başlatılamadı. REDIS_URL ile harici Redis kullanın."; exit 1; }
  else
    echo "[run.sh] Redis yok. Harici Redis için: export REDIS_URL=redis://HOST:6379/0"
    exit 1
  fi
  echo "[run.sh] Redis hazır."
else
  echo "[run.sh] Harici Redis kullanılıyor: $REDIS_URL"
fi

# --- Python venv + bağımlılıklar ---
if [ ! -d "$VENV_DIR" ]; then
  echo "[run.sh] Sanal ortam oluşturuluyor: $VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
echo "[run.sh] pip güncelleniyor..."
pip install -q -U pip
echo "[run.sh] Bağımlılıklar yükleniyor..."
pip install -q -r requirements.txt
export PYTHONPATH="$PROJECT_DIR"

# --- Storage dizinleri ---
mkdir -p "$STORAGE_BASE_PATH/inputs" "$STORAGE_BASE_PATH/outputs" "$STORAGE_BASE_PATH"
echo "[run.sh] Storage dizinleri hazır."

# --- API'yi arka planda başlat ---
API_PID=""
cleanup() {
  echo "[run.sh] Kapatılıyor..."
  [ -n "$API_PID" ] && kill "$API_PID" 2>/dev/null || true
  exit 0
}
trap cleanup SIGTERM SIGINT

echo "[run.sh] API başlatılıyor (port $API_PORT)..."
uvicorn api.main:app --host 0.0.0.0 --port "$API_PORT" &
API_PID=$!
sleep 2
if ! kill -0 $API_PID 2>/dev/null; then
  echo "[run.sh] API başlatılamadı."
  exit 1
fi
echo "[run.sh] API çalışıyor: http://0.0.0.0:$API_PORT"

# --- Celery worker (önde; script bununla sürer) ---
echo "[run.sh] Celery worker başlatılıyor..."
exec celery -A workers.celery_app worker --loglevel=info
