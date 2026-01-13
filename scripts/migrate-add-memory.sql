-- Memory Monitoring Schema Migration
-- Adds tables for Claude memory metrics and events
-- Run: sqlite3 datalake.db < scripts/migrate-add-memory.sql

-- Memory metrics (time-series RAM data from metrics.jsonl)
CREATE TABLE IF NOT EXISTS memory_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pid INTEGER NOT NULL,
    session_id TEXT,  -- Claude session UUID if available
    rss_bytes INTEGER NOT NULL,
    rss_mb REAL NOT NULL,
    memory_rate_mb_min REAL,  -- Growth rate MB/min
    command TEXT,
    timestamp TEXT NOT NULL,
    timestamp_unix INTEGER NOT NULL,
    source_device TEXT NOT NULL DEFAULT 'desktop',
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Memory events (from events.jsonl)
CREATE TABLE IF NOT EXISTS memory_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,  -- 'hook_warn', 'hook_block', 'skill_invoke', 'process_kill', 'restart'
    pid INTEGER,
    session_id TEXT,
    severity TEXT DEFAULT 'info',  -- 'info', 'warning', 'critical'
    message TEXT,
    details TEXT,  -- JSON payload
    timestamp TEXT NOT NULL,
    timestamp_unix INTEGER NOT NULL,
    source_device TEXT NOT NULL DEFAULT 'desktop',
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for fast time-range queries
CREATE INDEX IF NOT EXISTS idx_memory_metrics_timestamp ON memory_metrics(timestamp_unix DESC);
CREATE INDEX IF NOT EXISTS idx_memory_metrics_pid ON memory_metrics(pid);
CREATE INDEX IF NOT EXISTS idx_memory_metrics_device ON memory_metrics(source_device);
CREATE INDEX IF NOT EXISTS idx_memory_metrics_session ON memory_metrics(session_id);

CREATE INDEX IF NOT EXISTS idx_memory_events_timestamp ON memory_events(timestamp_unix DESC);
CREATE INDEX IF NOT EXISTS idx_memory_events_type ON memory_events(event_type);
CREATE INDEX IF NOT EXISTS idx_memory_events_severity ON memory_events(severity);
CREATE INDEX IF NOT EXISTS idx_memory_events_pid ON memory_events(pid);

-- Update schema version
INSERT OR REPLACE INTO metadata (key, value, updated_at)
VALUES ('memory_schema_version', '1.0.0', CURRENT_TIMESTAMP);

-- View for today's metrics summary
CREATE VIEW IF NOT EXISTS v_memory_today AS
SELECT
    pid,
    session_id,
    MIN(rss_mb) as min_rss_mb,
    MAX(rss_mb) as max_rss_mb,
    AVG(rss_mb) as avg_rss_mb,
    AVG(memory_rate_mb_min) as avg_rate,
    COUNT(*) as sample_count,
    MIN(timestamp) as first_seen,
    MAX(timestamp) as last_seen
FROM memory_metrics
WHERE date(timestamp) = date('now')
GROUP BY pid, session_id;

-- View for recent events
CREATE VIEW IF NOT EXISTS v_memory_events_recent AS
SELECT *
FROM memory_events
WHERE timestamp_unix > (strftime('%s', 'now') - 86400)
ORDER BY timestamp_unix DESC;
