-- Migration: Add explorer tables for conversation tree visualization
-- Run: sqlite3 ~/Programs/datalake/datalake.db < scripts/migrate-add-explorer.sql

-- Tool events: individual tool invocations paired with results
CREATE TABLE IF NOT EXISTS claude_tool_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    message_uuid TEXT NOT NULL,
    result_message_uuid TEXT,
    tool_use_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    tool_input TEXT,
    tool_result TEXT,
    is_error INTEGER DEFAULT 0,
    file_path TEXT,
    sequence_number INTEGER,
    timestamp TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES claude_sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tool_events_session ON claude_tool_events(session_id);
CREATE INDEX IF NOT EXISTS idx_tool_events_name ON claude_tool_events(tool_name);
CREATE INDEX IF NOT EXISTS idx_tool_events_file ON claude_tool_events(file_path);
CREATE INDEX IF NOT EXISTS idx_tool_events_tool_use_id ON claude_tool_events(tool_use_id);

-- Compaction events: context window boundaries
CREATE TABLE IF NOT EXISTS claude_compaction_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    leaf_uuid TEXT,
    summary_text TEXT NOT NULL,
    sequence_number INTEGER,
    timestamp TEXT,
    FOREIGN KEY (session_id) REFERENCES claude_sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_compaction_session ON claude_compaction_events(session_id);

-- File operations: Write/Edit operations for intermediate code files
CREATE TABLE IF NOT EXISTS claude_file_operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    tool_event_id INTEGER,
    operation TEXT NOT NULL,
    file_path TEXT NOT NULL,
    content_preview TEXT,
    old_string TEXT,
    new_string TEXT,
    sequence_number INTEGER,
    timestamp TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES claude_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (tool_event_id) REFERENCES claude_tool_events(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_file_ops_session ON claude_file_operations(session_id);
CREATE INDEX IF NOT EXISTS idx_file_ops_path ON claude_file_operations(file_path);
