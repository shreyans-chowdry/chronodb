#!/usr/bin/env bash
# ChronoDB — Launch Both Backend and Frontend

set -e

# Ensure we are in the project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

echo "=================================================="
echo "🚀 Starting ChronoDB System"
echo "=================================================="

# Check if seed database exists, if not, create it
if [ ! -f "api_test.db" ]; then
    echo "📦 Initializing sample database..."
    python3 scripts/seed_demo.py
fi

# Function to clean up child processes on exit
cleanup() {
    echo ""
    echo "🛑 Shutting down ChronoDB servers..."
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
    echo "✅ Shutdown complete."
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

# 1. Start FastAPI Backend (Port 8000)
echo "⚡ Starting FastAPI Backend on http://localhost:8000 (and http://0.0.0.0:8000)..."
export PYTHONPATH="$ROOT_DIR:$PYTHONPATH"
python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# 2. Start Next.js Frontend (Port 3000)
echo "🌐 Starting Next.js Frontend on http://localhost:3000..."
cd "$ROOT_DIR/frontend"
npx next dev -H 0.0.0.0 -p 3000 &
FRONTEND_PID=$!

cd "$ROOT_DIR"

echo ""
echo "=================================================="
echo "✅ ChronoDB is running!"
echo "   - Web Dashboard:  http://localhost:3000"
echo "   - Diff & Merge:   http://localhost:3000/diff"
echo "   - Swagger Docs:   http://localhost:8000/docs"
echo "=================================================="
echo "Press Ctrl+C to stop both servers."
echo ""

# Wait for both processes
wait $BACKEND_PID $FRONTEND_PID
