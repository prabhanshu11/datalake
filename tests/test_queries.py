"""Tests for query functionality and data retrieval."""
import sqlite3
import pytest
from datetime import datetime, timedelta


def test_query_recent_audio(db_connection):
    """Test querying recent audio files."""
    cursor = db_connection.cursor()

    # Insert test data with different timestamps
    base_time = datetime.now()
    for i in range(5):
        timestamp = (base_time - timedelta(hours=i)).isoformat()
        cursor.execute("""
            INSERT INTO audio (file_path, filename, original_filename, created_at)
            VALUES (?, ?, ?, ?)
        """, (f"audio/2026/01/10/test_{i}.wav", f"test_{i}.wav", f"test_{i}.wav", timestamp))

    db_connection.commit()

    # Query recent audio (last 3)
    cursor.execute("""
        SELECT filename FROM audio
        ORDER BY created_at DESC
        LIMIT 3
    """)
    results = cursor.fetchall()

    assert len(results) == 3
    assert results[0][0] == "test_0.wav"  # Most recent
    assert results[1][0] == "test_1.wav"
    assert results[2][0] == "test_2.wav"


def test_query_audio_by_tags(db_connection):
    """Test querying audio files by tags."""
    cursor = db_connection.cursor()

    # Insert test data with different tags
    test_data = [
        ("audio/2026/01/10/test1.wav", "test1.wav", "meeting,work"),
        ("audio/2026/01/10/test2.wav", "test2.wav", "personal,notes"),
        ("audio/2026/01/10/test3.wav", "test3.wav", "meeting,important"),
    ]

    for file_path, filename, tags in test_data:
        cursor.execute("""
            INSERT INTO audio (file_path, filename, original_filename, tags, created_at)
            VALUES (?, ?, ?, ?, '2026-01-10T12:00:00')
        """, (file_path, filename, filename, tags))

    db_connection.commit()

    # Query by tag "meeting"
    cursor.execute("""
        SELECT filename FROM audio
        WHERE tags LIKE '%meeting%'
        ORDER BY filename
    """)
    results = cursor.fetchall()

    assert len(results) == 2
    assert results[0][0] == "test1.wav"
    assert results[1][0] == "test3.wav"


def test_query_audio_by_format(db_connection):
    """Test querying audio files by format."""
    cursor = db_connection.cursor()

    # Insert test data with different formats
    test_data = [
        ("audio/2026/01/10/test1.wav", "test1.wav", "wav"),
        ("audio/2026/01/10/test2.mp3", "test2.mp3", "mp3"),
        ("audio/2026/01/10/test3.wav", "test3.wav", "wav"),
    ]

    for file_path, filename, format_type in test_data:
        cursor.execute("""
            INSERT INTO audio (file_path, filename, original_filename, format, created_at)
            VALUES (?, ?, ?, ?, '2026-01-10T12:00:00')
        """, (file_path, filename, filename, format_type))

    db_connection.commit()

    # Query WAV files
    cursor.execute("""
        SELECT filename FROM audio
        WHERE format = 'wav'
        ORDER BY filename
    """)
    results = cursor.fetchall()

    assert len(results) == 2
    assert results[0][0] == "test1.wav"
    assert results[1][0] == "test3.wav"


def test_query_audio_with_duration(db_connection):
    """Test querying audio files with duration constraints."""
    cursor = db_connection.cursor()

    # Insert test data with different durations
    test_data = [
        ("audio/2026/01/10/short.wav", "short.wav", 5.5),
        ("audio/2026/01/10/medium.wav", "medium.wav", 30.0),
        ("audio/2026/01/10/long.wav", "long.wav", 120.0),
    ]

    for file_path, filename, duration in test_data:
        cursor.execute("""
            INSERT INTO audio (file_path, filename, original_filename, duration_seconds, created_at)
            VALUES (?, ?, ?, ?, '2026-01-10T12:00:00')
        """, (file_path, filename, filename, duration))

    db_connection.commit()

    # Query files longer than 20 seconds
    cursor.execute("""
        SELECT filename, duration_seconds FROM audio
        WHERE duration_seconds > 20
        ORDER BY duration_seconds
    """)
    results = cursor.fetchall()

    assert len(results) == 2
    assert results[0][0] == "medium.wav"
    assert results[1][0] == "long.wav"


