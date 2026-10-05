#!/usr/bin/env bash
# Запуск в режиме разработки: бэкенд (порт 8000) + фронтенд (порт 5173). Остановка — Ctrl+C.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ -f "$ROOT/.env" ]; then set -a; . "$ROOT/.env"; set +a; fi

PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="python3"

(cd "$ROOT/backend" && exec "$PY" -m uvicorn app.main:app --reload --port 8000) &
BACK=$!
(cd "$ROOT/frontend" && exec npm run dev) &
FRONT=$!

trap 'kill $BACK $FRONT 2>/dev/null || true' INT TERM EXIT
echo ""
echo "  Интерфейс:  http://localhost:5173"
echo "  API:        http://localhost:8000/api/health"
echo ""
wait
