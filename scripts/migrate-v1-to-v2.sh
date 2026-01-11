#!/usr/bin/env bash
# Migrate datalake from v1 to v2 schema
# Adds new columns to existing tables and creates new tables

set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$(dirname "$(dirname "$(readlink -f "$0")")")}"
DB_FILE="${DB_FILE:-$PROJECT_ROOT/datalake.db}"
LOG_DIR="${LOG_DIR:-$PROJECT_ROOT/logs}"

log() {
    echo "[$(date -Iseconds)] [INFO] $*" | tee -a "$LOG_DIR/migrate-v2.log"
}

mkdir -p "$LOG_DIR"

log "Migrating datalake to v2.0"
log "Database: $DB_FILE"

# Check current version
CURRENT_VERSION=$(sqlite3 "$DB_FILE" "SELECT value FROM metadata WHERE key='schema_version';" 2>/dev/null || echo "1.0.0")
log "Current version: $CURRENT_VERSION"

if [[ "$CURRENT_VERSION" == "2.0.0" ]]; then
    log "Already at v2.0.0, skipping migration"
    exit 0
fi

# Add source_device column to existing tables if not exists
log "Adding source_device columns..."

sqlite3 "$DB_FILE" "
-- Add columns to audio table
ALTER TABLE audio ADD COLUMN source_device TEXT;
ALTER TABLE audio ADD COLUMN source_project TEXT;
" 2>/dev/null || log "audio columns may already exist"

sqlite3 "$DB_FILE" "
-- Add columns to transcripts table
ALTER TABLE transcripts ADD COLUMN source_device TEXT;
" 2>/dev/null || log "transcripts columns may already exist"

sqlite3 "$DB_FILE" "
-- Add columns to screenshots table
ALTER TABLE screenshots ADD COLUMN source_device TEXT;
" 2>/dev/null || log "screenshots columns may already exist"

# Create all new v2 tables
log "Creating new v2 tables..."

sqlite3 "$DB_FILE" "
-- Claude Code sessions (conversations)
CREATE TABLE IF NOT EXISTS claude_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    project_path TEXT NOT NULL,
    project_encoded TEXT,
    summary TEXT,
    model_primary TEXT,
    claude_version TEXT,
    git_branch TEXT,
    total_messages INTEGER DEFAULT 0,
    user_messages INTEGER DEFAULT 0,
    assistant_messages INTEGER DEFAULT 0,
    total_input_tokens INTEGER DEFAULT 0,
    total_output_tokens INTEGER DEFAULT 0,
    total_cache_read_tokens INTEGER DEFAULT 0,
    total_cache_creation_tokens INTEGER DEFAULT 0,
    source_device TEXT NOT NULL,
    source_file TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_seconds REAL,
    tags TEXT,
    rating INTEGER CHECK (rating >= 1 AND rating <= 10),
    rating_notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT
);

-- Claude Code messages
CREATE TABLE IF NOT EXISTS claude_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    message_uuid TEXT NOT NULL UNIQUE,
    parent_uuid TEXT,
    message_type TEXT NOT NULL,
    user_type TEXT,
    role TEXT,
    model TEXT,
    content_text TEXT,
    content_thinking TEXT,
    content_images INTEGER DEFAULT 0,
    content_tool_uses INTEGER DEFAULT 0,
    content_tool_results INTEGER DEFAULT 0,
    is_sidechain INTEGER DEFAULT 0,
    cwd TEXT,
    git_branch TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_read_tokens INTEGER,
    cache_creation_tokens INTEGER,
    stop_reason TEXT,
    request_id TEXT,
    timestamp TEXT NOT NULL,
    sequence_number INTEGER,
    todos TEXT,
    rating INTEGER CHECK (rating >= 1 AND rating <= 10),
    rating_notes TEXT,
    metadata TEXT,
    FOREIGN KEY (session_id) REFERENCES claude_sessions(id) ON DELETE CASCADE
);

-- Claude Code subagents
CREATE TABLE IF NOT EXISTS claude_subagents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_session_id INTEGER NOT NULL,
    subagent_id TEXT NOT NULL,
    subagent_type TEXT,
    description TEXT,
    source_file TEXT,
    total_messages INTEGER DEFAULT 0,
    started_at TEXT,
    ended_at TEXT,
    metadata TEXT,
    FOREIGN KEY (parent_session_id) REFERENCES claude_sessions(id) ON DELETE CASCADE
);

