#!/usr/bin/env bash
# Watch Claude session files for changes and trigger incremental refresh
# Uses inotifywait with debounce to avoid excessive parsing
#
# This gives near-real-time datalake updates: within DEBOUNCE_SECS of
# the last write to any session JSONL file, the parser runs.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
CLAUDE_DIR="${CLAUDE_DIR:-$HOME/.claude}"
PROJECTS_DIR="$CLAUDE_DIR/projects"
DEBOUNCE_SECS="${DEBOUNCE_SECS:-30}"
LOG_FILE="${LOG_FILE:-$PROJECT_ROOT/logs/watcher.log}"

# Source device role
DEVICE_CONFIG="$HOME/Programs/local-bootstrapping/device-role.conf"
DEVICE_NAME="unknown"
if [[ -f "$DEVICE_CONFIG" ]]; then
    source "$DEVICE_CONFIG"
fi

log() {
    echo "[$(date -Iseconds)] $*" | tee -a "$LOG_FILE"
}

mkdir -p "$(dirname "$LOG_FILE")"

log "Starting datalake watcher (debounce=${DEBOUNCE_SECS}s, device=${DEVICE_NAME})"
log "Watching: $PROJECTS_DIR for *.jsonl changes"

# Use inotifywait in monitor mode with a debounce pattern:
# - Watch for close_write events on .jsonl files (Claude flushes after each message)
# - Use timeout-based debounce: after detecting a change, wait DEBOUNCE_SECS
#   for more changes before triggering the parser
LAST_REFRESH=0

inotifywait -m -r -e close_write --include '\.jsonl$' "$PROJECTS_DIR" 2>/dev/null |
while read -r dir event file; do
    NOW=$(date +%s)
    SINCE_LAST=$((NOW - LAST_REFRESH))

    # Debounce: only refresh if enough time has passed since last refresh
    if [[ $SINCE_LAST -ge $DEBOUNCE_SECS ]]; then
        log "Change detected: $file (${SINCE_LAST}s since last refresh)"
        # Small delay to batch rapid writes
        sleep 5
        log "Running incremental refresh..."
        if python3 "$PROJECT_ROOT/parsers/claude_parser.py" --device "$DEVICE_NAME" 2>&1 | tee -a "$LOG_FILE"; then
            LAST_REFRESH=$(date +%s)
            log "Refresh complete"
        else
            log "ERROR: Refresh failed"
        fi
    fi
done
