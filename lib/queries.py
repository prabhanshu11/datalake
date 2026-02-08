#!/usr/bin/env python3
"""
Datalake query library for fast conversation search.

This module provides high-performance queries against the datalake SQLite database
using FTS5 full-text search instead of filesystem grep.

Usage:
    from datalake.lib.queries import DatalakeQueries

    dq = DatalakeQueries()
    sessions = dq.search_conversations("star trek", limit=10)
    messages = dq.get_session_messages("abc123-uuid")
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class SessionResult:
    session_id: str
    project_path: str
    started_at: str
    ended_at: Optional[str]
    summary: Optional[str]
    total_messages: int
    model_primary: Optional[str]
    source_device: str
    duration_seconds: Optional[int]


@dataclass
class MessageResult:
    message_uuid: str
    message_type: str
    role: Optional[str]
    content_text: Optional[str]
    content_thinking: Optional[str]
    timestamp: str
    model: Optional[str]


@dataclass
class HistoryResult:
    session_id: str
    display: str
    project: str
    timestamp: str


class DatalakeQueries:
    """Fast conversation queries using FTS5."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or Path.home() / "Programs" / "datalake" / "datalake.db"
        self._conn: Optional[sqlite3.Connection] = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def search_conversations(
        self,
        query: str,
        limit: int = 20,
        since: Optional[str] = None,
        until: Optional[str] = None,
        project: Optional[str] = None,
        search_messages: bool = True,
    ) -> list[SessionResult]:
        """
        Search for conversations by keyword using FTS5.

        Args:
            query: Search query (FTS5 syntax supported)
            limit: Maximum results to return
            since: Only sessions after this date (YYYY-MM-DD)
            until: Only sessions before this date (YYYY-MM-DD)
            project: Filter by project path (partial match)
            search_messages: If True, search message content; if False, search history only

        Returns:
            List of matching sessions sorted by date (newest first)
        """
        conn = self._get_conn()

        if search_messages:
            # Search in message content using FTS5
            sql = """
                SELECT DISTINCT
                    cs.session_id,
                    cs.project_path,
                    cs.started_at,
                    cs.ended_at,
                    cs.summary,
                    cs.total_messages,
                    cs.model_primary,
                    cs.source_device,
                    cs.duration_seconds
                FROM claude_sessions cs
                WHERE cs.id IN (
                    SELECT DISTINCT cm.session_id
                    FROM claude_messages cm
                    JOIN claude_messages_fts ON cm.id = claude_messages_fts.rowid
                    WHERE claude_messages_fts MATCH ?
                )
            """
        else:
            # Search in history (user prompts only)
            sql = """
                SELECT DISTINCT
                    cs.session_id,
                    cs.project_path,
                    cs.started_at,
                    cs.ended_at,
                    cs.summary,
                    cs.total_messages,
                    cs.model_primary,
                    cs.source_device,
                    cs.duration_seconds
                FROM claude_sessions cs
                WHERE cs.session_id IN (
                    SELECT DISTINCT ch.session_id
                    FROM claude_history ch
                    JOIN claude_history_fts ON ch.id = claude_history_fts.rowid
                    WHERE claude_history_fts MATCH ?
                )
            """

        params = [query]

        # Add filters
        filters = []
        if since:
            filters.append("cs.started_at >= ?")
            params.append(since)
        if until:
            filters.append("cs.started_at <= ?")
            params.append(until)
        if project:
            filters.append("cs.project_path LIKE ?")
            params.append(f"%{project}%")

        if filters:
            sql += " AND " + " AND ".join(filters)

        sql += " ORDER BY cs.started_at DESC LIMIT ?"
        params.append(limit)

        cursor = conn.execute(sql, params)
        results = []
        for row in cursor:
            results.append(SessionResult(
                session_id=row["session_id"],
                project_path=row["project_path"] or "",
                started_at=row["started_at"] or "",
                ended_at=row["ended_at"],
                summary=row["summary"],
                total_messages=row["total_messages"] or 0,
                model_primary=row["model_primary"],
                source_device=row["source_device"] or "",
                duration_seconds=row["duration_seconds"],
            ))

        return results

    def get_session_metadata(self, session_id: str) -> Optional[SessionResult]:
        """Get metadata for a specific session."""
        conn = self._get_conn()

        cursor = conn.execute("""
            SELECT
                session_id, project_path, started_at, ended_at, summary,
                total_messages, model_primary, source_device, duration_seconds
            FROM claude_sessions
            WHERE session_id = ?
        """, (session_id,))

        row = cursor.fetchone()
        if not row:
            return None

        return SessionResult(
            session_id=row["session_id"],
            project_path=row["project_path"] or "",
            started_at=row["started_at"] or "",
            ended_at=row["ended_at"],
            summary=row["summary"],
            total_messages=row["total_messages"] or 0,
            model_primary=row["model_primary"],
            source_device=row["source_device"] or "",
            duration_seconds=row["duration_seconds"],
        )

    def get_session_messages(
        self,
        session_id: str,
        limit: Optional[int] = None,
        offset: int = 0,
        message_types: Optional[list[str]] = None,
    ) -> list[MessageResult]:
        """
        Get messages for a specific session.

        Args:
            session_id: Session UUID
            limit: Maximum messages to return (None for all)
            offset: Skip first N messages
            message_types: Filter by message types (e.g., ['user', 'assistant'])

        Returns:
            List of messages in chronological order
        """
        conn = self._get_conn()

        sql = """
            SELECT
                cm.message_uuid, cm.message_type, cm.role,
                cm.content_text, cm.content_thinking,
                cm.timestamp, cm.model
            FROM claude_messages cm
            JOIN claude_sessions cs ON cm.session_id = cs.id
            WHERE cs.session_id = ?
        """
        params = [session_id]

        if message_types:
            placeholders = ",".join("?" * len(message_types))
            sql += f" AND cm.message_type IN ({placeholders})"
            params.extend(message_types)

        sql += " ORDER BY cm.timestamp ASC"

        if limit:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])

        cursor = conn.execute(sql, params)
        results = []
        for row in cursor:
            results.append(MessageResult(
                message_uuid=row["message_uuid"],
                message_type=row["message_type"],
                role=row["role"],
                content_text=row["content_text"],
                content_thinking=row["content_thinking"],
                timestamp=row["timestamp"],
                model=row["model"],
            ))

        return results

    def get_user_prompts(self, session_id: str, limit: int = 20) -> list[HistoryResult]:
        """Get user prompts from history for a session."""
        conn = self._get_conn()

        cursor = conn.execute("""
            SELECT session_id, display, project, timestamp
            FROM claude_history
            WHERE session_id = ?
            ORDER BY timestamp_unix ASC
            LIMIT ?
        """, (session_id, limit))

        results = []
        for row in cursor:
            results.append(HistoryResult(
                session_id=row["session_id"],
                display=row["display"],
                project=row["project"],
                timestamp=row["timestamp"],
            ))

        return results

    def get_recent_sessions(self, limit: int = 10) -> list[SessionResult]:
        """Get the most recent sessions."""
        conn = self._get_conn()

        cursor = conn.execute("""
            SELECT
                session_id, project_path, started_at, ended_at, summary,
                total_messages, model_primary, source_device, duration_seconds
            FROM claude_sessions
            ORDER BY started_at DESC
            LIMIT ?
        """, (limit,))

        results = []
        for row in cursor:
            results.append(SessionResult(
                session_id=row["session_id"],
                project_path=row["project_path"] or "",
                started_at=row["started_at"] or "",
                ended_at=row["ended_at"],
                summary=row["summary"],
                total_messages=row["total_messages"] or 0,
                model_primary=row["model_primary"],
                source_device=row["source_device"] or "",
                duration_seconds=row["duration_seconds"],
            ))

        return results

    def get_stats(self) -> dict:
        """Get database statistics."""
        conn = self._get_conn()

        stats = {}
        for table in ["claude_sessions", "claude_messages", "claude_history"]:
            cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
            stats[table] = cursor.fetchone()[0]

        cursor = conn.execute("""
            SELECT GROUP_CONCAT(DISTINCT source_device) FROM claude_sessions
        """)
        stats["devices"] = cursor.fetchone()[0]

        return stats
