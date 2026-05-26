#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Prefer compose if a provider (docker-compose or podman-compose) is present; otherwise fallback to podman run.
if command -v docker-compose >/dev/null 2>&1 || command -v podman-compose >/dev/null 2>&1; then
  podman compose -f docker-compose.yml up -d
else
  echo "[pg-up] No compose provider found; using plain 'podman run' fallback"
  # Ensure named volume exists
  if ! podman volume ls --format '{{.Name}}' | grep -qx 'pgdata'; then
    podman volume create pgdata >/dev/null
  fi
  # If container exists, (re)start it; else run new
  if podman ps -a --format '{{.Names}}' | grep -qx 'thodarudai-postgres'; then
    podman start thodarudai-postgres >/dev/null
  else
    INITDB_DIR="$(pwd)/initdb"
    podman run -d --name thodarudai-postgres \
      -e POSTGRES_DB=thodarudai \
      -e POSTGRES_USER=thodarudai \
      -e POSTGRES_PASSWORD=thodarudai \
      -p 127.0.0.1:5432:5432 \
      -v pgdata:/var/lib/postgresql/data \
      -v "${INITDB_DIR}:/docker-entrypoint-initdb.d:ro,Z" \
      postgres:16
  fi
fi
  # Wait for Postgres readiness
  echo -n "[pg-up] waiting for Postgres to be ready"
  for i in $(seq 1 ${PG_WAIT_SECS:-60}); do
    if podman exec thodarudai-postgres pg_isready -U thodarudai -d thodarudai -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
      echo " - ready"
      break
    fi
    sleep 1; echo -n "."
    if [[ "$i" -eq "${PG_WAIT_SECS:-60}" ]]; then
      echo
      echo "[pg-up] Postgres not ready after ${PG_WAIT_SECS:-60}s; recent logs:"
      podman logs thodarudai-postgres | tail -n 100 || true
      exit 1
    fi
  done
echo "Postgres is starting on 127.0.0.1:5432 (container: thodarudai-postgres)"
echo "DSN: postgresql://thodarudai:thodarudai@127.0.0.1:5432/thodarudai"
echo "psql client (no local install needed): bash docker/postgres/psql.sh"
