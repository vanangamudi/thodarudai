#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ "${PGCLEAN:-0}" == "1" ]]; then
  podman compose -f docker-compose.yml down --volumes
else
  podman compose -f docker-compose.yml down
fi
echo "Postgres stopped. To also remove the data volume: PGCLEAN=1 \$0"
