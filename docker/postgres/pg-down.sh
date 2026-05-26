#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if command -v docker-compose >/dev/null 2>&1 || command -v podman-compose >/dev/null 2>&1; then
  if [[ "${PGCLEAN:-0}" == "1" ]]; then
    podman compose -f docker-compose.yml down --volumes
  else
    podman compose -f docker-compose.yml down
  fi
else
  echo "[pg-down] No compose provider found; stopping single container"
  if podman ps -a --format '{{.Names}}' | grep -qx 'thodarudai-postgres'; then
    podman rm -f thodarudai-postgres >/dev/null || true
  fi
  if [[ "${PGCLEAN:-0}" == "1" ]]; then
    podman volume rm -f pgdata >/dev/null || true
  fi
fi
echo "Postgres stopped. To also remove the data volume: PGCLEAN=1 \$0"
