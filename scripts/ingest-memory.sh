#!/usr/bin/env bash
# ingest-memory.sh - Ingest Claude memory monitoring data from desktop
#
# This script:
# 1. SSHs to the desktop (100.92.71.80)
# 2. Reads /var/log/claude-memory/metrics.jsonl and events.jsonl
# 3. Pipes the data to memory_parser.py for ingestion
#
# Usage: ./scripts/ingest-memory.sh [--once|--watch]
#   --once   Run once and exit (default)
#   --watch  Run continuously every 30 seconds

set -euo pipefail

# Configuration
DESKTOP_HOST="100.92.71.80"
DESKTOP_USER="prabhanshu"
REMOTE_LOG_DIR="/var/log/claude-memory"
LOCAL_DB="${DATALAKE_DB:-$HOME/Programs/datalake/datalake.db}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_FILE="$PROJECT_DIR/logs/ingest-memory.log"

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

log() {
    echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] $*" | tee -a "$LOG_FILE"
}

check_remote_logs() {
    log "Checking for remote log files..."

    if ssh "$DESKTOP_USER@$DESKTOP_HOST" "test -d '$REMOTE_LOG_DIR'" 2>/dev/null; then
        log "Remote log directory exists: $REMOTE_LOG_DIR"

        # Check individual files
        local metrics_exists events_exists
        metrics_exists=$(ssh "$DESKTOP_USER@$DESKTOP_HOST" "test -f '$REMOTE_LOG_DIR/metrics.jsonl' && echo 1 || echo 0")
        events_exists=$(ssh "$DESKTOP_USER@$DESKTOP_HOST" "test -f '$REMOTE_LOG_DIR/events.jsonl' && echo 1 || echo 0")

        log "  metrics.jsonl: $([ "$metrics_exists" = "1" ] && echo 'exists' || echo 'missing')"
        log "  events.jsonl: $([ "$events_exists" = "1" ] && echo 'exists' || echo 'missing')"

        return 0
    else
        log "Remote log directory does not exist yet: $REMOTE_LOG_DIR"
        log "Waiting for claude-memory-monitor service to be deployed..."
        return 1
    fi
}

ingest_once() {
    log "Starting memory ingestion..."

    # Check if remote logs exist
    if ! check_remote_logs; then
        log "Skipping ingestion - logs not available yet"
        return 0
    fi

    # Create a temporary directory for the remote files
    local tmpdir
    tmpdir=$(mktemp -d)
    trap "rm -rf '$tmpdir'" EXIT

    # Copy files from remote
    log "Copying log files from desktop..."
    scp -q "$DESKTOP_USER@$DESKTOP_HOST:$REMOTE_LOG_DIR/metrics.jsonl" "$tmpdir/" 2>/dev/null || true
    scp -q "$DESKTOP_USER@$DESKTOP_HOST:$REMOTE_LOG_DIR/events.jsonl" "$tmpdir/" 2>/dev/null || true

    # Run parser
    log "Running memory parser..."
    python3 "$PROJECT_DIR/parsers/memory_parser.py" \
        --log-dir "$tmpdir" \
        --device "desktop" \
        --db "$LOCAL_DB"

    log "Ingestion complete"
}

watch_mode() {
    log "Starting watch mode (every 30 seconds)..."

    while true; do
        ingest_once
        log "Sleeping for 30 seconds..."
        sleep 30
    done
}

show_help() {
    cat << EOF
Usage: $0 [OPTIONS]

Ingest Claude memory monitoring data from desktop into datalake.

Options:
  --once    Run ingestion once and exit (default)
  --watch   Run continuously every 30 seconds
  --check   Only check if remote logs exist
  --help    Show this help message

Environment:
  DATALAKE_DB   Path to datalake database (default: ~/Programs/datalake/datalake.db)

Remote Configuration:
  Host: $DESKTOP_HOST
  User: $DESKTOP_USER
  Log dir: $REMOTE_LOG_DIR
EOF
}

# Main
case "${1:-once}" in
    --once|once)
        ingest_once
        ;;
    --watch|watch)
        watch_mode
        ;;
    --check|check)
        check_remote_logs
        ;;
    --help|-h|help)
        show_help
        ;;
    *)
        echo "Unknown option: $1"
        show_help
        exit 1
        ;;
esac
