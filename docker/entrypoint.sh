#!/usr/bin/env sh
set -eu

if [ "${1:-}" = "api" ]; then
  alembic upgrade head
  python scripts/seed_demo.py
  exec uvicorn retailflow_orders.main:app --host 0.0.0.0 --port 8000
fi

exec "$@"