-- Claude Code history entries
CREATE TABLE IF NOT EXISTS claude_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    display TEXT NOT NULL,
    pasted_contents TEXT,
    project TEXT NOT NULL,
    source_device TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    timestamp_unix INTEGER,
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Voice typing sessions
CREATE TABLE IF NOT EXISTS voice_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audio_id INTEGER,
    transcript_id INTEGER,
    session_uuid TEXT,
    trigger_type TEXT,
    trigger_timestamp TEXT,
    recording_start TEXT,
    recording_end TEXT,
    transcription_start TEXT,
    transcription_end TEXT,
    output_timestamp TEXT,
    success INTEGER DEFAULT 1,
    failure_reason TEXT,
    source_device TEXT NOT NULL,
    claude_session_id INTEGER,
    rating INTEGER CHECK (rating >= 1 AND rating <= 10),
    rating_notes TEXT,
    corrected_transcript TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT,
    FOREIGN KEY (audio_id) REFERENCES audio(id) ON DELETE SET NULL,
    FOREIGN KEY (transcript_id) REFERENCES transcripts(id) ON DELETE SET NULL,
    FOREIGN KEY (claude_session_id) REFERENCES claude_sessions(id) ON DELETE SET NULL
);

-- Voice typing events
CREATE TABLE IF NOT EXISTS voice_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    event_type TEXT NOT NULL,
    event_data TEXT,
    source_device TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    metadata TEXT,
    FOREIGN KEY (session_id) REFERENCES voice_sessions(id) ON DELETE CASCADE
);

-- Email accounts
CREATE TABLE IF NOT EXISTS email_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_address TEXT NOT NULL UNIQUE,
    provider TEXT DEFAULT 'gmail',
    display_name TEXT,
    last_sync_at TEXT,
    sync_token TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT
);

-- Email threads
CREATE TABLE IF NOT EXISTS email_threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id TEXT NOT NULL UNIQUE,
    account_id INTEGER NOT NULL,
    subject TEXT,
    snippet TEXT,
    message_count INTEGER DEFAULT 0,
    participant_count INTEGER DEFAULT 0,
    participants TEXT,
    labels TEXT,
    is_starred INTEGER DEFAULT 0,
    is_important INTEGER DEFAULT 0,
    is_unread INTEGER DEFAULT 0,
    first_message_at TEXT,
    last_message_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT,
    FOREIGN KEY (account_id) REFERENCES email_accounts(id) ON DELETE CASCADE
);

-- Email messages
CREATE TABLE IF NOT EXISTS email_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL UNIQUE,
    thread_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    from_address TEXT NOT NULL,
    from_name TEXT,
    to_addresses TEXT,
    cc_addresses TEXT,
    bcc_addresses TEXT,
    reply_to TEXT,
    subject TEXT,
    snippet TEXT,
    body_plain TEXT,
    body_html TEXT,
    labels TEXT,
    is_starred INTEGER DEFAULT 0,
    is_read INTEGER DEFAULT 1,
    is_draft INTEGER DEFAULT 0,
    is_sent INTEGER DEFAULT 0,
    has_attachments INTEGER DEFAULT 0,
    attachment_count INTEGER DEFAULT 0,
    size_bytes INTEGER,
    internal_date TEXT,
    received_at TEXT,
    sent_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT,
    FOREIGN KEY (thread_id) REFERENCES email_threads(id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES email_accounts(id) ON DELETE CASCADE
);

-- Email attachments
CREATE TABLE IF NOT EXISTS email_attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL,
    attachment_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    file_path TEXT,
    mime_type TEXT,
    size_bytes INTEGER,
    is_inline INTEGER DEFAULT 0,
    content_id TEXT,
    is_downloaded INTEGER DEFAULT 0,
    downloaded_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT,
    FOREIGN KEY (message_id) REFERENCES email_messages(id) ON DELETE CASCADE
);

-- Terminal sessions
CREATE TABLE IF NOT EXISTS terminal_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_uuid TEXT UNIQUE,
    window_title TEXT,
    working_directory TEXT,
    source_device TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_seconds REAL,
    line_count INTEGER DEFAULT 0,
    size_bytes INTEGER,
    associated_claude_session_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT,
    FOREIGN KEY (associated_claude_session_id) REFERENCES claude_sessions(id) ON DELETE SET NULL
);

