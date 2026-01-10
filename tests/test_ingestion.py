"""Tests for audio ingestion functionality."""
import os
import subprocess
from pathlib import Path
import sqlite3
import pytest


def test_ingest_audio_script_exists():
    """Test that the ingest-audio.sh script exists and is executable."""
    script_path = Path(__file__).parent.parent / "scripts" / "ingest-audio.sh"
    assert script_path.exists()
    assert os.access(script_path, os.X_OK)


def test_ingest_audio_basic(temp_datalake, sample_audio_file):
    """Test basic audio ingestion."""
    # Set environment variables
    env = os.environ.copy()
    env["DATA_DIR"] = str(temp_datalake["data_dir"])
    env["DB_FILE"] = str(temp_datalake["db"])
    env["LOG_DIR"] = str(temp_datalake["logs_dir"])
    env["DB_FILE"] = str(temp_datalake["db"])
    env["LOG_DIR"] = str(temp_datalake["logs_dir"])

    # Run ingestion script
    script_path = Path(__file__).parent.parent / "scripts" / "ingest-audio.sh"
    result = subprocess.run(
        [str(script_path), str(sample_audio_file)],
        cwd=str(temp_datalake["root"]),
        env=env,
        capture_output=True,
        text=True
    )

    # Check script succeeded
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    assert "Audio ingested successfully" in result.stdout

    # Verify database record
    conn = sqlite3.connect(temp_datalake["db"])
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM audio ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    assert row["original_filename"] == sample_audio_file.name
    assert row["format"] in ["wav", "pcm_s16le"]  # Depends on ffprobe availability
    assert row["size_bytes"] > 0


