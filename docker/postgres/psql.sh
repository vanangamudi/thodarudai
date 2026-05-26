#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

CONTAINER="${PG_CONTAINER:-thodarudai-postgres}"
DB="${PGDATABASE:-thodarudai}"
USER="${PGUSER:-thodarudai}"
HOST="${PGHOST:-127.0.0.1}"
PORT="${PGPORT:-5432}"
PASS="${PGPASSWORD:-thodarudai}"

if podman ps -a --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  # Wait up to 30s for readiness
  for i in $(seq 1 ${PG_WAIT_SECS:-30}); do
    if podman exec "$CONTAINER" pg_isready -U "$USER" -d "$DB" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  exec podman exec -e PGPASSWORD="$PASS" -it "$CONTAINER" \
    psql -U "$USER" -d "$DB"
else
  # Fallback: run an ephemeral psql client container against host-exposed DB
  echo "[psql] Container '$CONTAINER' not found; using ephemeral client container"
  exec podman run --rm -it --network host \
    -e PGPASSWORD="$PASS" docker.io/library/postgres:16 \
    psql -h "$HOST" -p "$PORT" -U "$USER" -d "$DB"
fi
