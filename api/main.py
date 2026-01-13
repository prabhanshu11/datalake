"""Datalake REST API - Minimal server for network access"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any, Optional
from datetime import datetime

from .database import get_db, dict_from_row

app = FastAPI(
    title="Datalake API",
    description="REST API for audio, transcripts, and screenshots",
    version="0.1.0"
)

# Enable CORS for desktop access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for local network access
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Datalake API",
        "version": "0.1.0",
        "endpoints": {
            "health": "/health",
            "audio": "/api/v1/audio",
            "transcripts": "/api/v1/transcripts",
            "screenshots": "/api/v1/screenshots",
            "stats": "/api/v1/stats"
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        with get_db() as conn:
            cursor = conn.execute("SELECT 1")
            cursor.fetchone()
        return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {str(e)}")


@app.get("/api/v1/audio")
async def list_audio(
    limit: int = 10,
    offset: int = 0,
    tags: Optional[str] = None
) -> List[Dict[str, Any]]:
    """List audio files with optional filtering"""
    try:
        with get_db() as conn:
            query = "SELECT * FROM audio"
            params = []

            if tags:
                query += " WHERE tags LIKE ?"
                params.append(f"%{tags}%")

            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            return [dict_from_row(row) for row in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/audio/{audio_id}")
async def get_audio(audio_id: int) -> Dict[str, Any]:
    """Get audio file by ID"""
    try:
        with get_db() as conn:
            cursor = conn.execute("SELECT * FROM audio WHERE id = ?", (audio_id,))
            row = cursor.fetchone()

            if not row:
                raise HTTPException(status_code=404, detail="Audio file not found")

            return dict_from_row(row)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/transcripts")
async def list_transcripts(
    limit: int = 10,
    offset: int = 0,
    tags: Optional[str] = None
) -> List[Dict[str, Any]]:
    """List transcripts with optional filtering"""
    try:
        with get_db() as conn:
            query = "SELECT * FROM transcripts"
            params = []

            if tags:
                query += " WHERE tags LIKE ?"
                params.append(f"%{tags}%")

            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            return [dict_from_row(row) for row in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/transcripts/{transcript_id}")
async def get_transcript(transcript_id: int) -> Dict[str, Any]:
    """Get transcript by ID"""
    try:
        with get_db() as conn:
            cursor = conn.execute("SELECT * FROM transcripts WHERE id = ?", (transcript_id,))
            row = cursor.fetchone()

            if not row:
                raise HTTPException(status_code=404, detail="Transcript not found")

            return dict_from_row(row)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/screenshots")
async def list_screenshots(
    limit: int = 10,
    offset: int = 0,
    tags: Optional[str] = None
) -> List[Dict[str, Any]]:
    """List screenshots with optional filtering"""
    try:
        with get_db() as conn:
            query = "SELECT * FROM screenshots"
            params = []

            if tags:
                query += " WHERE tags LIKE ?"
                params.append(f"%{tags}%")

            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            return [dict_from_row(row) for row in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/screenshots/{screenshot_id}")
async def get_screenshot(screenshot_id: int) -> Dict[str, Any]:
    """Get screenshot by ID"""
    try:
        with get_db() as conn:
            cursor = conn.execute("SELECT * FROM screenshots WHERE id = ?", (screenshot_id,))
            row = cursor.fetchone()

            if not row:
                raise HTTPException(status_code=404, detail="Screenshot not found")

            return dict_from_row(row)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/search/transcripts")
async def search_transcripts(q: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Full-text search on transcripts using FTS5"""
    if not q:
        raise HTTPException(status_code=400, detail="Search query 'q' is required")

    try:
        with get_db() as conn:
            query = """
                SELECT
                    t.*,
                    snippet(transcripts_fts, 0, '>>>', '<<<', '...', 40) as snippet
                FROM transcripts t
                JOIN transcripts_fts ON t.id = transcripts_fts.rowid
                WHERE transcripts_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """
            cursor = conn.execute(query, (q, limit))
            rows = cursor.fetchall()

            return [dict_from_row(row) for row in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/stats")
async def get_stats() -> Dict[str, Any]:
    """Get database statistics"""
    try:
        with get_db() as conn:
            # Audio stats
            cursor = conn.execute("""
                SELECT
                    COUNT(*) as total_files,
                    COALESCE(SUM(duration_seconds), 0) as total_duration,
                    COALESCE(SUM(size_bytes), 0) as total_size
                FROM audio
            """)
            audio_stats = dict_from_row(cursor.fetchone())

            # Transcript stats
            cursor = conn.execute("""
                SELECT
                    COUNT(*) as total_files,
                    COALESCE(SUM(word_count), 0) as total_words,
                    COALESCE(SUM(size_bytes), 0) as total_size
                FROM transcripts
            """)
            transcript_stats = dict_from_row(cursor.fetchone())

            # Screenshot stats
            cursor = conn.execute("""
                SELECT
                    COUNT(*) as total_files,
                    COALESCE(SUM(size_bytes), 0) as total_size
                FROM screenshots
            """)
            screenshot_stats = dict_from_row(cursor.fetchone())

            return {
                "audio": audio_stats,
                "transcripts": transcript_stats,
                "screenshots": screenshot_stats
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Memory Monitoring Endpoints
# =============================================================================

@app.get("/api/v1/memory/metrics/today")
async def get_memory_metrics_today() -> List[Dict[str, Any]]:
    """Get today's memory metrics for charting"""
    try:
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT pid, session_id, rss_mb, memory_rate_mb_min,
                       timestamp, timestamp_unix
                FROM memory_metrics
                WHERE date(timestamp) = date('now', 'localtime')
                ORDER BY timestamp_unix ASC
            """)
            rows = cursor.fetchall()
            return [dict_from_row(row) for row in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/memory/metrics/range")
async def get_memory_metrics_range(
    start: str,
    end: str,
    limit: int = 10000
) -> List[Dict[str, Any]]:
    """Get memory metrics for a date range"""
    try:
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT pid, session_id, rss_mb, memory_rate_mb_min,
                       timestamp, timestamp_unix
                FROM memory_metrics
                WHERE date(timestamp) >= ? AND date(timestamp) <= ?
                ORDER BY timestamp_unix ASC
                LIMIT ?
            """, (start, end, limit))
            rows = cursor.fetchall()
            return [dict_from_row(row) for row in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/memory/events/today")
async def get_memory_events_today() -> List[Dict[str, Any]]:
    """Get today's memory events"""
    try:
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT event_type, pid, session_id, severity,
                       message, details, timestamp, timestamp_unix
                FROM memory_events
                WHERE date(timestamp) = date('now', 'localtime')
                ORDER BY timestamp_unix DESC
            """)
            rows = cursor.fetchall()
            return [dict_from_row(row) for row in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/memory/events/range")
async def get_memory_events_range(
    start: str,
    end: str,
    event_type: Optional[str] = None,
    limit: int = 1000
) -> List[Dict[str, Any]]:
    """Get memory events for a date range"""
    try:
        with get_db() as conn:
            query = """
                SELECT event_type, pid, session_id, severity,
                       message, details, timestamp, timestamp_unix
                FROM memory_events
                WHERE date(timestamp) >= ? AND date(timestamp) <= ?
            """
            params = [start, end]

            if event_type:
                query += " AND event_type = ?"
                params.append(event_type)

            query += " ORDER BY timestamp_unix DESC LIMIT ?"
            params.append(limit)

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            return [dict_from_row(row) for row in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/memory/sessions")
async def get_memory_sessions() -> List[Dict[str, Any]]:
    """Get list of Claude sessions with current memory info"""
    try:
        with get_db() as conn:
            # Get latest metrics for each PID (active sessions)
            cursor = conn.execute("""
                SELECT m.pid, m.session_id, m.rss_mb, m.memory_rate_mb_min as rate,
                       m.command, m.timestamp, m.source_device
                FROM memory_metrics m
                INNER JOIN (
                    SELECT pid, MAX(timestamp_unix) as max_ts
                    FROM memory_metrics
                    WHERE timestamp_unix > (strftime('%s', 'now') - 3600)
                    GROUP BY pid
                ) latest ON m.pid = latest.pid AND m.timestamp_unix = latest.max_ts
                ORDER BY m.rss_mb DESC
            """)
            rows = cursor.fetchall()
            return [dict_from_row(row) for row in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/memory/sessions/{pid}/low-memory-mode")
async def toggle_low_memory_mode(pid: int, enabled: bool = True) -> Dict[str, Any]:
    """Toggle low-memory mode for a specific Claude session"""
    import os
    from pathlib import Path

    try:
        # Write to control file that hooks can read
        control_dir = Path("/var/log/claude-memory/low-memory-mode")
        control_dir.mkdir(parents=True, exist_ok=True)

        control_file = control_dir / str(pid)

        if enabled:
            control_file.write_text("1")
        else:
            if control_file.exists():
                control_file.unlink()

        return {"success": True, "pid": pid, "low_memory_mode": enabled}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
