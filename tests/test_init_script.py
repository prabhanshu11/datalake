"""Tests for initialization script."""
import os
import subprocess
import tempfile
import shutil
from pathlib import Path
import sqlite3
import pytest


def test_init_script_exists():
    """Test that the init.sh script exists and is executable."""
    script_path = Path(__file__).parent.parent / "scripts" / "init.sh"
    assert script_path.exists()
    assert os.access(script_path, os.X_OK)


def test_init_creates_database():
    """Test that init.sh creates the database."""
    # Create temporary directory
    temp_dir = tempfile.mkdtemp(prefix="datalake_init_test_")
    temp_path = Path(temp_dir)

    try:
        # Copy schema file
        project_root = Path(__file__).parent.parent
        schema_src = project_root / "schema.sql"
        schema_dst = temp_path / "schema.sql"
        shutil.copy(schema_src, schema_dst)

        # Create necessary directories
        (temp_path / "scripts").mkdir()
        (temp_path / "logs").mkdir()

        # Set environment
        env = os.environ.copy()
        env["PROJECT_ROOT"] = str(temp_path)
        env["DATA_DIR"] = str(temp_path / "data")
        env["DB_FILE"] = str(temp_path / "datalake.db")
        env["LOG_DIR"] = str(temp_path / "logs")
        env["SCHEMA_FILE"] = str(temp_path / "schema.sql")

        # Run init script
        script_path = project_root / "scripts" / "init.sh"
        result = subprocess.run(
            [str(script_path)],
            cwd=str(temp_path),
            env=env,
            capture_output=True,
            text=True
        )

        # Check script succeeded
        assert result.returncode == 0, f"Script failed: {result.stderr}"

        # Check database exists
        db_file = temp_path / "datalake.db"
        assert db_file.exists()

        # Verify database has tables
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()

        assert "audio" in tables
        assert "transcripts" in tables
        assert "screenshots" in tables

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_init_creates_directories():
    """Test that init.sh creates data directory structure."""
    temp_dir = tempfile.mkdtemp(prefix="datalake_init_test_")
    temp_path = Path(temp_dir)

    try:
        # Copy schema file
        project_root = Path(__file__).parent.parent
        schema_src = project_root / "schema.sql"
        schema_dst = temp_path / "schema.sql"
        shutil.copy(schema_src, schema_dst)

        (temp_path / "scripts").mkdir()
        (temp_path / "logs").mkdir()

        env = os.environ.copy()
        env["PROJECT_ROOT"] = str(temp_path)
        env["DATA_DIR"] = str(temp_path / "data")
        env["DB_FILE"] = str(temp_path / "datalake.db")
        env["LOG_DIR"] = str(temp_path / "logs")
        env["SCHEMA_FILE"] = str(temp_path / "schema.sql")

        script_path = project_root / "scripts" / "init.sh"
        result = subprocess.run(
            [str(script_path)],
            cwd=str(temp_path),
            env=env,
            capture_output=True,
            text=True
        )

        assert result.returncode == 0

        # Check directory structure
        data_dir = temp_path / "data"
        assert data_dir.exists()
        assert (data_dir / "audio").exists()
        assert (data_dir / "transcripts").exists()
        assert (data_dir / "screenshots").exists()

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_init_sets_permissions():
    """Test that init.sh sets correct permissions."""
    temp_dir = tempfile.mkdtemp(prefix="datalake_init_test_")
    temp_path = Path(temp_dir)

    try:
        project_root = Path(__file__).parent.parent
        schema_src = project_root / "schema.sql"
        schema_dst = temp_path / "schema.sql"
        shutil.copy(schema_src, schema_dst)

        (temp_path / "scripts").mkdir()
        (temp_path / "logs").mkdir()

        env = os.environ.copy()
        env["PROJECT_ROOT"] = str(temp_path)
        env["DATA_DIR"] = str(temp_path / "data")
        env["DB_FILE"] = str(temp_path / "datalake.db")
        env["LOG_DIR"] = str(temp_path / "logs")
        env["SCHEMA_FILE"] = str(temp_path / "schema.sql")

        script_path = project_root / "scripts" / "init.sh"
        subprocess.run(
            [str(script_path)],
            cwd=str(temp_path),
            env=env,
            capture_output=True,
            text=True
        )

        # Check database file permissions (should be 644)
        db_file = temp_path / "datalake.db"
        if db_file.exists():
            stat_info = db_file.stat()
            permissions = oct(stat_info.st_mode)[-3:]
            assert permissions == "644"

        # Check directory permissions (should be 755)
        data_dir = temp_path / "data"
        if data_dir.exists():
            stat_info = data_dir.stat()
            permissions = oct(stat_info.st_mode)[-3:]
            assert permissions == "755"

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_init_creates_log():
    """Test that init.sh creates a log file."""
    temp_dir = tempfile.mkdtemp(prefix="datalake_init_test_")
    temp_path = Path(temp_dir)

    try:
        project_root = Path(__file__).parent.parent
        schema_src = project_root / "schema.sql"
        schema_dst = temp_path / "schema.sql"
        shutil.copy(schema_src, schema_dst)

        (temp_path / "scripts").mkdir()
        (temp_path / "logs").mkdir()

        env = os.environ.copy()
        env["PROJECT_ROOT"] = str(temp_path)
        env["DATA_DIR"] = str(temp_path / "data")
        env["DB_FILE"] = str(temp_path / "datalake.db")
        env["LOG_DIR"] = str(temp_path / "logs")
        env["SCHEMA_FILE"] = str(temp_path / "schema.sql")

        script_path = project_root / "scripts" / "init.sh"
        subprocess.run(
            [str(script_path)],
            cwd=str(temp_path),
            env=env,
            capture_output=True,
            text=True
        )

        # Check log file
        log_file = temp_path / "logs" / "init.log"
        assert log_file.exists()

        log_content = log_file.read_text()
        assert "[INFO]" in log_content
        assert "initialization" in log_content.lower()

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_init_schema_missing():
    """Test that init.sh fails gracefully when schema is missing."""
    temp_dir = tempfile.mkdtemp(prefix="datalake_init_test_")
    temp_path = Path(temp_dir)

    try:
        (temp_path / "scripts").mkdir()
        (temp_path / "logs").mkdir()

        env = os.environ.copy()
        env["PROJECT_ROOT"] = str(temp_path)
        env["DATA_DIR"] = str(temp_path / "data")
        env["DB_FILE"] = str(temp_path / "datalake.db")
        env["LOG_DIR"] = str(temp_path / "logs")
        env["SCHEMA_FILE"] = str(temp_path / "schema.sql")

        project_root = Path(__file__).parent.parent
        script_path = project_root / "scripts" / "init.sh"
        result = subprocess.run(
            [str(script_path)],
            cwd=str(temp_path),
            env=env,
            capture_output=True,
            text=True
        )

        assert result.returncode == 1
        assert "Schema file not found" in result.stdout or "not found" in result.stdout.lower()

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
