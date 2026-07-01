#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "=========================================="
echo "  MOD_CTRL Dashboard - Mac/Linux launcher"
echo "=========================================="

if [ ! -f "backend/.env" ]; then
    echo
    echo "ERROR: backend/.env is missing."
    echo "Copy backend/.env.example to backend/.env and fill in MONGO_URL."
    exit 1
fi

(cd backend && python3 -m uvicorn server:app --host 0.0.0.0 --port 8001 --reload) &
BACKEND_PID=$!
sleep 3

(cd frontend && yarn start) &
FRONTEND_PID=$!
sleep 5

# open browser
if command -v xdg-open >/dev/null; then xdg-open http://localhost:3000
elif command -v open >/dev/null; then open http://localhost:3000
fi

echo
echo "Backend PID $BACKEND_PID  http://localhost:8001"
echo "Frontend PID $FRONTEND_PID  http://localhost:3000"
echo "Press Ctrl+C to stop both."

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT
wait
