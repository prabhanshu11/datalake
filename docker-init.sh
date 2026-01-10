#!/usr/bin/env bash
# Initialize datalake database in Docker container
set -euo pipefail

echo "Initializing datalake in container..."
docker-compose run --rm datalake ./scripts/init.sh

echo ""
echo "Database initialized successfully!"
echo "You can now ingest files using: ./docker-ingest.sh <file> [tags]"
