"""Database connection management"""
import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager


def get_db_path() -> Path:
    """Get database file path from environment"""
    db_file = os.environ.get("DB_FILE", "/data/datalake.db")
    return Path(db_file)


@contextmanager
def get_db():
    """Get database connection with WAL mode enabled"""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def dict_from_row(row: sqlite3.Row) -> dict:
    """Convert sqlite3.Row to dictionary"""
    return {key: row[key] for key in row.keys()}
