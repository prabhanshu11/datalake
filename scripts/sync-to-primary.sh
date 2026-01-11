#!/usr/bin/env bash
# Sync local datalake to primary (laptop) database
# Uses SQLite attach to merge data without duplicates

set -euo pipefail

# Configuration
PROJECT_ROOT="${PROJECT_ROOT:-$(dirname "$(dirname "$(readlink -f "$0")")")}"
LOCAL_DB="${LOCAL_DB:-$PROJECT_ROOT/datalake.db}"
LOG_DIR="${LOG_DIR:-$PROJECT_ROOT/logs}"
REMOTE_HOST="${REMOTE_HOST:-prabhanshu@100.103.8.87}"
REMOTE_DB="${REMOTE_DB:-~/Programs/datalake/datalake.db}"
LOCAL_DEVICE="${LOCAL_DEVICE:-$(hostname | tr '[:upper:]' '[:lower:]')}"

log() {
    echo "[$(date -Iseconds)] [INFO] $*" | tee -a "$LOG_DIR/sync.log"
}

error() {
    echo "[$(date -Iseconds)] [ERROR] $*" | tee -a "$LOG_DIR/sync.log" >&2
}

mkdir -p "$LOG_DIR"

log "Starting sync from $LOCAL_DEVICE to primary"
log "Local DB: $LOCAL_DB"
log "Remote: $REMOTE_HOST:$REMOTE_DB"

# Check local database
if [[ ! -f "$LOCAL_DB" ]]; then
    error "Local database not found: $LOCAL_DB"
    exit 1
fi

# Check remote connectivity
if ! ssh -o ConnectTimeout=5 "$REMOTE_HOST" "test -f $REMOTE_DB"; then
    error "Cannot connect to remote or remote DB not found"
    exit 1
fi

# Create temp directory for sync
SYNC_DIR=$(mktemp -d)
trap "rm -rf $SYNC_DIR" EXIT

log "Exporting local data..."

# Export data to CSV for transfer (more portable than SQLite dump)
sqlite3 -header -csv "$LOCAL_DB" "
SELECT * FROM claude_history WHERE source_device = '$LOCAL_DEVICE';
" > "$SYNC_DIR/claude_history.csv"

sqlite3 -header -csv "$LOCAL_DB" "
SELECT * FROM claude_sessions WHERE source_device = '$LOCAL_DEVICE';
" > "$SYNC_DIR/claude_sessions.csv"

sqlite3 -header -csv "$LOCAL_DB" "
SELECT cm.* FROM claude_messages cm
JOIN claude_sessions cs ON cm.session_id = cs.id
WHERE cs.source_device = '$LOCAL_DEVICE';
" > "$SYNC_DIR/claude_messages.csv"

# Count records
HISTORY_COUNT=$(wc -l < "$SYNC_DIR/claude_history.csv" | tr -d ' ')
SESSIONS_COUNT=$(wc -l < "$SYNC_DIR/claude_sessions.csv" | tr -d ' ')
MESSAGES_COUNT=$(wc -l < "$SYNC_DIR/claude_messages.csv" | tr -d ' ')

log "Exported: history=$((HISTORY_COUNT-1)), sessions=$((SESSIONS_COUNT-1)), messages=$((MESSAGES_COUNT-1))"

# Transfer and import on remote
log "Transferring to remote..."
scp -q "$SYNC_DIR"/*.csv "$REMOTE_HOST:/tmp/datalake_sync/"

log "Importing on remote..."
ssh "$REMOTE_HOST" "
cd ~/Programs/datalake

# Import history (skip duplicates based on session_id + timestamp_unix)
sqlite3 datalake.db \".mode csv\" \".import --skip 1 /tmp/datalake_sync/claude_history.csv claude_history_import\"
sqlite3 datalake.db \"
    INSERT OR IGNORE INTO claude_history
    (session_id, display, pasted_contents, project, source_device, timestamp, timestamp_unix)
    SELECT session_id, display, pasted_contents, project, source_device, timestamp, timestamp_unix
    FROM claude_history_import
    WHERE NOT EXISTS (
        SELECT 1 FROM claude_history ch
        WHERE ch.session_id = claude_history_import.session_id
        AND ch.timestamp_unix = claude_history_import.timestamp_unix
    );
    DROP TABLE IF EXISTS claude_history_import;
\"

# Import sessions (skip duplicates based on session_id)
sqlite3 datalake.db \".mode csv\" \".import --skip 1 /tmp/datalake_sync/claude_sessions.csv claude_sessions_import\"
sqlite3 datalake.db \"
    INSERT OR IGNORE INTO claude_sessions
    (session_id, project_path, project_encoded, summary, model_primary, claude_version,
     git_branch, total_messages, user_messages, assistant_messages, total_input_tokens,
     total_output_tokens, total_cache_read_tokens, total_cache_creation_tokens,
     source_device, source_file, started_at, ended_at, duration_seconds)
    SELECT session_id, project_path, project_encoded, summary, model_primary, claude_version,
           git_branch, total_messages, user_messages, assistant_messages, total_input_tokens,
           total_output_tokens, total_cache_read_tokens, total_cache_creation_tokens,
           source_device, source_file, started_at, ended_at, duration_seconds
    FROM claude_sessions_import
    WHERE session_id NOT IN (SELECT session_id FROM claude_sessions);
    DROP TABLE IF EXISTS claude_sessions_import;
\"

# Clean up
rm -rf /tmp/datalake_sync
"

# Log sync event
START_TIME=$(date -Iseconds)
sqlite3 "$LOCAL_DB" "
INSERT INTO sync_log (source_device, target_device, sync_type, started_at, completed_at, status)
VALUES ('$LOCAL_DEVICE', 'laptop', 'incremental', '$START_TIME', datetime('now'), 'success');
"

log "Sync complete!"

# Show remote stats
log "Remote database stats:"
ssh "$REMOTE_HOST" "sqlite3 ~/Programs/datalake/datalake.db \"
SELECT 'History: ' || COUNT(*) FROM claude_history;
SELECT 'Sessions: ' || COUNT(*) FROM claude_sessions;
SELECT 'Messages: ' || COUNT(*) FROM claude_messages;
SELECT 'Devices: ' || GROUP_CONCAT(DISTINCT source_device) FROM claude_sessions;
\""
