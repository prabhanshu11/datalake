-- Datalake SQLite Schema v2.0.0
-- Extended schema for Claude Code conversations, voice typing, and email
-- Designed for fast queries with full-text search and proper indexing

-- ============================================================================
-- EXISTING TABLES (from v1.0.0) - Audio, Transcripts, Screenshots
-- ============================================================================

-- Audio recordings table (enhanced)
CREATE TABLE IF NOT EXISTS audio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL UNIQUE,  -- Relative path from data directory
    filename TEXT NOT NULL,
    original_filename TEXT,
    duration_seconds REAL,
    format TEXT,  -- e.g., 'wav', 'mp3', 'flac'
    sample_rate INTEGER,
    channels INTEGER,
    size_bytes INTEGER,
    tags TEXT,  -- JSON array or comma-separated tags
    source_device TEXT,  -- 'desktop', 'laptop', etc.
    source_project TEXT,  -- 'omarchy-voice-typing', 'recordings', etc.
    created_at TEXT NOT NULL,  -- ISO 8601 timestamp
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT  -- JSON for additional metadata
);

-- Transcripts table (enhanced)
CREATE TABLE IF NOT EXISTS transcripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL UNIQUE,
    filename TEXT NOT NULL,
    audio_id INTEGER,  -- Foreign key to audio table
    content TEXT NOT NULL,  -- Full transcript text
    word_count INTEGER,
    language TEXT,
    confidence REAL,  -- Transcription confidence score (0.0-1.0)
    provider TEXT,  -- e.g., 'assemblyai', 'whisper'
    size_bytes INTEGER,
    tags TEXT,
    source_device TEXT,
    created_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT,
    FOREIGN KEY (audio_id) REFERENCES audio(id) ON DELETE SET NULL
);

-- Screenshots table (unchanged)
CREATE TABLE IF NOT EXISTS screenshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL UNIQUE,
    filename TEXT NOT NULL,
    width INTEGER,
    height INTEGER,
    format TEXT,  -- e.g., 'png', 'jpg'
    size_bytes INTEGER,
    tags TEXT,
    source_device TEXT,
    created_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT
);

-- ============================================================================
-- CLAUDE CODE CONVERSATION TABLES
-- ============================================================================

-- Claude Code sessions (conversations)
CREATE TABLE IF NOT EXISTS claude_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,  -- UUID from Claude Code
    project_path TEXT NOT NULL,  -- e.g., '/home/prabhanshu/Programs'
    project_encoded TEXT,  -- e.g., '-home-prabhanshu-Programs'
    summary TEXT,  -- Auto-generated summary from Claude
    model_primary TEXT,  -- Primary model used (e.g., 'claude-opus-4-5-20251101')
    claude_version TEXT,  -- Claude Code version (e.g., '2.1.4')
    git_branch TEXT,
    total_messages INTEGER DEFAULT 0,
    user_messages INTEGER DEFAULT 0,
    assistant_messages INTEGER DEFAULT 0,
    total_input_tokens INTEGER DEFAULT 0,
    total_output_tokens INTEGER DEFAULT 0,
    total_cache_read_tokens INTEGER DEFAULT 0,
    total_cache_creation_tokens INTEGER DEFAULT 0,
    source_device TEXT NOT NULL,  -- 'desktop', 'laptop'
    source_file TEXT,  -- Path to source JSONL file
    started_at TEXT NOT NULL,  -- First message timestamp
    ended_at TEXT,  -- Last message timestamp
    duration_seconds REAL,
    tags TEXT,
    rating INTEGER CHECK (rating >= 1 AND rating <= 10),  -- 1-10 rating
    rating_notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT  -- JSON for additional metadata
);