-- Terminal output
CREATE TABLE IF NOT EXISTS terminal_output (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    chunk_number INTEGER NOT NULL,
    content TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    is_input INTEGER DEFAULT 0,
    metadata TEXT,
    FOREIGN KEY (session_id) REFERENCES terminal_sessions(id) ON DELETE CASCADE
);

-- Device registry
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_name TEXT NOT NULL UNIQUE,
    device_type TEXT,
    hostname TEXT,
    ip_address TEXT,
    tailscale_ip TEXT,
    last_seen_at TEXT,
    last_sync_at TEXT,
    sync_status TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT
);

-- Sync log
CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_device TEXT NOT NULL,
    target_device TEXT NOT NULL,
    sync_type TEXT NOT NULL,
    table_name TEXT,
    records_synced INTEGER DEFAULT 0,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT,
    error_message TEXT,
    metadata TEXT
);
"

# Create FTS tables
log "Creating FTS tables..."

sqlite3 "$DB_FILE" "
-- FTS for Claude messages
CREATE VIRTUAL TABLE IF NOT EXISTS claude_messages_fts USING fts5(
    content_text,
    content_thinking,
    content='claude_messages',
    content_rowid='id'
);

-- FTS for Claude history
CREATE VIRTUAL TABLE IF NOT EXISTS claude_history_fts USING fts5(
    display,
    content='claude_history',
    content_rowid='id'
);

-- FTS for email messages
CREATE VIRTUAL TABLE IF NOT EXISTS email_messages_fts USING fts5(
    subject,
    body_plain,
    from_address,
    from_name,
    content='email_messages',
    content_rowid='id'
);

-- FTS for terminal output
CREATE VIRTUAL TABLE IF NOT EXISTS terminal_output_fts USING fts5(
    content,
    content='terminal_output',
    content_rowid='id'
);
"

# Create indexes
log "Creating indexes..."

sqlite3 "$DB_FILE" "
-- Claude session indexes
CREATE INDEX IF NOT EXISTS idx_claude_sessions_session_id ON claude_sessions(session_id);
CREATE INDEX IF NOT EXISTS idx_claude_sessions_project ON claude_sessions(project_path);
CREATE INDEX IF NOT EXISTS idx_claude_sessions_started_at ON claude_sessions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_claude_sessions_source_device ON claude_sessions(source_device);

-- Claude message indexes
CREATE INDEX IF NOT EXISTS idx_claude_messages_session ON claude_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_claude_messages_uuid ON claude_messages(message_uuid);
CREATE INDEX IF NOT EXISTS idx_claude_messages_timestamp ON claude_messages(timestamp);

-- Claude history indexes
CREATE INDEX IF NOT EXISTS idx_claude_history_session ON claude_history(session_id);
CREATE INDEX IF NOT EXISTS idx_claude_history_timestamp ON claude_history(timestamp_unix DESC);

-- Voice session indexes
CREATE INDEX IF NOT EXISTS idx_voice_sessions_device ON voice_sessions(source_device);
CREATE INDEX IF NOT EXISTS idx_voice_sessions_created ON voice_sessions(created_at DESC);

-- Email indexes
CREATE INDEX IF NOT EXISTS idx_email_threads_account ON email_threads(account_id);
CREATE INDEX IF NOT EXISTS idx_email_messages_thread ON email_messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_email_messages_received ON email_messages(received_at DESC);

-- Terminal indexes
CREATE INDEX IF NOT EXISTS idx_terminal_sessions_device ON terminal_sessions(source_device);
CREATE INDEX IF NOT EXISTS idx_terminal_output_session ON terminal_output(session_id);
"

# Update schema version
sqlite3 "$DB_FILE" "INSERT OR REPLACE INTO metadata (key, value, updated_at) VALUES ('schema_version', '2.0.0', datetime('now'));"

# Show stats
TABLE_COUNT=$(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
log "Total tables: $TABLE_COUNT"

NEW_VERSION=$(sqlite3 "$DB_FILE" "SELECT value FROM metadata WHERE key='schema_version';")
log "New version: $NEW_VERSION"

log "Migration complete!"
