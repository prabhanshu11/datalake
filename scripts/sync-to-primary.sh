#!/usr/bin/env bash
# Sync local datalake to primary (laptop) database
#
# Default (SYNC_MODE=incremental): export only the rows inserted since the last
# successful sync (AUTOINCREMENT-id watermark) into a small delta DB, scp it, and
# merge it on the primary with the same ATTACH/INSERT rules as before. FTS5 stays
# consistent through the primary's AFTER INSERT triggers. Megabytes per tick.
# First run / lost watermark: reconcile against the primary's keys (session_ids,
# message_uuids, newest history timestamp) - exact, a few MB once.
#
# SYNC_MODE=full is the old path (VACUUM INTO the whole 23 GB DB + scp it). It halved
# the star-trek-camera tracker's cycle rate on the desktop for 1.5-2.7 h per tick
# (star-trek-camera docs/night-1002/datalake-incr-REPORT.md). Manual use only.
#
# Env: SYNC_MODE=incremental|full  DRY_RUN=1 (merge rolled back, watermark kept)
#      SYNC_RECONCILE=1 (ignore the watermark, reconcile against the primary)

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

# Helper: run sqlite3 with busy timeout (other processes may hold locks)
sq() {
    sqlite3 -cmd ".timeout 60000" "$@"
}

SYNC_MODE="${SYNC_MODE:-incremental}"
DRY_RUN="${DRY_RUN:-0}"
STATE_DIR="${STATE_DIR:-$HOME/.cache/datalake}"
DELTA_PY="$PROJECT_ROOT/scripts/sync_delta.py"
WATERMARK="$STATE_DIR/sync-watermark-$LOCAL_DEVICE.json"
REMOTE_PY_DB="${REMOTE_DB}"
mkdir -p "$STATE_DIR"

# Low priority for everything this script runs locally (the camera tracker shares the box)
lowprio() { nice -n19 ionice -c3 "$@"; }

DELTA_DB="$STATE_DIR/datalake_sync_delta.db"
KEYS_DB="$STATE_DIR/datalake_sync_keys.db"