-- Claude Code messages
CREATE TABLE IF NOT EXISTS claude_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    message_uuid TEXT NOT NULL UNIQUE,  -- UUID from Claude
    parent_uuid TEXT,  -- For conversation tree
    message_type TEXT NOT NULL,  -- 'user', 'assistant', 'summary', 'snapshot'
    user_type TEXT,  -- 'external', 'internal'
    role TEXT,  -- 'user', 'assistant'
    model TEXT,  -- Model used for this message
    content_text TEXT,  -- Extracted text content
    content_thinking TEXT,  -- Extracted thinking content
    content_images INTEGER DEFAULT 0,  -- Count of images in message
    content_tool_uses INTEGER DEFAULT 0,  -- Count of tool uses
    content_tool_results INTEGER DEFAULT 0,  -- Count of tool results
    is_sidechain INTEGER DEFAULT 0,  -- Boolean
    cwd TEXT,  -- Current working directory
    git_branch TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_read_tokens INTEGER,
    cache_creation_tokens INTEGER,
    stop_reason TEXT,
    request_id TEXT,  -- Anthropic request ID
    timestamp TEXT NOT NULL,
    sequence_number INTEGER,  -- Order in conversation
    todos TEXT,  -- JSON array of todos at this point
    rating INTEGER CHECK (rating >= 1 AND rating <= 10),
    rating_notes TEXT,
    metadata TEXT,  -- JSON for full original message
    FOREIGN KEY (session_id) REFERENCES claude_sessions(id) ON DELETE CASCADE
);

-- Claude Code subagents (Task tool spawns)
CREATE TABLE IF NOT EXISTS claude_subagents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_session_id INTEGER NOT NULL,
    subagent_id TEXT NOT NULL,  -- e.g., 'agent-a36d39a'
    subagent_type TEXT,  -- e.g., 'Explore', 'Bash', etc.
    description TEXT,
    source_file TEXT,
    total_messages INTEGER DEFAULT 0,
    started_at TEXT,
    ended_at TEXT,
    metadata TEXT,
    FOREIGN KEY (parent_session_id) REFERENCES claude_sessions(id) ON DELETE CASCADE
);

-- Claude Code history entries (from history.jsonl)
CREATE TABLE IF NOT EXISTS claude_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    display TEXT NOT NULL,  -- User's display text
    pasted_contents TEXT,  -- JSON of pasted content
    project TEXT NOT NULL,
    source_device TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    timestamp_unix INTEGER,
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Full-text search for Claude messages
CREATE VIRTUAL TABLE IF NOT EXISTS claude_messages_fts USING fts5(
    content_text,
    content_thinking,
    content='claude_messages',
    content_rowid='id'
);

-- FTS triggers for claude_messages
CREATE TRIGGER IF NOT EXISTS claude_messages_ai AFTER INSERT ON claude_messages BEGIN
    INSERT INTO claude_messages_fts(rowid, content_text, content_thinking)
    VALUES (new.id, new.content_text, new.content_thinking);
END;

CREATE TRIGGER IF NOT EXISTS claude_messages_ad AFTER DELETE ON claude_messages BEGIN
    DELETE FROM claude_messages_fts WHERE rowid = old.id;
END;

CREATE TRIGGER IF NOT EXISTS claude_messages_au AFTER UPDATE ON claude_messages BEGIN
    DELETE FROM claude_messages_fts WHERE rowid = old.id;
    INSERT INTO claude_messages_fts(rowid, content_text, content_thinking)
    VALUES (new.id, new.content_text, new.content_thinking);
END;