def test_ingest_audio_with_tags(temp_datalake, sample_audio_file):
    """Test audio ingestion with tags."""
    env = os.environ.copy()
    env["DATA_DIR"] = str(temp_datalake["data_dir"])
    env["DB_FILE"] = str(temp_datalake["db"])
    env["LOG_DIR"] = str(temp_datalake["logs_dir"])

    script_path = Path(__file__).parent.parent / "scripts" / "ingest-audio.sh"
    result = subprocess.run(
        [str(script_path), str(sample_audio_file), "test,important,meeting"],
        cwd=str(temp_datalake["root"]),
        env=env,
        capture_output=True,
        text=True
    )

    assert result.returncode == 0

    # Verify tags in database
    conn = sqlite3.connect(temp_datalake["db"])
    cursor = conn.cursor()
    cursor.execute("SELECT tags FROM audio ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    assert row[0] == "test,important,meeting"


def test_ingest_audio_file_not_found(temp_datalake):
    """Test ingestion with non-existent file."""
    env = os.environ.copy()
    env["DATA_DIR"] = str(temp_datalake["data_dir"])
    env["DB_FILE"] = str(temp_datalake["db"])
    env["LOG_DIR"] = str(temp_datalake["logs_dir"])

    script_path = Path(__file__).parent.parent / "scripts" / "ingest-audio.sh"
    result = subprocess.run(
        [str(script_path), "nonexistent.wav"],
        cwd=str(temp_datalake["root"]),
        env=env,
        capture_output=True,
        text=True
    )

    assert result.returncode == 1
    assert "Audio file not found" in result.stderr or "not found" in result.stdout.lower()


def test_ingest_audio_no_database(temp_datalake, sample_audio_file):
    """Test ingestion fails gracefully when database doesn't exist."""
    # Remove database
    temp_datalake["db"].unlink()

    env = os.environ.copy()
    env["DATA_DIR"] = str(temp_datalake["data_dir"])
    env["DB_FILE"] = str(temp_datalake["db"])
    env["LOG_DIR"] = str(temp_datalake["logs_dir"])

    script_path = Path(__file__).parent.parent / "scripts" / "ingest-audio.sh"
    result = subprocess.run(
        [str(script_path), str(sample_audio_file)],
        cwd=str(temp_datalake["root"]),
        env=env,
        capture_output=True,
        text=True
    )

    assert result.returncode == 1
    assert "Database not found" in result.stderr or "not found" in result.stdout.lower()


def test_ingest_audio_creates_date_directories(temp_datalake, sample_audio_file):
    """Test that ingestion creates proper date-based directory structure."""
    from datetime import datetime

    env = os.environ.copy()
    env["DATA_DIR"] = str(temp_datalake["data_dir"])
    env["DB_FILE"] = str(temp_datalake["db"])
    env["LOG_DIR"] = str(temp_datalake["logs_dir"])

    script_path = Path(__file__).parent.parent / "scripts" / "ingest-audio.sh"
    result = subprocess.run(
        [str(script_path), str(sample_audio_file)],
        cwd=str(temp_datalake["root"]),
        env=env,
        capture_output=True,
        text=True
    )

    assert result.returncode == 0

    # Check directory structure
    now = datetime.now()
    year_dir = temp_datalake["data_dir"] / "audio" / now.strftime("%Y")
    month_dir = year_dir / now.strftime("%m")
    day_dir = month_dir / now.strftime("%d")

    assert year_dir.exists()
    assert month_dir.exists()
    assert day_dir.exists()

    # Check file exists in correct location
    files = list(day_dir.glob("*.wav"))
    assert len(files) > 0


def test_ingest_audio_file_permissions(temp_datalake, sample_audio_file):
    """Test that ingested files have correct permissions."""
    env = os.environ.copy()
    env["DATA_DIR"] = str(temp_datalake["data_dir"])
    env["DB_FILE"] = str(temp_datalake["db"])
    env["LOG_DIR"] = str(temp_datalake["logs_dir"])

    script_path = Path(__file__).parent.parent / "scripts" / "ingest-audio.sh"
    result = subprocess.run(
        [str(script_path), str(sample_audio_file)],
        cwd=str(temp_datalake["root"]),
        env=env,
        capture_output=True,
        text=True
    )

    assert result.returncode == 0

    # Find the ingested file
    conn = sqlite3.connect(temp_datalake["db"])
    cursor = conn.cursor()
    cursor.execute("SELECT file_path FROM audio ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()

    file_path = temp_datalake["data_dir"] / row[0]
    assert file_path.exists()

    # Check permissions (should be 644)
    stat_info = file_path.stat()
    permissions = oct(stat_info.st_mode)[-3:]
    assert permissions == "644"


def test_ingest_multiple_audio_files(temp_datalake, sample_audio_file, tmp_path):
    """Test ingesting multiple audio files."""
    env = os.environ.copy()
    env["DATA_DIR"] = str(temp_datalake["data_dir"])
    env["DB_FILE"] = str(temp_datalake["db"])
    env["LOG_DIR"] = str(temp_datalake["logs_dir"])

    script_path = Path(__file__).parent.parent / "scripts" / "ingest-audio.sh"

    # Create multiple audio files
    audio_files = []
    for i in range(3):
        audio_file = tmp_path / f"test_{i}.wav"
        audio_file.write_bytes(sample_audio_file.read_bytes())
        audio_files.append(audio_file)

    # Ingest all files
    for audio_file in audio_files:
        result = subprocess.run(
            [str(script_path), str(audio_file), f"test,batch_{audio_file.stem}"],
            cwd=str(temp_datalake["root"]),
            env=env,
            capture_output=True,
            text=True
        )
        assert result.returncode == 0

    # Verify all files in database
    conn = sqlite3.connect(temp_datalake["db"])
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM audio")
    count = cursor.fetchone()[0]
    conn.close()

    assert count == 3


def test_logging_created(temp_datalake, sample_audio_file):
    """Test that ingestion creates log files."""
    env = os.environ.copy()
    env["DATA_DIR"] = str(temp_datalake["data_dir"])
    env["DB_FILE"] = str(temp_datalake["db"])
    env["LOG_DIR"] = str(temp_datalake["logs_dir"])

    script_path = Path(__file__).parent.parent / "scripts" / "ingest-audio.sh"
    subprocess.run(
        [str(script_path), str(sample_audio_file)],
        cwd=str(temp_datalake["root"]),
        env=env,
        capture_output=True,
        text=True
    )

    # Check log file exists
    log_file = temp_datalake["logs_dir"] / "ingest-audio.log"
    assert log_file.exists()

    # Check log content
    log_content = log_file.read_text()
    assert "[INFO]" in log_content
    assert "Starting ingestion" in log_content
