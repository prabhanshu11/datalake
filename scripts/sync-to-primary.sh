#!/usr/bin/env bash
# Sync local datalake to primary (laptop) database
# Uses SQLite ATTACH for robust binary-safe merging

set -euo pipefail

# Configuration
PROJECT_ROOT="${PROJECT_ROOT:-$(dirname "$(dirname "$(readlink -f "$0")")")}"
LOCAL_DB="${LOCAL_DB:-$PROJECT_ROOT/datalake.db}"
LOG_DIR="${LOG_DIR:-$PROJECT_ROOT/logs}"
REMOTE_HOST="${REMOTE_HOST:-prabhanshu@100.103.8.87}"
REMOTE_DB="${REMOTE_DB:-~/Programs/datalake/datalake.db}"

# Get device name from local-bootstrapping config or fall back to hostname
DEVICE_CONFIG="${DEVICE_CONFIG:-$HOME/Programs/local-bootstrapping/device-role.conf}"
if [[ -f "$DEVICE_CONFIG" ]]; then
    source "$DEVICE_CONFIG"
    LOCAL_DEVICE="${LOCAL_DEVICE:-$DEVICE_NAME}"
fi
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

# Count local records to sync
log "Counting local records..."
LOCAL_STATS=$(sqlite3 "$LOCAL_DB" "
SELECT
    (SELECT COUNT(*) FROM claude_history WHERE source_device = '$LOCAL_DEVICE') as history,
    (SELECT COUNT(*) FROM claude_sessions WHERE source_device = '$LOCAL_DEVICE') as sessions,
    (SELECT COUNT(*) FROM claude_messages cm
     JOIN claude_sessions cs ON cm.session_id = cs.id
     WHERE cs.source_device = '$LOCAL_DEVICE') as messages;
")
log "Local records: $LOCAL_STATS"

# Copy database to remote for ATTACH-based merge
log "Transferring database to remote..."
scp -q "$LOCAL_DB" "$REMOTE_HOST:/tmp/datalake_sync_source.db"

log "Merging on remote using ATTACH..."
ssh "$REMOTE_HOST" 'sqlite3 ~/Programs/datalake/datalake.db "
-- Attach source database
ATTACH DATABASE '\''/tmp/datalake_sync_source.db'\'' AS source;

-- Merge history (skip exact duplicates by session_id + timestamp_unix)
INSERT OR IGNORE INTO claude_history
    (session_id, display, pasted_contents, project, source_device, timestamp, timestamp_unix)
SELECT session_id, display, pasted_contents, project, source_device, timestamp, timestamp_unix
FROM source.claude_history sh
WHERE sh.source_device = '\''desktop'\''
  AND NOT EXISTS (
    SELECT 1 FROM claude_history ch
    WHERE ch.session_id = sh.session_id
      AND ch.timestamp_unix = sh.timestamp_unix
  );

-- Merge sessions (skip duplicates by session_id)
INSERT OR IGNORE INTO claude_sessions
    (session_id, project_path, project_encoded, summary, model_primary, claude_version,
     git_branch, total_messages, user_messages, assistant_messages, total_input_tokens,
     total_output_tokens, total_cache_read_tokens, total_cache_creation_tokens,
     source_device, source_file, started_at, ended_at, duration_seconds, created_at, ingested_at)
SELECT session_id, project_path, project_encoded, summary, model_primary, claude_version,
       git_branch, total_messages, user_messages, assistant_messages, total_input_tokens,
       total_output_tokens, total_cache_read_tokens, total_cache_creation_tokens,
       source_device, source_file, started_at, ended_at, duration_seconds, created_at, ingested_at
FROM source.claude_sessions ss
WHERE ss.source_device = '\''desktop'\''
  AND ss.session_id NOT IN (SELECT session_id FROM claude_sessions);

-- Merge messages (requires session to exist first)
-- Map source session_id to target session_id via session_uuid
INSERT OR IGNORE INTO claude_messages
    (session_id, message_uuid, parent_uuid, message_type, user_type, role, model,
     content_text, content_thinking, content_images, content_tool_uses, content_tool_results,
     is_sidechain, cwd, git_branch, input_tokens, output_tokens,
     cache_read_tokens, cache_creation_tokens, stop_reason, request_id,
     timestamp, sequence_number, todos, metadata)
SELECT
    (SELECT id FROM claude_sessions WHERE session_id = ss.session_id) as session_id,
    sm.message_uuid, sm.parent_uuid, sm.message_type, sm.user_type, sm.role, sm.model,
    sm.content_text, sm.content_thinking, sm.content_images, sm.content_tool_uses, sm.content_tool_results,
    sm.is_sidechain, sm.cwd, sm.git_branch, sm.input_tokens, sm.output_tokens,
    sm.cache_read_tokens, sm.cache_creation_tokens, sm.stop_reason, sm.request_id,
    sm.timestamp, sm.sequence_number, sm.todos, sm.metadata
FROM source.claude_messages sm
JOIN source.claude_sessions ss ON sm.session_id = ss.id
WHERE ss.source_device = '\''desktop'\''
  AND sm.message_uuid NOT IN (SELECT message_uuid FROM claude_messages WHERE message_uuid IS NOT NULL);

DETACH DATABASE source;
"

# Clean up
rm -f /tmp/datalake_sync_source.db
'

# Log sync event
START_TIME=$(date -Iseconds)
sqlite3 "$LOCAL_DB" "
INSERT INTO sync_log (source_device, target_device, sync_type, started_at, completed_at, status)
VALUES ('$LOCAL_DEVICE', 'laptop', 'incremental', '$START_TIME', datetime('now'), 'success');
" 2>/dev/null || true

log "Sync complete!"

# Show remote stats
log "Remote database stats after sync:"
ssh "$REMOTE_HOST" 'sqlite3 ~/Programs/datalake/datalake.db "
SELECT '\''History: '\'' || COUNT(*) FROM claude_history;
SELECT '\''Sessions: '\'' || COUNT(*) FROM claude_sessions;
SELECT '\''Messages: '\'' || COUNT(*) FROM claude_messages;
SELECT '\''Devices: '\'' || GROUP_CONCAT(DISTINCT source_device) FROM claude_sessions;
"'
