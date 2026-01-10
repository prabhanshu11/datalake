-- Datalake SQLite Schema
-- Designed for fast queries on audio recordings, transcripts, and screenshots

-- Audio recordings table
CREATE TABLE IF NOT EXISTS audio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL UNIQUE,  -- Relative path from /mnt/data-ssd/datalake/
    filename TEXT NOT NULL,
    original_filename TEXT,
    duration_seconds REAL,
    format TEXT,  -- e.g., 'wav', 'mp3', 'flac'
    sample_rate INTEGER,
    channels INTEGER,
    size_bytes INTEGER,
    tags TEXT,  -- JSON array or comma-separated tags
    created_at TEXT NOT NULL,  -- ISO 8601 timestamp
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT  -- JSON for additional metadata
);

-- Transcripts table
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
    created_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT,
    FOREIGN KEY (audio_id) REFERENCES audio(id) ON DELETE SET NULL
);

-- Screenshots table
CREATE TABLE IF NOT EXISTS screenshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL UNIQUE,
    filename TEXT NOT NULL,
    width INTEGER,
    height INTEGER,
    format TEXT,  -- e.g., 'png', 'jpg'
    size_bytes INTEGER,
    tags TEXT,
    created_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT
);

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

-- Indexes for fast queries
CREATE INDEX IF NOT EXISTS idx_audio_created_at ON audio(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audio_tags ON audio(tags);
CREATE INDEX IF NOT EXISTS idx_audio_format ON audio(format);

CREATE INDEX IF NOT EXISTS idx_transcripts_created_at ON transcripts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_transcripts_audio_id ON transcripts(audio_id);
CREATE INDEX IF NOT EXISTS idx_transcripts_tags ON transcripts(tags);

CREATE INDEX IF NOT EXISTS idx_screenshots_created_at ON screenshots(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_screenshots_tags ON screenshots(tags);

-- Metadata table for schema version and migration tracking
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO metadata (key, value) VALUES ('schema_version', '1.0.0');
INSERT OR IGNORE INTO metadata (key, value) VALUES ('created_at', CURRENT_TIMESTAMP);
