#!/usr/bin/env python3
"""
Voice Typing Parser

Parses voice recordings and transcripts from:
- ~/Programs/recordings/ (audio files)
- ~/Programs/transcripts/ (transcript text files)
- ~/Programs/omarchy-voice-typing/recordings/ (project-specific)
- ~/Programs/omarchy-voice-typing/transcripts/ (project-specific)

Links audio to transcripts by timestamp proximity.
"""

import os
import re
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Iterator
import logging

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class AudioFile:
    """Represents an audio recording."""
    file_path: str
    filename: str
    original_filename: str
    timestamp: datetime
    duration_seconds: Optional[float]
    format: str
    sample_rate: Optional[int]
    channels: Optional[int]
    size_bytes: int
    source_project: str


@dataclass
class TranscriptFile:
    """Represents a transcript."""
    file_path: str
    filename: str
    content: str
    word_count: int
    session_uuid: str
    timestamp: datetime
    size_bytes: int
    source_project: str


@dataclass
class VoiceSession:
    """Linked audio + transcript session."""
    audio: Optional[AudioFile]
    transcript: Optional[TranscriptFile]
    source_device: str
    success: bool
    created_at: datetime


class VoiceParser:
    """Parser for voice typing data."""

    # Patterns for filenames
    AUDIO_PATTERN = re.compile(r'^(\d{8})_(\d{6})_(.+)\.(wav|mp3|flac)$')
    TRANSCRIPT_PATTERN = re.compile(r'^(\d{8})_(\d{6})_([a-f0-9-]+)\.txt$')

    def __init__(self, source_device: str = "unknown"):
        self.source_device = source_device
        self.audio_dirs = [
            Path.home() / "Programs" / "recordings",
            Path.home() / "Programs" / "omarchy-voice-typing" / "recordings",
        ]
        self.transcript_dirs = [
            Path.home() / "Programs" / "transcripts",
            Path.home() / "Programs" / "omarchy-voice-typing" / "transcripts",
        ]

    def _parse_timestamp(self, date_str: str, time_str: str) -> datetime:
        """Parse YYYYMMDD_HHMMSS to datetime."""
        return datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")

    def _get_audio_duration(self, filepath: Path) -> Optional[float]:
        """Get audio duration using ffprobe."""
        try:
            result = subprocess.run(
                ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', str(filepath)],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return float(result.stdout.strip())
        except:
            pass
        return None

    def _get_audio_metadata(self, filepath: Path) -> dict:
        """Get audio metadata using ffprobe."""
        metadata = {'sample_rate': None, 'channels': None}
        try:
            result = subprocess.run(
                ['ffprobe', '-v', 'quiet', '-show_entries',
                 'stream=sample_rate,channels', '-of', 'csv=p=0',
                 str(filepath)],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split(',')
                if len(parts) >= 2:
                    metadata['sample_rate'] = int(parts[0]) if parts[0] else None
                    metadata['channels'] = int(parts[1]) if parts[1] else None
        except:
            pass
        return metadata

    def scan_audio(self) -> Iterator[AudioFile]:
        """Scan all audio directories."""
        for audio_dir in self.audio_dirs:
            if not audio_dir.exists():
                continue

            source_project = audio_dir.parent.name if 'omarchy' in str(audio_dir) else 'recordings'
            logger.info(f"Scanning audio: {audio_dir}")

            for filepath in audio_dir.iterdir():
                if not filepath.is_file():
                    continue

                match = self.AUDIO_PATTERN.match(filepath.name)
                if not match:
                    continue

                date_str, time_str, name_part, fmt = match.groups()
                timestamp = self._parse_timestamp(date_str, time_str)

                duration = self._get_audio_duration(filepath)
                metadata = self._get_audio_metadata(filepath)

                yield AudioFile(
                    file_path=str(filepath),
                    filename=filepath.name,
                    original_filename=f"{name_part}.{fmt}",
                    timestamp=timestamp,
                    duration_seconds=duration,
                    format=fmt,
                    sample_rate=metadata['sample_rate'],
                    channels=metadata['channels'],
                    size_bytes=filepath.stat().st_size,
                    source_project=source_project
                )

    def scan_transcripts(self) -> Iterator[TranscriptFile]:
        """Scan all transcript directories."""
        for transcript_dir in self.transcript_dirs:
            if not transcript_dir.exists():
                continue

            source_project = transcript_dir.parent.name if 'omarchy' in str(transcript_dir) else 'transcripts'
            logger.info(f"Scanning transcripts: {transcript_dir}")

            for filepath in transcript_dir.iterdir():
                if not filepath.is_file():
                    continue

                match = self.TRANSCRIPT_PATTERN.match(filepath.name)
                if not match:
                    continue

                date_str, time_str, session_uuid = match.groups()
                timestamp = self._parse_timestamp(date_str, time_str)

                try:
                    content = filepath.read_text(encoding='utf-8').strip()
                except:
                    content = ""

                word_count = len(content.split()) if content else 0

                yield TranscriptFile(
                    file_path=str(filepath),
                    filename=filepath.name,
                    content=content,
                    word_count=word_count,
                    session_uuid=session_uuid,
                    timestamp=timestamp,
                    size_bytes=filepath.stat().st_size,
                    source_project=source_project
                )

    def link_sessions(self, max_time_diff_seconds: int = 60) -> Iterator[VoiceSession]:
        """Link audio files to transcripts by timestamp proximity."""
        # Collect all audio and transcripts
        audio_files = list(self.scan_audio())
        transcript_files = list(self.scan_transcripts())

        logger.info(f"Found {len(audio_files)} audio, {len(transcript_files)} transcripts")

        # Sort by timestamp
        audio_files.sort(key=lambda x: x.timestamp)
        transcript_files.sort(key=lambda x: x.timestamp)

        # Track used transcripts
        used_transcripts = set()

        for audio in audio_files:
            best_match = None
            best_diff = timedelta(seconds=max_time_diff_seconds + 1)

            for transcript in transcript_files:
                if transcript.file_path in used_transcripts:
                    continue

                diff = abs(transcript.timestamp - audio.timestamp)
                if diff < best_diff and diff <= timedelta(seconds=max_time_diff_seconds):
                    best_diff = diff
                    best_match = transcript

            if best_match:
                used_transcripts.add(best_match.file_path)

            yield VoiceSession(
                audio=audio,
                transcript=best_match,
                source_device=self.source_device,
                success=best_match is not None and best_match.word_count > 0,
                created_at=audio.timestamp
            )

        # Orphan transcripts (no matching audio)
        for transcript in transcript_files:
            if transcript.file_path not in used_transcripts:
                yield VoiceSession(
                    audio=None,
                    transcript=transcript,
                    source_device=self.source_device,
                    success=transcript.word_count > 0,
                    created_at=transcript.timestamp
                )

    def get_stats(self) -> dict:
        """Get statistics about available data."""
        audio_count = sum(1 for _ in self.scan_audio())
        transcript_count = sum(1 for _ in self.scan_transcripts())
        return {
            'audio_files': audio_count,
            'transcripts': transcript_count,
        }


class VoiceIngester:
    """Ingest voice data into datalake."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)

    def ingest_session(self, session: VoiceSession) -> Optional[int]:
        """Ingest a voice session."""
        cursor = self.conn.cursor()

        audio_id = None
        transcript_id = None

        # Insert audio if present
        if session.audio:
            cursor.execute('''
                INSERT OR IGNORE INTO audio
                (file_path, filename, original_filename, duration_seconds,
                 format, sample_rate, channels, size_bytes, source_device,
                 source_project, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                session.audio.file_path,
                session.audio.filename,
                session.audio.original_filename,
                session.audio.duration_seconds,
                session.audio.format,
                session.audio.sample_rate,
                session.audio.channels,
                session.audio.size_bytes,
                session.source_device,
                session.audio.source_project,
                session.audio.timestamp.isoformat()
            ))
            if cursor.rowcount > 0:
                audio_id = cursor.lastrowid
            else:
                cursor.execute('SELECT id FROM audio WHERE file_path = ?',
                             (session.audio.file_path,))
                row = cursor.fetchone()
                audio_id = row[0] if row else None

        # Insert transcript if present
        if session.transcript:
            cursor.execute('''
                INSERT OR IGNORE INTO transcripts
                (file_path, filename, audio_id, content, word_count,
                 size_bytes, source_device, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                session.transcript.file_path,
                session.transcript.filename,
                audio_id,
                session.transcript.content,
                session.transcript.word_count,
                session.transcript.size_bytes,
                session.source_device,
                session.transcript.timestamp.isoformat()
            ))
            if cursor.rowcount > 0:
                transcript_id = cursor.lastrowid
            else:
                cursor.execute('SELECT id FROM transcripts WHERE file_path = ?',
                             (session.transcript.file_path,))
                row = cursor.fetchone()
                transcript_id = row[0] if row else None

        # Insert voice session
        cursor.execute('''
            INSERT OR IGNORE INTO voice_sessions
            (audio_id, transcript_id, session_uuid, source_device, success, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            audio_id,
            transcript_id,
            session.transcript.session_uuid if session.transcript else None,
            session.source_device,
            1 if session.success else 0,
            session.created_at.isoformat()
        ))

        self.conn.commit()
        return cursor.lastrowid if cursor.rowcount > 0 else None

    def close(self):
        self.conn.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Parse voice typing data')
    parser.add_argument('--device', '-d', default='desktop', help='Source device')
    parser.add_argument('--db', '-b', default='~/Programs/datalake/datalake.db', help='Database path')
    parser.add_argument('--stats-only', '-s', action='store_true', help='Only show stats')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    voice_parser = VoiceParser(args.device)

    # Show stats
    stats = voice_parser.get_stats()
    print(f"\nVoice Typing Statistics for {args.device}:")
    print(f"  Audio files: {stats['audio_files']}")
    print(f"  Transcripts: {stats['transcripts']}")

    if args.stats_only:
        return

    # Ingest
    db_path = os.path.expanduser(args.db)
    print(f"\nIngesting into: {db_path}")

    ingester = VoiceIngester(db_path)

    session_count = 0
    for session in voice_parser.link_sessions():
        result = ingester.ingest_session(session)
        if result:
            session_count += 1
            if args.verbose:
                audio_name = session.audio.filename if session.audio else 'no-audio'
                transcript_words = session.transcript.word_count if session.transcript else 0
                print(f"  {audio_name} -> {transcript_words} words")

    print(f"  Ingested {session_count} voice sessions")
    ingester.close()
    print("\nDone!")


if __name__ == '__main__':
    main()