-- Full-text search for Claude history
CREATE VIRTUAL TABLE IF NOT EXISTS claude_history_fts USING fts5(
    display,
    content='claude_history',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS claude_history_ai AFTER INSERT ON claude_history BEGIN
    INSERT INTO claude_history_fts(rowid, display)
    VALUES (new.id, new.display);
END;

CREATE TRIGGER IF NOT EXISTS claude_history_ad AFTER DELETE ON claude_history BEGIN
    DELETE FROM claude_history_fts WHERE rowid = old.id;
END;

CREATE TRIGGER IF NOT EXISTS claude_history_au AFTER UPDATE ON claude_history BEGIN
    DELETE FROM claude_history_fts WHERE rowid = old.id;
    INSERT INTO claude_history_fts(rowid, display)
    VALUES (new.id, new.display);
END;

-- ============================================================================
-- VOICE TYPING SESSION TABLES
-- ============================================================================

-- Voice typing sessions (links audio + transcript + context)
CREATE TABLE IF NOT EXISTS voice_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audio_id INTEGER,
    transcript_id INTEGER,
    session_uuid TEXT,  -- UUID from transcript filename
    trigger_type TEXT,  -- 'keybinding', 'manual', 'api'
    trigger_timestamp TEXT,  -- When recording was triggered
    recording_start TEXT,
    recording_end TEXT,
    transcription_start TEXT,
    transcription_end TEXT,
    output_timestamp TEXT,  -- When text was output
    success INTEGER DEFAULT 1,  -- 0 = failed
    failure_reason TEXT,  -- If failed, why
    source_device TEXT NOT NULL,
    claude_session_id INTEGER,  -- If used within a Claude session
    rating INTEGER CHECK (rating >= 1 AND rating <= 10),
    rating_notes TEXT,
    corrected_transcript TEXT,  -- User's corrected version (feedback)
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT,
    FOREIGN KEY (audio_id) REFERENCES audio(id) ON DELETE SET NULL,
    FOREIGN KEY (transcript_id) REFERENCES transcripts(id) ON DELETE SET NULL,
    FOREIGN KEY (claude_session_id) REFERENCES claude_sessions(id) ON DELETE SET NULL
);

-- Voice typing events/logs
CREATE TABLE IF NOT EXISTS voice_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    event_type TEXT NOT NULL,  -- 'trigger', 'recording_start', 'recording_end', 'api_call', 'api_response', 'output', 'error'
    event_data TEXT,  -- JSON payload
    source_device TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    metadata TEXT,
    FOREIGN KEY (session_id) REFERENCES voice_sessions(id) ON DELETE CASCADE
);

-- ============================================================================
-- EMAIL (GMAIL) TABLES
-- ============================================================================

-- Email accounts
CREATE TABLE IF NOT EXISTS email_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_address TEXT NOT NULL UNIQUE,
    provider TEXT DEFAULT 'gmail',
    display_name TEXT,
    last_sync_at TEXT,
    sync_token TEXT,  -- For incremental sync
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT
);

-- Email threads (Gmail thread concept)
CREATE TABLE IF NOT EXISTS email_threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id TEXT NOT NULL UNIQUE,  -- Gmail thread ID
    account_id INTEGER NOT NULL,
    subject TEXT,
    snippet TEXT,  -- Preview text
    message_count INTEGER DEFAULT 0,
    participant_count INTEGER DEFAULT 0,
    participants TEXT,  -- JSON array of email addresses
    labels TEXT,  -- JSON array of labels
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
    message_id TEXT NOT NULL UNIQUE,  -- Gmail message ID
    thread_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    from_address TEXT NOT NULL,
    from_name TEXT,
    to_addresses TEXT,  -- JSON array
    cc_addresses TEXT,  -- JSON array
    bcc_addresses TEXT,  -- JSON array
    reply_to TEXT,
    subject TEXT,
    snippet TEXT,
    body_plain TEXT,  -- Plain text body
    body_html TEXT,  -- HTML body
    labels TEXT,  -- JSON array
    is_starred INTEGER DEFAULT 0,
    is_read INTEGER DEFAULT 1,
    is_draft INTEGER DEFAULT 0,
    is_sent INTEGER DEFAULT 0,
    has_attachments INTEGER DEFAULT 0,
    attachment_count INTEGER DEFAULT 0,
    size_bytes INTEGER,
    internal_date TEXT,  -- Gmail internal date
    received_at TEXT,
    sent_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT,  -- JSON for headers, etc.
    FOREIGN KEY (thread_id) REFERENCES email_threads(id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES email_accounts(id) ON DELETE CASCADE
);

