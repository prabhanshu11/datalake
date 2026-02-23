-- Datalake Schema Migration v3.0.0 — Memory Velocity Tables
-- Source: freeze-monitor velocity JSONL (~/Programs/utilities/freeze-monitor/logs/velocity-*.jsonl)
-- Run: sqlite3 datalake.db < schema_v3_memory.sql
--
-- These tables store system-wide memory telemetry at 3-second resolution,
-- enabling long-term analysis of RAM velocity patterns, OOM precursors,
-- and per-process memory growth across devices.

-- ============================================================================
-- MEMORY VELOCITY TIME-SERIES
-- ============================================================================

-- System-wide memory snapshot every 3 seconds (from freeze-monitor)
CREATE TABLE IF NOT EXISTS memory_velocity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_utc TEXT NOT NULL,          -- ISO 8601: 2026-02-23T07:03:42Z
    timestamp_unix INTEGER NOT NULL,      -- Unix epoch seconds
    source_device TEXT NOT NULL,          -- hostname: 'omarchy', 'pi-hub'
    ram_total_mb INTEGER NOT NULL,
    ram_used_mb INTEGER NOT NULL,
    ram_available_mb INTEGER NOT NULL,
    swap_used_mb INTEGER NOT NULL,
    swap_total_mb INTEGER NOT NULL,
    velocity_mb_s REAL NOT NULL DEFAULT 0, -- MB/s delta (positive = growing)
    severity TEXT NOT NULL DEFAULT 'nominal', -- nominal|elevated|warning|critical
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Per-sample top memory consumers (child of memory_velocity)
-- Normalized from the top_consumers JSON array in each JSONL line
CREATE TABLE IF NOT EXISTS memory_velocity_consumers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    velocity_id INTEGER NOT NULL,         -- FK to memory_velocity
    pid INTEGER NOT NULL,
    process_name TEXT NOT NULL,
    rss_mb INTEGER NOT NULL,
    delta_mb INTEGER NOT NULL DEFAULT 0,  -- MB change since previous sample
    window_s INTEGER NOT NULL DEFAULT 3,  -- Sample interval
    FOREIGN KEY (velocity_id) REFERENCES memory_velocity(id) ON DELETE CASCADE
);

-- Severity transition events (materialized from velocity data)
-- One row per severity change, not per sample — useful for alerting and dashboards
CREATE TABLE IF NOT EXISTS memory_severity_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_utc TEXT NOT NULL,
    timestamp_unix INTEGER NOT NULL,
    source_device TEXT NOT NULL,
    severity TEXT NOT NULL,               -- The severity level entered
    ram_available_mb INTEGER,
    swap_used_mb INTEGER,
    velocity_mb_s REAL,
    duration_s INTEGER,                   -- How long this severity lasted (filled on transition out)
    top_consumer_pid INTEGER,
    top_consumer_name TEXT,
    top_consumer_rss_mb INTEGER,
    resolved_at TEXT,                      -- When severity dropped back to nominal
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- INDEXES
-- ============================================================================

-- Primary query pattern: time-range scans per device
CREATE INDEX IF NOT EXISTS idx_mv_device_time ON memory_velocity(source_device, timestamp_unix DESC);
CREATE INDEX IF NOT EXISTS idx_mv_timestamp ON memory_velocity(timestamp_unix DESC);
CREATE INDEX IF NOT EXISTS idx_mv_severity ON memory_velocity(severity) WHERE severity != 'nominal';

-- Consumer lookups
CREATE INDEX IF NOT EXISTS idx_mvc_velocity ON memory_velocity_consumers(velocity_id);
CREATE INDEX IF NOT EXISTS idx_mvc_process ON memory_velocity_consumers(process_name, rss_mb DESC);

-- Event queries
CREATE INDEX IF NOT EXISTS idx_mse_device_time ON memory_severity_events(source_device, timestamp_unix DESC);
CREATE INDEX IF NOT EXISTS idx_mse_severity ON memory_severity_events(severity);

-- ============================================================================
-- VIEWS
-- ============================================================================

-- View: Memory velocity with severity != nominal (anomalies only)
CREATE VIEW IF NOT EXISTS v_memory_anomalies AS
SELECT
    mv.id,
    mv.timestamp_utc,
    mv.source_device,
    mv.ram_available_mb,
    mv.ram_used_mb,
    mv.swap_used_mb,
    mv.velocity_mb_s,
    mv.severity,
    (SELECT group_concat(process_name || '(' || rss_mb || 'MB)', ', ')
     FROM memory_velocity_consumers
     WHERE velocity_id = mv.id
     ORDER BY rss_mb DESC) as top_consumers
FROM memory_velocity mv
WHERE mv.severity != 'nominal'
ORDER BY mv.timestamp_unix DESC;

-- View: Hourly memory summary (for long-term trend analysis)
CREATE VIEW IF NOT EXISTS v_memory_hourly AS
SELECT
    source_device,
    strftime('%Y-%m-%d %H:00', timestamp_utc) as hour,
    COUNT(*) as samples,
    ROUND(AVG(ram_used_mb), 0) as avg_used_mb,
    ROUND(AVG(ram_available_mb), 0) as avg_available_mb,
    ROUND(MIN(ram_available_mb), 0) as min_available_mb,
    ROUND(MAX(velocity_mb_s), 1) as max_velocity_mb_s,
    ROUND(AVG(velocity_mb_s), 1) as avg_velocity_mb_s,
    ROUND(AVG(swap_used_mb), 0) as avg_swap_mb,
    SUM(CASE WHEN severity != 'nominal' THEN 1 ELSE 0 END) as anomaly_count
FROM memory_velocity
GROUP BY source_device, strftime('%Y-%m-%d %H:00', timestamp_utc)
ORDER BY hour DESC;

-- View: Daily peak memory usage
CREATE VIEW IF NOT EXISTS v_memory_daily_peaks AS
SELECT
    source_device,
    date(timestamp_utc) as date,
    COUNT(*) as total_samples,
    ROUND(MAX(ram_used_mb), 0) as peak_used_mb,
    ROUND(MIN(ram_available_mb), 0) as min_available_mb,
    ROUND(MAX(ABS(velocity_mb_s)), 1) as peak_velocity_mb_s,
    ROUND(MAX(swap_used_mb), 0) as peak_swap_mb,
    SUM(CASE WHEN severity = 'critical' THEN 1 ELSE 0 END) as critical_samples,
    SUM(CASE WHEN severity = 'warning' THEN 1 ELSE 0 END) as warning_samples,
    SUM(CASE WHEN severity = 'elevated' THEN 1 ELSE 0 END) as elevated_samples
FROM memory_velocity
GROUP BY source_device, date(timestamp_utc)
ORDER BY date DESC;

-- View: Severity events with duration
CREATE VIEW IF NOT EXISTS v_severity_events AS
SELECT
    mse.id,
    mse.timestamp_utc,
    mse.source_device,
    mse.severity,
    mse.ram_available_mb,
    mse.velocity_mb_s,
    mse.duration_s,
    mse.top_consumer_name,
    mse.top_consumer_rss_mb,
    mse.resolved_at
FROM memory_severity_events mse
ORDER BY mse.timestamp_unix DESC;

-- ============================================================================
-- SCHEMA VERSION UPDATE
-- ============================================================================

INSERT OR REPLACE INTO metadata (key, value, updated_at)
VALUES ('schema_version', '3.0.0', CURRENT_TIMESTAMP);

INSERT OR REPLACE INTO metadata (key, value, updated_at)
VALUES ('schema_v3_migration', 'memory_velocity tables added', CURRENT_TIMESTAMP);
