#!/usr/bin/env bash
set -euo pipefail

OUTAGE_SECONDS="${1:-60}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
  PY="$REPO_ROOT/.venv/bin/python"
elif [ -x "$REPO_ROOT/collector-security/.venv/bin/python" ]; then
  PY="$REPO_ROOT/collector-security/.venv/bin/python"
else
  PY="python3"
fi

echo "=== [1] Collector status BEFORE outage ==="
PYTHONPATH=collector-security "$PY" -m collector.cli status

echo "=== [2] Stopping backend container (if running) for ${OUTAGE_SECONDS}s ==="
if command -v docker >/dev/null 2>&1 && docker compose ps --services --filter "status=running" 2>/dev/null | grep -qx "backend"; then
  docker compose stop backend
  BACKEND_STOPPED=1
else
  echo "Backend container is not currently running under docker compose; simulating outage locally."
  BACKEND_STOPPED=0
fi

echo "=== [3] Generating telemetry during outage window (${OUTAGE_SECONDS}s) ==="
PYTHONPATH=collector-security "$PY" -m collector.cli generate --mode normal --duration "${OUTAGE_SECONDS}" --transmit || true

echo "=== [4] Collector status DURING outage ==="
PYTHONPATH=collector-security "$PY" -m collector.cli status

if [ "$BACKEND_STOPPED" -eq 1 ]; then
  echo "=== [5] Starting backend container and waiting 15s for backlog drain ==="
  docker compose start backend
  sleep 15
fi

echo "=== [6] Collector status AFTER recovery ==="
PYTHONPATH=collector-security "$PY" -m collector.cli status

if [ "$BACKEND_STOPPED" -eq 1 ]; then
  echo "=== [7] Duplicate payload_id check in PostgreSQL (expected: 0 rows) ==="
  docker compose exec -T postgres psql -U "${POSTGRES_USER:-obs_user}" -d "${POSTGRES_DB:-observability}" \
    -c "SELECT payload_id, COUNT(*) FROM telemetry_metadata GROUP BY payload_id HAVING COUNT(*) > 1;" || true
fi

echo "Outage drill finished. Record measured counts and timestamps in FINAL_QUALITY_REPORT.md."