-- Email attachments
CREATE TABLE IF NOT EXISTS email_attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL,
    attachment_id TEXT NOT NULL,  -- Gmail attachment ID
    filename TEXT NOT NULL,
    file_path TEXT,  -- Local path if downloaded
    mime_type TEXT,
    size_bytes INTEGER,
    is_inline INTEGER DEFAULT 0,
    content_id TEXT,  -- For inline attachments
    is_downloaded INTEGER DEFAULT 0,
    downloaded_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT,
    FOREIGN KEY (message_id) REFERENCES email_messages(id) ON DELETE CASCADE
);

-- Full-text search for emails
CREATE VIRTUAL TABLE IF NOT EXISTS email_messages_fts USING fts5(
    subject,
    body_plain,
    from_address,
    from_name,
    content='email_messages',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS email_messages_ai AFTER INSERT ON email_messages BEGIN
    INSERT INTO email_messages_fts(rowid, subject, body_plain, from_address, from_name)
    VALUES (new.id, new.subject, new.body_plain, new.from_address, new.from_name);
END;

CREATE TRIGGER IF NOT EXISTS email_messages_ad AFTER DELETE ON email_messages BEGIN
    DELETE FROM email_messages_fts WHERE rowid = old.id;
END;

CREATE TRIGGER IF NOT EXISTS email_messages_au AFTER UPDATE ON email_messages BEGIN
    DELETE FROM email_messages_fts WHERE rowid = old.id;
    INSERT INTO email_messages_fts(rowid, subject, body_plain, from_address, from_name)
    VALUES (new.id, new.subject, new.body_plain, new.from_address, new.from_name);
END;

-- ============================================================================
-- GHOSTTY TERMINAL LOGGING TABLES
-- ============================================================================

-- Terminal sessions captured from Ghostty
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
    associated_claude_session_id INTEGER,  -- If associated with Claude
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT,
    FOREIGN KEY (associated_claude_session_id) REFERENCES claude_sessions(id) ON DELETE SET NULL
);

-- Terminal output chunks
CREATE TABLE IF NOT EXISTS terminal_output (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    chunk_number INTEGER NOT NULL,
    content TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    is_input INTEGER DEFAULT 0,  -- 0 = output, 1 = input
    metadata TEXT,
    FOREIGN KEY (session_id) REFERENCES terminal_sessions(id) ON DELETE CASCADE
);

-- FTS for terminal output
CREATE VIRTUAL TABLE IF NOT EXISTS terminal_output_fts USING fts5(
    content,
    content='terminal_output',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS terminal_output_ai AFTER INSERT ON terminal_output BEGIN
    INSERT INTO terminal_output_fts(rowid, content)
    VALUES (new.id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS terminal_output_ad AFTER DELETE ON terminal_output BEGIN
    DELETE FROM terminal_output_fts WHERE rowid = old.id;
END;

-- ============================================================================
-- SYNC AND DEVICE MANAGEMENT
-- ============================================================================

-- Device registry
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_name TEXT NOT NULL UNIQUE,  -- 'desktop', 'laptop', 'nas'
    device_type TEXT,  -- 'primary', 'secondary', 'storage'
    hostname TEXT,
    ip_address TEXT,
    tailscale_ip TEXT,
    last_seen_at TEXT,
    last_sync_at TEXT,
    sync_status TEXT,  -- 'synced', 'pending', 'error'
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT
);

-- Sync log
CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_device TEXT NOT NULL,
    target_device TEXT NOT NULL,
    sync_type TEXT NOT NULL,  -- 'full', 'incremental', 'manual'
    table_name TEXT,
    records_synced INTEGER DEFAULT 0,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT,  -- 'success', 'partial', 'failed'
    error_message TEXT,
    metadata TEXT
);

