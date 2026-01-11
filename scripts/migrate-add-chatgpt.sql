-- Migration: Add ChatGPT conversation support
-- Safe to run multiple times (uses IF NOT EXISTS)

-- ChatGPT conversations table
CREATE TABLE IF NOT EXISTS chatgpt_conversations (
    id INTEGER PRIMARY KEY,
    conversation_id TEXT UNIQUE NOT NULL,  -- ChatGPT's stable ID
    title TEXT,
    create_time REAL,  -- Unix timestamp
    update_time REAL,
    model_slug TEXT,  -- default_model_slug (e.g., gpt-4, gpt-3.5-turbo)
    is_archived INTEGER DEFAULT 0,
    is_starred INTEGER DEFAULT 0,
    message_count INTEGER DEFAULT 0,
    -- Import tracking
    import_id INTEGER REFERENCES chatgpt_imports(id),
    source_device TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    rating INTEGER CHECK(rating >= 1 AND rating <= 10),
    rating_notes TEXT
);

-- ChatGPT messages (flattened from tree structure)
CREATE TABLE IF NOT EXISTS chatgpt_messages (
    id INTEGER PRIMARY KEY,
    conversation_id INTEGER REFERENCES chatgpt_conversations(id) ON DELETE CASCADE,
    message_id TEXT,  -- ChatGPT's node ID
    parent_id TEXT,   -- Parent node for threading
    role TEXT,        -- user, assistant, system, tool
    content_type TEXT, -- text, code, image, execution_output, etc.
    content_text TEXT,
    create_time REAL,
    model_slug TEXT,
    sequence_number INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Import tracking (for duplicate detection + raw file storage)
CREATE TABLE IF NOT EXISTS chatgpt_imports (
    id INTEGER PRIMARY KEY,
    zip_hash TEXT UNIQUE,  -- SHA256 of zip file
    original_filename TEXT,
    zip_path TEXT,  -- Where we stored the raw zip
    conversation_count INTEGER,
    message_count INTEGER,
    imported_at TEXT DEFAULT CURRENT_TIMESTAMP,
    source_device TEXT
);

-- FTS for ChatGPT messages
CREATE VIRTUAL TABLE IF NOT EXISTS chatgpt_messages_fts USING fts5(
    content_text,
    content='chatgpt_messages',
    content_rowid='id'
);

-- Trigger to keep FTS in sync (insert)
CREATE TRIGGER IF NOT EXISTS chatgpt_messages_ai AFTER INSERT ON chatgpt_messages BEGIN
    INSERT INTO chatgpt_messages_fts(rowid, content_text)
    VALUES (new.id, new.content_text);
END;

-- Trigger to keep FTS in sync (delete)
CREATE TRIGGER IF NOT EXISTS chatgpt_messages_ad AFTER DELETE ON chatgpt_messages BEGIN
    INSERT INTO chatgpt_messages_fts(chatgpt_messages_fts, rowid, content_text)
    VALUES('delete', old.id, old.content_text);
END;

-- Trigger to keep FTS in sync (update)
CREATE TRIGGER IF NOT EXISTS chatgpt_messages_au AFTER UPDATE ON chatgpt_messages BEGIN
    INSERT INTO chatgpt_messages_fts(chatgpt_messages_fts, rowid, content_text)
    VALUES('delete', old.id, old.content_text);
    INSERT INTO chatgpt_messages_fts(rowid, content_text)
    VALUES (new.id, new.content_text);
END;

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_chatgpt_conversations_import ON chatgpt_conversations(import_id);
CREATE INDEX IF NOT EXISTS idx_chatgpt_conversations_created ON chatgpt_conversations(created_at);
CREATE INDEX IF NOT EXISTS idx_chatgpt_messages_conversation ON chatgpt_messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_chatgpt_messages_sequence ON chatgpt_messages(conversation_id, sequence_number);
CREATE INDEX IF NOT EXISTS idx_chatgpt_messages_role ON chatgpt_messages(role);