incremental_sync() {
    trap 'rm -f "$DELTA_DB" "$DELTA_DB-journal" "$KEYS_DB"' EXIT
    local t0 export_json rows dry_flag="" merge_json
    t0=$(date +%s.%N)

    local export_args=(export --db "$LOCAL_DB" --device "$LOCAL_DEVICE" --out "$DELTA_DB")
    if [[ -f "$WATERMARK" && "${SYNC_RECONCILE:-0}" != "1" ]]; then
        log "Watermark: $(cat "$WATERMARK")"
        export_args+=(--watermark-file "$WATERMARK")
    else
        log "No watermark (or SYNC_RECONCILE=1): reconciling against the primary's keys"
        ssh "$REMOTE_HOST" "mkdir -p ~/.cache/datalake && python3 - keys --db $REMOTE_PY_DB --device $LOCAL_DEVICE --out ~/.cache/datalake/datalake_sync_keys.db" < "$DELTA_PY" | tee -a "$LOG_DIR/sync.log"
        scp -q -C "$REMOTE_HOST:.cache/datalake/datalake_sync_keys.db" "$KEYS_DB"
        ssh "$REMOTE_HOST" 'rm -f ~/.cache/datalake/datalake_sync_keys.db'
        log "Keys fetched ($(du -h "$KEYS_DB" | cut -f1))"
        export_args+=(--keys "$KEYS_DB")
    fi

    export_json=$(lowprio python3 "$DELTA_PY" "${export_args[@]}")
    log "Export: $export_json"
    rows=$(python3 -c 'import json,sys; print(sum(json.loads(sys.argv[1])["rows"].values()))' "$export_json")

    if [[ "$rows" -gt 0 ]]; then
        log "Transferring delta ($(du -h "$DELTA_DB" | cut -f1), $rows rows)..."
        ssh "$REMOTE_HOST" 'mkdir -p ~/.cache/datalake'
        scp -q -C "$DELTA_DB" "$REMOTE_HOST:.cache/datalake/datalake_sync_delta.db"
        [[ "$DRY_RUN" == "1" ]] && dry_flag="--dry-run"
        merge_json=$(ssh "$REMOTE_HOST" "python3 - merge --db $REMOTE_PY_DB --delta ~/.cache/datalake/datalake_sync_delta.db --device $LOCAL_DEVICE $dry_flag; rc=\$?; rm -f ~/.cache/datalake/datalake_sync_delta.db; exit \$rc" < "$DELTA_PY")
        log "Merge: $merge_json"
    else
        log "Nothing new since the watermark; no transfer"
    fi

    if [[ "$DRY_RUN" == "1" ]]; then
        log "DRY_RUN=1: watermark not advanced"
    else
        python3 -c 'import json,sys; print(json.dumps(json.loads(sys.argv[1])["watermark"]))' "$export_json" > "$WATERMARK.tmp"
        mv "$WATERMARK.tmp" "$WATERMARK"
        sq "$LOCAL_DB" "
INSERT INTO sync_log (source_device, target_device, sync_type, records_synced, started_at, completed_at, status, metadata)
VALUES ('$LOCAL_DEVICE', 'laptop', 'incremental', $rows, datetime($t0, 'unixepoch'), datetime('now'), 'success', '$(echo "$export_json" | tr -d "'")');
" 2>/dev/null || true
    fi
    log "Sync complete! (incremental, $rows rows, $(python3 -c "import time; print(round(time.time()-$t0, 1))") s)"
}

if [[ "$SYNC_MODE" == "incremental" ]]; then
    incremental_sync
    exit 0
fi

log "SYNC_MODE=$SYNC_MODE: old full path (VACUUM INTO the whole DB + scp)"
# Count local records to sync
log "Counting local records..."
LOCAL_STATS=$(sq "$LOCAL_DB" "
SELECT
    (SELECT COUNT(*) FROM claude_history WHERE source_device = '$LOCAL_DEVICE') as history,
    (SELECT COUNT(*) FROM claude_sessions WHERE source_device = '$LOCAL_DEVICE') as sessions,
    (SELECT COUNT(*) FROM claude_messages cm
     JOIN claude_sessions cs ON cm.session_id = cs.id
     WHERE cs.source_device = '$LOCAL_DEVICE') as messages;
")
log "Local records: $LOCAL_STATS"

# Create a consistent snapshot using VACUUM INTO
# This creates an atomic, consistent copy even with concurrent writers.
# Raw scp of a DB with active writers produces a corrupt copy
# because the -journal file is not included.
# On disk, NOT /tmp: /tmp is a 16 GB tmpfs with a user quota on both machines and the
# DB is >20 GB. A partial 13 GB snapshot in /tmp blocked every other /tmp writer on the
# desktop on 2026-09-11 (local-bootstrapping sync validation failed on it).
SNAPSHOT_DIR="${HOME}/.cache/datalake"
mkdir -p "$SNAPSHOT_DIR"
SNAPSHOT="$SNAPSHOT_DIR/datalake_sync_snapshot.db"
trap 'rm -f "$SNAPSHOT"' EXIT
log "Creating consistent snapshot via VACUUM INTO..."
rm -f "$SNAPSHOT"
sq "$LOCAL_DB" "VACUUM INTO '$SNAPSHOT';"

# Verify snapshot integrity before transferring
if ! sqlite3 "$SNAPSHOT" "PRAGMA integrity_check;" | grep -q "^ok$"; then
    error "Snapshot failed integrity check, aborting"
    rm -f "$SNAPSHOT"
    exit 1
fi
log "Snapshot OK ($(du -h "$SNAPSHOT" | cut -f1))"

# Transfer snapshot to remote
log "Transferring snapshot to remote..."
ssh "$REMOTE_HOST" 'mkdir -p ~/.cache/datalake'
scp -q "$SNAPSHOT" "$REMOTE_HOST:$HOME/.cache/datalake/datalake_sync_source.db"
rm -f "$SNAPSHOT"

log "Merging on remote using ATTACH..."
ssh "$REMOTE_HOST" 'set -e
sqlite3 ~/Programs/datalake/datalake.db "
-- Attach source database
ATTACH DATABASE '\''"$HOME"/.cache/datalake/datalake_sync_source.db'\'' AS source;

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
rm -f $HOME/.cache/datalake/datalake_sync_source.db
'

# Log sync event
START_TIME=$(date -Iseconds)
sq "$LOCAL_DB" "
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
