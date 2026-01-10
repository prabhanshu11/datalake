"""Tests for database schema and operations."""
import sqlite3
import pytest


def test_database_exists(temp_datalake):
    """Test that the database file is created."""
    assert temp_datalake["db"].exists()


def test_schema_tables_exist(db_connection):
    """Test that all required tables are created."""
    cursor = db_connection.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cursor.fetchall()}

    required_tables = {
        "audio",
        "transcripts",
        "screenshots",
        "transcripts_fts",
        "metadata",
    }

    assert required_tables.issubset(tables), f"Missing tables: {required_tables - tables}"


def test_audio_table_schema(db_connection):
    """Test audio table has correct columns."""
    cursor = db_connection.cursor()
    cursor.execute("PRAGMA table_info(audio);")
    columns = {row[1] for row in cursor.fetchall()}

    required_columns = {
        "id", "file_path", "filename", "original_filename",
        "duration_seconds", "format", "sample_rate", "channels",
        "size_bytes", "tags", "created_at", "ingested_at", "metadata"
    }

    assert required_columns == columns


def test_transcripts_table_schema(db_connection):
    """Test transcripts table has correct columns."""
    cursor = db_connection.cursor()
    cursor.execute("PRAGMA table_info(transcripts);")
    columns = {row[1] for row in cursor.fetchall()}

    required_columns = {
        "id", "file_path", "filename", "audio_id", "content",
        "word_count", "language", "confidence", "provider",
        "size_bytes", "tags", "created_at", "ingested_at", "metadata"
    }

    assert required_columns == columns


def test_screenshots_table_schema(db_connection):
    """Test screenshots table has correct columns."""
    cursor = db_connection.cursor()
    cursor.execute("PRAGMA table_info(screenshots);")
    columns = {row[1] for row in cursor.fetchall()}

    required_columns = {
        "id", "file_path", "filename", "width", "height",
        "format", "size_bytes", "tags", "created_at",
        "ingested_at", "metadata"
    }

    assert required_columns == columns


def test_indexes_exist(db_connection):
    """Test that indexes are created for performance."""
    cursor = db_connection.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index';")
    indexes = {row[0] for row in cursor.fetchall()}

    expected_indexes = {
        "idx_audio_created_at",
        "idx_audio_tags",
        "idx_audio_format",
        "idx_transcripts_created_at",
        "idx_transcripts_audio_id",
        "idx_transcripts_tags",
        "idx_screenshots_created_at",
        "idx_screenshots_tags",
    }

    # FTS indexes are auto-created, so we filter those out
    actual_indexes = {idx for idx in indexes if not idx.startswith("sqlite_")}

    assert expected_indexes.issubset(actual_indexes), f"Missing indexes: {expected_indexes - actual_indexes}"


def test_insert_audio_record(db_connection):
    """Test inserting an audio record."""
    cursor = db_connection.cursor()
    cursor.execute("""
        INSERT INTO audio (file_path, filename, original_filename, duration_seconds,
                          format, sample_rate, channels, size_bytes, tags, created_at)
        VALUES ('audio/2026/01/10/test.wav', 'test.wav', 'original.wav', 10.5,
                'wav', 44100, 2, 1024, 'test,sample', '2026-01-10T12:00:00')
    """)
    db_connection.commit()

    cursor.execute("SELECT * FROM audio WHERE filename='test.wav'")
    row = cursor.fetchone()

    assert row is not None
    assert row["filename"] == "test.wav"
    assert row["duration_seconds"] == 10.5
    assert row["format"] == "wav"
    assert row["sample_rate"] == 44100
    assert row["channels"] == 2
    assert row["size_bytes"] == 1024
    assert row["tags"] == "test,sample"