-- ============================================================================
-- INDEXES
-- ============================================================================

-- Audio indexes
CREATE INDEX IF NOT EXISTS idx_audio_created_at ON audio(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audio_tags ON audio(tags);
CREATE INDEX IF NOT EXISTS idx_audio_format ON audio(format);
CREATE INDEX IF NOT EXISTS idx_audio_source_device ON audio(source_device);

-- Transcript indexes
CREATE INDEX IF NOT EXISTS idx_transcripts_created_at ON transcripts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_transcripts_audio_id ON transcripts(audio_id);
CREATE INDEX IF NOT EXISTS idx_transcripts_tags ON transcripts(tags);
CREATE INDEX IF NOT EXISTS idx_transcripts_source_device ON transcripts(source_device);

-- Screenshot indexes
CREATE INDEX IF NOT EXISTS idx_screenshots_created_at ON screenshots(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_screenshots_tags ON screenshots(tags);

-- Claude session indexes
CREATE INDEX IF NOT EXISTS idx_claude_sessions_session_id ON claude_sessions(session_id);
CREATE INDEX IF NOT EXISTS idx_claude_sessions_project ON claude_sessions(project_path);
CREATE INDEX IF NOT EXISTS idx_claude_sessions_started_at ON claude_sessions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_claude_sessions_source_device ON claude_sessions(source_device);
CREATE INDEX IF NOT EXISTS idx_claude_sessions_rating ON claude_sessions(rating);

-- Claude message indexes
CREATE INDEX IF NOT EXISTS idx_claude_messages_session ON claude_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_claude_messages_uuid ON claude_messages(message_uuid);
CREATE INDEX IF NOT EXISTS idx_claude_messages_parent ON claude_messages(parent_uuid);
CREATE INDEX IF NOT EXISTS idx_claude_messages_type ON claude_messages(message_type);
CREATE INDEX IF NOT EXISTS idx_claude_messages_timestamp ON claude_messages(timestamp);

-- Claude history indexes
CREATE INDEX IF NOT EXISTS idx_claude_history_session ON claude_history(session_id);
CREATE INDEX IF NOT EXISTS idx_claude_history_timestamp ON claude_history(timestamp_unix DESC);
CREATE INDEX IF NOT EXISTS idx_claude_history_device ON claude_history(source_device);

-- Voice session indexes
CREATE INDEX IF NOT EXISTS idx_voice_sessions_audio ON voice_sessions(audio_id);
CREATE INDEX IF NOT EXISTS idx_voice_sessions_transcript ON voice_sessions(transcript_id);
CREATE INDEX IF NOT EXISTS idx_voice_sessions_device ON voice_sessions(source_device);
CREATE INDEX IF NOT EXISTS idx_voice_sessions_created ON voice_sessions(created_at DESC);

-- Email indexes
CREATE INDEX IF NOT EXISTS idx_email_threads_account ON email_threads(account_id);
CREATE INDEX IF NOT EXISTS idx_email_threads_last_message ON email_threads(last_message_at DESC);
CREATE INDEX IF NOT EXISTS idx_email_messages_thread ON email_messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_email_messages_account ON email_messages(account_id);
CREATE INDEX IF NOT EXISTS idx_email_messages_from ON email_messages(from_address);
CREATE INDEX IF NOT EXISTS idx_email_messages_received ON email_messages(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_email_attachments_message ON email_attachments(message_id);

-- Terminal indexes
CREATE INDEX IF NOT EXISTS idx_terminal_sessions_device ON terminal_sessions(source_device);
CREATE INDEX IF NOT EXISTS idx_terminal_sessions_started ON terminal_sessions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_terminal_output_session ON terminal_output(session_id);

-- Sync indexes
CREATE INDEX IF NOT EXISTS idx_sync_log_started ON sync_log(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_sync_log_devices ON sync_log(source_device, target_device);

-- ============================================================================
-- EXISTING FTS TABLE (from v1.0.0)
-- ============================================================================

-- Full-text search virtual table for transcripts
CREATE VIRTUAL TABLE IF NOT EXISTS transcripts_fts USING fts5(
    content,
    filename,
    tags,
    content='transcripts',
    content_rowid='id'
);

-- Triggers to keep FTS index in sync with transcripts table
CREATE TRIGGER IF NOT EXISTS transcripts_ai AFTER INSERT ON transcripts BEGIN
    INSERT INTO transcripts_fts(rowid, content, filename, tags)
    VALUES (new.id, new.content, new.filename, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS transcripts_ad AFTER DELETE ON transcripts BEGIN
    DELETE FROM transcripts_fts WHERE rowid = old.id;
END;

CREATE TRIGGER IF NOT EXISTS transcripts_au AFTER UPDATE ON transcripts BEGIN
    DELETE FROM transcripts_fts WHERE rowid = old.id;
    INSERT INTO transcripts_fts(rowid, content, filename, tags)
    VALUES (new.id, new.content, new.filename, new.tags);
END;

-- ============================================================================
-- METADATA TABLE
-- ============================================================================

-- Metadata table for schema version and migration tracking
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR REPLACE INTO metadata (key, value, updated_at) VALUES ('schema_version', '2.0.0', CURRENT_TIMESTAMP);
INSERT OR IGNORE INTO metadata (key, value) VALUES ('created_at', CURRENT_TIMESTAMP);

-- ============================================================================
-- VIEWS FOR COMMON QUERIES
-- ============================================================================

-- View: Recent Claude conversations with stats
CREATE VIEW IF NOT EXISTS v_recent_claude_sessions AS
SELECT
    cs.id,
    cs.session_id,
    cs.project_path,
    cs.summary,
    cs.model_primary,
    cs.total_messages,
    cs.total_input_tokens + cs.total_output_tokens as total_tokens,
    cs.source_device,
    cs.started_at,
    cs.duration_seconds,
    cs.rating,
    (SELECT COUNT(*) FROM claude_subagents WHERE parent_session_id = cs.id) as subagent_count
FROM claude_sessions cs
ORDER BY cs.started_at DESC;

-- View: Voice sessions with audio and transcript info
CREATE VIEW IF NOT EXISTS v_voice_sessions AS
SELECT
    vs.id,
    vs.session_uuid,
    a.filename as audio_filename,
    a.duration_seconds,
    t.content as transcript,
    t.word_count,
    t.confidence,
    vs.success,
    vs.failure_reason,
    vs.corrected_transcript,
    vs.rating,
    vs.source_device,
    vs.created_at
FROM voice_sessions vs
LEFT JOIN audio a ON vs.audio_id = a.id
LEFT JOIN transcripts t ON vs.transcript_id = t.id
ORDER BY vs.created_at DESC;

-- View: Email inbox
CREATE VIEW IF NOT EXISTS v_email_inbox AS
SELECT
    et.id as thread_id,
    et.subject,
    et.snippet,
    et.message_count,
    et.participants,
    et.is_starred,
    et.is_unread,
    et.last_message_at,
    ea.email_address as account
FROM email_threads et
JOIN email_accounts ea ON et.account_id = ea.id
WHERE et.is_unread = 1 OR et.is_starred = 1
ORDER BY et.last_message_at DESC;

-- View: Token usage by day
CREATE VIEW IF NOT EXISTS v_token_usage_daily AS
SELECT
    date(started_at) as date,
    source_device,
    COUNT(*) as session_count,
    SUM(total_input_tokens) as input_tokens,
    SUM(total_output_tokens) as output_tokens,
    SUM(total_cache_read_tokens) as cache_read_tokens,
    SUM(total_input_tokens + total_output_tokens) as total_tokens
FROM claude_sessions
GROUP BY date(started_at), source_device
ORDER BY date DESC;
