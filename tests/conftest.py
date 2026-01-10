"""Pytest configuration and fixtures for datalake tests."""
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
import pytest


@pytest.fixture
def temp_datalake():
    """Create a temporary datalake environment for testing."""
    # Create temporary directory
    temp_dir = tempfile.mkdtemp(prefix="datalake_test_")
    temp_path = Path(temp_dir)

    # Set up directory structure
    data_dir = temp_path / "data"
    data_dir.mkdir()
    (data_dir / "audio").mkdir()
    (data_dir / "transcripts").mkdir()
    (data_dir / "screenshots").mkdir()

    scripts_dir = temp_path / "scripts"
    scripts_dir.mkdir()

    logs_dir = temp_path / "logs"
    logs_dir.mkdir()

    # Copy schema file to temp directory
    project_root = Path(__file__).parent.parent
    schema_file = project_root / "schema.sql"
    temp_schema = temp_path / "schema.sql"
    shutil.copy(schema_file, temp_schema)

    # Initialize database
    db_file = temp_path / "datalake.db"
    with open(temp_schema) as f:
        schema_sql = f.read()
    conn = sqlite3.connect(db_file)
    conn.executescript(schema_sql)
    conn.close()

    # Return environment info
    env = {
        "root": temp_path,
        "db": db_file,
        "data_dir": data_dir,
        "scripts_dir": scripts_dir,
        "logs_dir": logs_dir,
        "schema": temp_schema,
    }

    yield env

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def sample_audio_file(tmp_path):
    """Create a sample audio file for testing."""
    audio_file = tmp_path / "test_audio.wav"
    # Create a minimal valid WAV file (44 bytes header + silent audio)
    with open(audio_file, "wb") as f:
        # WAV header for 1 second of silence, 44100 Hz, 16-bit, mono
        f.write(b'RIFF')  # ChunkID
        f.write((36 + 44100 * 2).to_bytes(4, 'little'))  # ChunkSize
        f.write(b'WAVE')  # Format
        f.write(b'fmt ')  # Subchunk1ID
        f.write((16).to_bytes(4, 'little'))  # Subchunk1Size
        f.write((1).to_bytes(2, 'little'))  # AudioFormat (PCM)
        f.write((1).to_bytes(2, 'little'))  # NumChannels (mono)
        f.write((44100).to_bytes(4, 'little'))  # SampleRate
        f.write((44100 * 2).to_bytes(4, 'little'))  # ByteRate
        f.write((2).to_bytes(2, 'little'))  # BlockAlign
        f.write((16).to_bytes(2, 'little'))  # BitsPerSample
        f.write(b'data')  # Subchunk2ID
        f.write((44100 * 2).to_bytes(4, 'little'))  # Subchunk2Size
        # Write 1 second of silence
        f.write(b'\x00' * (44100 * 2))

    return audio_file


@pytest.fixture
def db_connection(temp_datalake):
    """Provide a database connection for testing."""
    conn = sqlite3.connect(temp_datalake["db"])
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()