def test_insert_transcript_record(db_connection):
    """Test inserting a transcript record."""
    cursor = db_connection.cursor()

    # First insert audio record
    cursor.execute("""
        INSERT INTO audio (file_path, filename, original_filename, created_at)
        VALUES ('audio/2026/01/10/test.wav', 'test.wav', 'test.wav', '2026-01-10T12:00:00')
    """)
    audio_id = cursor.lastrowid

    # Insert transcript
    cursor.execute("""
        INSERT INTO transcripts (file_path, filename, audio_id, content, word_count,
                                language, confidence, provider, size_bytes, tags, created_at)
        VALUES ('transcripts/2026/01/10/test.txt', 'test.txt', ?, 'Hello world test',
                3, 'en', 0.95, 'assemblyai', 512, 'test', '2026-01-10T12:00:00')
    """, (audio_id,))
    db_connection.commit()

    cursor.execute("SELECT * FROM transcripts WHERE filename='test.txt'")
    row = cursor.fetchone()

    assert row is not None
    assert row["audio_id"] == audio_id
    assert row["content"] == "Hello world test"
    assert row["word_count"] == 3
    assert row["language"] == "en"
    assert row["confidence"] == 0.95


def test_fts_search(db_connection):
    """Test full-text search on transcripts."""
    cursor = db_connection.cursor()

    # Insert test transcripts
    test_data = [
        ("transcripts/2026/01/10/test1.txt", "test1.txt", "The quick brown fox jumps over the lazy dog", "animals"),
        ("transcripts/2026/01/10/test2.txt", "test2.txt", "Python is a great programming language", "programming"),
        ("transcripts/2026/01/10/test3.txt", "test3.txt", "Machine learning and artificial intelligence", "ai,ml"),
    ]

    for file_path, filename, content, tags in test_data:
        cursor.execute("""
            INSERT INTO transcripts (file_path, filename, content, tags, created_at)
            VALUES (?, ?, ?, ?, '2026-01-10T12:00:00')
        """, (file_path, filename, content, tags))

    db_connection.commit()

    # Search for "python"
    cursor.execute("""
        SELECT t.filename, t.content
        FROM transcripts t
        JOIN transcripts_fts ON t.id = transcripts_fts.rowid
        WHERE transcripts_fts MATCH 'python'
    """)
    results = cursor.fetchall()

    assert len(results) == 1
    assert results[0]["filename"] == "test2.txt"

    # Search for "fox"
    cursor.execute("""
        SELECT t.filename, t.content
        FROM transcripts t
        JOIN transcripts_fts ON t.id = transcripts_fts.rowid
        WHERE transcripts_fts MATCH 'fox'
    """)
    results = cursor.fetchall()

    assert len(results) == 1
    assert results[0]["filename"] == "test1.txt"


def test_metadata_table(db_connection):
    """Test metadata table has schema version."""
    cursor = db_connection.cursor()
    cursor.execute("SELECT value FROM metadata WHERE key='schema_version'")
    row = cursor.fetchone()

    assert row is not None
    assert row[0] == "1.0.0"


def test_foreign_key_constraint(db_connection):
    """Test foreign key relationship between transcripts and audio."""
    cursor = db_connection.cursor()

    # Enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON")

    # Insert audio
    cursor.execute("""
        INSERT INTO audio (file_path, filename, original_filename, created_at)
        VALUES ('audio/2026/01/10/test.wav', 'test.wav', 'test.wav', '2026-01-10T12:00:00')
    """)
    audio_id = cursor.lastrowid
    db_connection.commit()

    # Insert transcript with valid audio_id
    cursor.execute("""
        INSERT INTO transcripts (file_path, filename, audio_id, content, created_at)
        VALUES ('transcripts/2026/01/10/test.txt', 'test.txt', ?, 'Test content', '2026-01-10T12:00:00')
    """, (audio_id,))
    db_connection.commit()

    # Verify transcript was inserted
    cursor.execute("SELECT COUNT(*) FROM transcripts WHERE audio_id=?", (audio_id,))
    assert cursor.fetchone()[0] == 1

    # Delete audio - transcript's audio_id should be set to NULL due to ON DELETE SET NULL
    cursor.execute("DELETE FROM audio WHERE id=?", (audio_id,))
    db_connection.commit()

    cursor.execute("SELECT audio_id FROM transcripts WHERE filename='test.txt'")
    row = cursor.fetchone()
    assert row[0] is None  # Should be NULL after audio deletion
