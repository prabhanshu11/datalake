#!/usr/bin/env bash
# Run interactive query interface in container
set -euo pipefail

echo "Opening datalake query interface..."
docker-compose run --rm datalake ./scripts/query.sh
