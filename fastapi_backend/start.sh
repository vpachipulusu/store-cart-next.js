#!/bin/bash

# KAN-167: BACKEND_PORT (default 8000) lets a second checkout run its backend in parallel.
BACKEND_PORT="${BACKEND_PORT:-8000}"

if [ -f /.dockerenv ]; then
    echo "Running in Docker"
    fastapi dev app/main.py --host 0.0.0.0 --port "$BACKEND_PORT" --reload &
    python watcher.py
else
    echo "Running locally with uv"
    uv run fastapi dev app/main.py --host 0.0.0.0 --port "$BACKEND_PORT" --reload &
    uv run python watcher.py
fi

wait