def test_query_transcripts_with_audio(db_connection):
    """Test joining transcripts with audio records."""
    cursor = db_connection.cursor()

    # Insert audio
    cursor.execute("""
        INSERT INTO audio (file_path, filename, original_filename, created_at)
        VALUES ('audio/2026/01/10/test.wav', 'test.wav', 'test.wav', '2026-01-10T12:00:00')
    """)
    audio_id = cursor.lastrowid

    # Insert transcript
    cursor.execute("""
        INSERT INTO transcripts (file_path, filename, audio_id, content, created_at)
        VALUES ('transcripts/2026/01/10/test.txt', 'test.txt', ?, 'Test transcript content', '2026-01-10T12:00:00')
    """, (audio_id,))

    db_connection.commit()

    # Query with join
    cursor.execute("""
        SELECT a.filename as audio_file, t.filename as transcript_file, t.content
        FROM transcripts t
        JOIN audio a ON t.audio_id = a.id
    """)
    result = cursor.fetchone()

    assert result is not None
    assert result[0] == "test.wav"
    assert result[1] == "test.txt"
    assert result[2] == "Test transcript content"


def test_query_statistics(db_connection):
    """Test aggregate statistics queries."""
    cursor = db_connection.cursor()

    # Insert test audio data
    for i in range(10):
        cursor.execute("""
            INSERT INTO audio (file_path, filename, original_filename, duration_seconds, size_bytes, created_at)
            VALUES (?, ?, ?, ?, ?, '2026-01-10T12:00:00')
        """, (f"audio/2026/01/10/test_{i}.wav", f"test_{i}.wav", f"test_{i}.wav", 10.0, 1024000))

    db_connection.commit()

    # Get statistics
    cursor.execute("""
        SELECT
            COUNT(*) as total_files,
            SUM(duration_seconds) as total_duration,
            SUM(size_bytes) as total_size,
            AVG(duration_seconds) as avg_duration
        FROM audio
    """)
    stats = cursor.fetchone()

    assert stats["total_files"] == 10
    assert stats["total_duration"] == 100.0
    assert stats["total_size"] == 10240000
    assert stats["avg_duration"] == 10.0


def test_fts_ranking(db_connection):
    """Test that full-text search returns results in rank order."""
    cursor = db_connection.cursor()

    # Insert transcripts with varying relevance
    test_data = [
        ("t1.txt", "Python programming"),
        ("t2.txt", "Python Python Python programming language"),
        ("t3.txt", "Java programming"),
    ]

    for filename, content in test_data:
        cursor.execute("""
            INSERT INTO transcripts (file_path, filename, content, created_at)
            VALUES (?, ?, ?, '2026-01-10T12:00:00')
        """, (f"transcripts/2026/01/10/{filename}", filename, content))

    db_connection.commit()

    # Search for "Python" - t2.txt should rank higher
    cursor.execute("""
        SELECT t.filename
        FROM transcripts t
        JOIN transcripts_fts ON t.id = transcripts_fts.rowid
        WHERE transcripts_fts MATCH 'Python'
        ORDER BY rank
    """)
    results = cursor.fetchall()

    assert len(results) == 2
    # t2.txt should be first due to multiple occurrences
    assert results[0][0] == "t2.txt"


def test_query_by_date_range(db_connection):
    """Test querying records by date range."""
    cursor = db_connection.cursor()

    # Insert data across multiple dates
    test_dates = [
        ("2026-01-08T12:00:00", "old.wav"),
        ("2026-01-09T12:00:00", "yesterday.wav"),
        ("2026-01-10T12:00:00", "today.wav"),
        ("2026-01-11T12:00:00", "tomorrow.wav"),
    ]

    for created_at, filename in test_dates:
        cursor.execute("""
            INSERT INTO audio (file_path, filename, original_filename, created_at)
            VALUES (?, ?, ?, ?)
        """, (f"audio/2026/01/10/{filename}", filename, filename, created_at))

    db_connection.commit()

    # Query for Jan 9-10
    cursor.execute("""
        SELECT filename FROM audio
        WHERE created_at >= '2026-01-09T00:00:00'
          AND created_at < '2026-01-11T00:00:00'
        ORDER BY created_at
    """)
    results = cursor.fetchall()

    assert len(results) == 2
    assert results[0][0] == "yesterday.wav"
    assert results[1][0] == "today.wav"


def test_query_empty_database(db_connection):
    """Test queries on empty database return no results."""
    cursor = db_connection.cursor()

    cursor.execute("SELECT * FROM audio")
    assert len(cursor.fetchall()) == 0

    cursor.execute("SELECT * FROM transcripts")
    assert len(cursor.fetchall()) == 0

    cursor.execute("SELECT * FROM screenshots")
    assert len(cursor.fetchall()) == 0
