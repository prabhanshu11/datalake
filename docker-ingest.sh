#!/usr/bin/env bash
# Ingest audio file into containerized datalake
set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: $0 <audio_file> [tags]"
    echo ""
    echo "Example:"
    echo "  $0 recording.wav \"meeting,important\""
    exit 1
fi

AUDIO_FILE="$1"
TAGS="${2:-}"

if [ ! -f "$AUDIO_FILE" ]; then
    echo "Error: File not found: $AUDIO_FILE"
    exit 1
fi

# Get absolute path
AUDIO_PATH="$(realpath "$AUDIO_FILE")"
AUDIO_NAME="$(basename "$AUDIO_FILE")"

echo "Ingesting: $AUDIO_NAME"

# Copy file into container and ingest
docker-compose run --rm \
    -v "$AUDIO_PATH:/tmp/$AUDIO_NAME:ro" \
    datalake \
    ./scripts/ingest-audio.sh "/tmp/$AUDIO_NAME" "$TAGS"

echo "Ingestion complete!"
