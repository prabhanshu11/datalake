#!/usr/bin/env bash
# Run tests in Docker container
set -euo pipefail

echo "Running tests in container..."
docker-compose run --rm datalake /usr/local/bin/uv run pytest -v "$@"
