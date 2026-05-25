#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
podman compose -f docker-compose.yml up -d
echo "Postgres is starting on 127.0.0.1:5432 (container: thodarudai-postgres)"
echo "DSN: postgresql://thodarudai:thodarudai@127.0.0.1:5432/thodarudai"
