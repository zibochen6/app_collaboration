#!/bin/bash

# Provisioning Station - Development Mode with Hot Reload
# Builds frontend then runs backend with --reload

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PORT=3260

echo "=========================================="
echo "  Provisioning Station - Dev Mode"
echo "=========================================="
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
NC='\033[0m'

# Function to cleanup on exit
cleanup() {
    echo ""
    echo "Shutting down..."
    kill $BACKEND_PID 2>/dev/null || true
    exit 0
}

trap cleanup SIGINT SIGTERM

# Check dependencies
if ! command -v uv &> /dev/null; then
    echo "Error: uv is not installed. Please install it first:"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

if ! command -v npm &> /dev/null; then
    echo "Error: npm is not installed. Please install Node.js first."
    exit 1
fi

# Install dependencies
echo -e "${BLUE}[1/4]${NC} Checking backend dependencies..."
cd "$PROJECT_DIR"
uv sync --quiet

echo -e "${BLUE}[2/4]${NC} Checking frontend dependencies..."
cd "$PROJECT_DIR/frontend"
if [ ! -d "node_modules" ]; then
    npm install --silent
fi

# Cleanup leftover processes on ports
echo -e "${BLUE}[3/4]${NC} Checking ports..."
cd "$PROJECT_DIR"
if ! uv run python scripts/port_cleanup.py $BACKEND_PORT; then
    echo -e "${YELLOW}Warning: Port may still be in use${NC}"
    echo "If startup fails, manually kill the blocking process or use a different port."
    sleep 2
fi

# Build frontend
echo -e "${BLUE}[4/4]${NC} Building frontend..."
cd "$PROJECT_DIR/frontend"
npm run build --silent 2>/dev/null || npm run build

# Start backend with hot reload
cd "$PROJECT_DIR"
echo -e "${GREEN}Starting backend on http://localhost:${BACKEND_PORT}${NC}"
uv run uvicorn provisioning_station.main:app --host 0.0.0.0 --port $BACKEND_PORT --reload &
BACKEND_PID=$!

sleep 2

echo ""
echo "=========================================="
echo -e "${GREEN}Provisioning Station is running!${NC}"
echo ""
echo "  Open: http://localhost:${BACKEND_PORT}"
echo ""
echo "  Backend hot reload enabled."
echo "  Frontend changes require re-run."
echo "  Press Ctrl+C to stop"
echo "=========================================="

# Wait for backend process
wait $BACKEND_PID
