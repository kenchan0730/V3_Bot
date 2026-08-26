#!/usr/bin/env bash
# V4.5 Desktop 一鍵啟動（建置前端 + 啟動 API + 開啟瀏覽器）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DESKTOP="$ROOT/V4.5_Desktop"
FRONTEND="$DESKTOP/frontend"
PORT=8765
URL="http://127.0.0.1:${PORT}"

export PYTHONPATH="$ROOT"

cd "$ROOT"

# 載入 .env（若存在）
if [[ -f "$ROOT/data/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/data/.env"
  set +a
fi

# Finnhub：相容 FINNHUB_KEY / FINNHUB_API_KEY
if [[ -z "${FINNHUB_API_KEY:-}" && -n "${FINNHUB_KEY:-}" ]]; then
  export FINNHUB_API_KEY="$FINNHUB_KEY"
fi

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "❌ 找不到指令：$1"
  exit 1
  fi
}

need_cmd python3

echo "════════════════════════════════════════"
echo "  V4.5 Intelligence Desktop"
echo "  版本分支：cursor/v45-desktop-intelligence-16b9"
echo "════════════════════════════════════════"

# Python 依賴
if ! python3 -c "import fastapi, uvicorn, yfinance" 2>/dev/null; then
  echo "📦 安裝 Python 依賴…"
  python3 -m pip install -r "$ROOT/requirements.txt" -q
  python3 -m pip install -r "$DESKTOP/requirements.txt" -q
fi

# 前端建置
if [[ ! -d "$FRONTEND/dist" ]]; then
  need_cmd npm
  echo "📦 建置前端（首次約 1–2 分鐘）…"
  cd "$FRONTEND"
  npm install --silent
  npm run build
  cd "$ROOT"
fi

# 檢查埠是否已被佔用
if command -v lsof >/dev/null 2>&1 && lsof -i ":$PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
  echo "⚠️  port $PORT 已在使用中，假設服務已啟動。"
else
  echo "🚀 啟動後端 API：$URL"
  cd "$DESKTOP/backend"
  nohup python3 -m uvicorn app:app --host 127.0.0.1 --port "$PORT" > /tmp/v45-desktop.log 2>&1 &
  echo $! > /tmp/v45-desktop.pid
  cd "$ROOT"
  sleep 2
fi

# 開啟瀏覽器
echo "🌐 開啟瀏覽器：$URL"
if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL" >/dev/null 2>&1 &
elif command -v open >/dev/null 2>&1; then
  open "$URL"
else
  echo "請手動在瀏覽器打開：$URL"
fi

echo ""
echo "✅ 已啟動。關閉方式："
echo "   kill \$(cat /tmp/v45-desktop.pid)   # 或關閉終端機"
echo "   日誌：tail -f /tmp/v45-desktop.log"
echo ""
