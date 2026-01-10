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
