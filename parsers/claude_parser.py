#!/usr/bin/env python3
"""
Claude Code Conversation Parser

Parses Claude Code conversation data from:
- ~/.claude/history.jsonl (user prompt history)
- ~/.claude/projects/{project}/session.jsonl (full conversations)
- ~/.claude/projects/{project}/agent-*.jsonl (subagent conversations)

Designed for ingestion into the datalake database.
"""

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Iterator, Any
import re
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S%z'
)
logger = logging.getLogger(__name__)


@dataclass
class ClaudeMessage:
    """Represents a parsed Claude message."""
    message_uuid: str
    parent_uuid: Optional[str]
    message_type: str  # 'user', 'assistant', 'summary', 'snapshot'
    user_type: Optional[str]
    role: Optional[str]
    model: Optional[str]
    content_text: str
    content_thinking: str
    content_images: int
    content_tool_uses: int
    content_tool_results: int
    is_sidechain: bool
    cwd: Optional[str]
    git_branch: Optional[str]
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    stop_reason: Optional[str]
    request_id: Optional[str]
    timestamp: str
    sequence_number: int
    todos: str
    metadata: str


@dataclass
class ClaudeSession:
    """Represents a parsed Claude session."""
    session_id: str
    project_path: str
    project_encoded: str
    summary: Optional[str]
    model_primary: Optional[str]
    claude_version: Optional[str]
    git_branch: Optional[str]
    total_messages: int
    user_messages: int
    assistant_messages: int
    total_input_tokens: int
    total_output_tokens: int
    total_cache_read_tokens: int
    total_cache_creation_tokens: int
    source_device: str
    source_file: str
    started_at: str
    ended_at: Optional[str]
    duration_seconds: Optional[float]
    messages: list[ClaudeMessage] = field(default_factory=list)
    subagents: list[dict] = field(default_factory=list)


@dataclass
class ClaudeHistoryEntry:
    """Represents an entry from history.jsonl."""
    session_id: str
    display: str
    pasted_contents: str
    project: str
    source_device: str
    timestamp: str
    timestamp_unix: int


class ClaudeParser:
    """Parser for Claude Code conversation data."""

    def __init__(self, claude_dir: str = "~/.claude", source_device: str = "unknown"):
        self.claude_dir = Path(claude_dir).expanduser()
        self.source_device = source_device
        self.history_file = self.claude_dir / "history.jsonl"
        self.projects_dir = self.claude_dir / "projects"

    def parse_history(self) -> Iterator[ClaudeHistoryEntry]:
        """Parse history.jsonl file."""
        if not self.history_file.exists():
            logger.warning(f"History file not found: {self.history_file}")
            return

        logger.info(f"Parsing history from: {self.history_file}")

        with open(self.history_file, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                try:
                    data = json.loads(line.strip())

                    # Skip non-history entries
                    if 'display' not in data:
                        continue

                    timestamp_unix = data.get('timestamp', 0)
                    timestamp_iso = datetime.fromtimestamp(
                        timestamp_unix / 1000
                    ).isoformat() if timestamp_unix else None

                    yield ClaudeHistoryEntry(
                        session_id=data.get('sessionId', ''),
                        display=data.get('display', ''),
                        pasted_contents=json.dumps(data.get('pastedContents', {})),
                        project=data.get('project', ''),
                        source_device=self.source_device,
                        timestamp=timestamp_iso,
                        timestamp_unix=timestamp_unix
                    )
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse history line {line_num}: {e}")
                except Exception as e:
                    logger.error(f"Error processing history line {line_num}: {e}")

    def _extract_content(self, message: dict) -> tuple[str, str, int, int, int]:
        """Extract text, thinking, and counts from message content."""
        content = message.get('content', [])
        if isinstance(content, str):
            return content, '', 0, 0, 0

        text_parts = []
        thinking_parts = []
        image_count = 0
        tool_use_count = 0
        tool_result_count = 0

        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, dict):
                item_type = item.get('type', '')
                if item_type == 'text':
                    text_parts.append(item.get('text', ''))
                elif item_type == 'thinking':
                    thinking_parts.append(item.get('thinking', ''))
                elif item_type == 'image':
                    image_count += 1
                elif item_type == 'tool_use':
                    tool_use_count += 1
                elif item_type == 'tool_result':
                    tool_result_count += 1

        return (
            '\n'.join(text_parts),
            '\n'.join(thinking_parts),
            image_count,
            tool_use_count,
            tool_result_count
        )

    def _parse_session_file(self, session_file: Path, session_id: str,
                           project_path: str) -> Optional[ClaudeSession]:
        """Parse a single session JSONL file."""
        if not session_file.exists():
            return None

        logger.debug(f"Parsing session: {session_file}")

        messages: list[ClaudeMessage] = []
        summaries: list[str] = []
        models_used: set[str] = set()
        claude_version = None
        git_branch = None

        total_input = 0
        total_output = 0
        total_cache_read = 0
        total_cache_creation = 0
        user_count = 0
        assistant_count = 0

        timestamps: list[str] = []

        with open(session_file, 'r', encoding='utf-8') as f:
            for seq_num, line in enumerate(f, 1):
                try:
                    data = json.loads(line.strip())
                    msg_type = data.get('type', 'unknown')

                    if msg_type == 'summary':
                        summaries.append(data.get('summary', ''))
                        continue

                    if msg_type in ('user', 'assistant'):
                        # Get timestamp
                        ts = data.get('timestamp', '')
                        if ts:
                            timestamps.append(ts)

                        # Get version and branch
                        if not claude_version:
                            claude_version = data.get('version')
                        if not git_branch:
                            git_branch = data.get('gitBranch')

                        # Extract message content
                        inner_msg = data.get('message', {})
                        text, thinking, images, tools, results = self._extract_content(inner_msg)

                        # Get model
                        model = inner_msg.get('model')
                        if model:
                            models_used.add(model)

                        # Get usage
                        usage = inner_msg.get('usage', {})
                        input_tokens = usage.get('input_tokens', 0)
                        output_tokens = usage.get('output_tokens', 0)
                        cache_read = usage.get('cache_read_input_tokens', 0)
                        cache_creation = usage.get('cache_creation_input_tokens', 0)

                        total_input += input_tokens
                        total_output += output_tokens
                        total_cache_read += cache_read
                        total_cache_creation += cache_creation

                        if msg_type == 'user':
                            user_count += 1
                        else:
                            assistant_count += 1

                        msg = ClaudeMessage(
                            message_uuid=data.get('uuid', ''),
                            parent_uuid=data.get('parentUuid'),
                            message_type=msg_type,
                            user_type=data.get('userType'),
                            role=inner_msg.get('role'),
                            model=model,
                            content_text=text,
                            content_thinking=thinking,
                            content_images=images,
                            content_tool_uses=tools,
                            content_tool_results=results,
                            is_sidechain=data.get('isSidechain', False),
                            cwd=data.get('cwd'),
                            git_branch=data.get('gitBranch'),
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            cache_read_tokens=cache_read,
                            cache_creation_tokens=cache_creation,
                            stop_reason=inner_msg.get('stop_reason'),
                            request_id=data.get('requestId'),
                            timestamp=ts,
                            sequence_number=seq_num,
                            todos=json.dumps(data.get('todos', [])),
                            metadata=json.dumps(data)
                        )
                        messages.append(msg)

                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse line {seq_num} in {session_file}: {e}")
                except Exception as e:
                    logger.error(f"Error processing line {seq_num} in {session_file}: {e}")

        if not messages:
            return None

        # Calculate duration
        started_at = min(timestamps) if timestamps else None
        ended_at = max(timestamps) if timestamps else None
        duration = None
        if started_at and ended_at:
            try:
                start_dt = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
                end_dt = datetime.fromisoformat(ended_at.replace('Z', '+00:00'))
                duration = (end_dt - start_dt).total_seconds()
            except:
                pass

        # Decode project path
        project_decoded = project_path.replace('-', '/')
        if project_decoded.startswith('/'):
            pass  # Already correct
        else:
            project_decoded = '/' + project_decoded

        return ClaudeSession(
            session_id=session_id,
            project_path=project_decoded,
            project_encoded=project_path,
            summary=summaries[0] if summaries else None,
            model_primary=list(models_used)[0] if models_used else None,
            claude_version=claude_version,
            git_branch=git_branch,
            total_messages=len(messages),
            user_messages=user_count,
            assistant_messages=assistant_count,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_cache_read_tokens=total_cache_read,
            total_cache_creation_tokens=total_cache_creation,
            source_device=self.source_device,
            source_file=str(session_file),
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=duration,
            messages=messages
        )

    def parse_sessions(self) -> Iterator[ClaudeSession]:
        """Parse all session files from projects directory."""
        if not self.projects_dir.exists():
            logger.warning(f"Projects directory not found: {self.projects_dir}")
            return

        logger.info(f"Scanning projects in: {self.projects_dir}")

        for project_dir in self.projects_dir.iterdir():
            if not project_dir.is_dir():
                continue

            project_name = project_dir.name
            logger.debug(f"Processing project: {project_name}")

            # Find session files (UUID format)
            session_pattern = re.compile(
                r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.jsonl$'
            )

            for item in project_dir.iterdir():
                if not item.is_file():
                    continue

                if session_pattern.match(item.name):
                    session_id = item.stem
                    session = self._parse_session_file(item, session_id, project_name)
                    if session:
                        # Look for subagents
                        session_subdir = project_dir / session_id
                        if session_subdir.exists() and session_subdir.is_dir():
                            for subagent_file in session_subdir.glob('agent-*.jsonl'):
                                session.subagents.append({
                                    'subagent_id': subagent_file.stem,
                                    'source_file': str(subagent_file)
                                })

                        yield session

    def get_stats(self) -> dict:
        """Get statistics about available data."""
        stats = {
            'history_entries': 0,
            'sessions': 0,
            'total_messages': 0,
            'projects': set(),
        }

        # Count history entries
        if self.history_file.exists():
            with open(self.history_file, 'r') as f:
                stats['history_entries'] = sum(1 for _ in f)

        # Count sessions
        if self.projects_dir.exists():
            for project_dir in self.projects_dir.iterdir():
                if project_dir.is_dir():
                    stats['projects'].add(project_dir.name)
                    for item in project_dir.iterdir():
                        if item.is_file() and item.suffix == '.jsonl':
                            if re.match(r'^[0-9a-f]{8}-', item.name):
                                stats['sessions'] += 1

        stats['projects'] = len(stats['projects'])
        return stats


class DatalakeIngester:
    """Ingests parsed Claude data into the datalake database."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

    def ingest_history(self, entries: Iterator[ClaudeHistoryEntry]) -> int:
        """Ingest history entries into the database."""
        cursor = self.conn.cursor()
        count = 0

        for entry in entries:
            try:
                cursor.execute('''
                    INSERT OR IGNORE INTO claude_history
                    (session_id, display, pasted_contents, project, source_device,
                     timestamp, timestamp_unix)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    entry.session_id,
                    entry.display,
                    entry.pasted_contents,
                    entry.project,
                    entry.source_device,
                    entry.timestamp,
                    entry.timestamp_unix
                ))
                if cursor.rowcount > 0:
                    count += 1
            except sqlite3.Error as e:
                logger.error(f"Failed to insert history entry: {e}")

        self.conn.commit()
        logger.info(f"Ingested {count} history entries")
        return count

    def ingest_session(self, session: ClaudeSession) -> Optional[int]:
        """Ingest a session and its messages into the database."""
        cursor = self.conn.cursor()

        try:
            # Insert session
            cursor.execute('''
                INSERT OR IGNORE INTO claude_sessions
                (session_id, project_path, project_encoded, summary, model_primary,
                 claude_version, git_branch, total_messages, user_messages,
                 assistant_messages, total_input_tokens, total_output_tokens,
                 total_cache_read_tokens, total_cache_creation_tokens,
                 source_device, source_file, started_at, ended_at, duration_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                session.session_id,
                session.project_path,
                session.project_encoded,
                session.summary,
                session.model_primary,
                session.claude_version,
                session.git_branch,
                session.total_messages,
                session.user_messages,
                session.assistant_messages,
                session.total_input_tokens,
                session.total_output_tokens,
                session.total_cache_read_tokens,
                session.total_cache_creation_tokens,
                session.source_device,
                session.source_file,
                session.started_at,
                session.ended_at,
                session.duration_seconds
            ))

            if cursor.rowcount == 0:
                # Session already exists, get its ID
                cursor.execute(
                    'SELECT id FROM claude_sessions WHERE session_id = ?',
                    (session.session_id,)
                )
                row = cursor.fetchone()
                session_db_id = row['id'] if row else None
            else:
                session_db_id = cursor.lastrowid

            if session_db_id is None:
                return None

            # Insert messages
            for msg in session.messages:
                cursor.execute('''
                    INSERT OR IGNORE INTO claude_messages
                    (session_id, message_uuid, parent_uuid, message_type, user_type,
                     role, model, content_text, content_thinking, content_images,
                     content_tool_uses, content_tool_results, is_sidechain, cwd,
                     git_branch, input_tokens, output_tokens, cache_read_tokens,
                     cache_creation_tokens, stop_reason, request_id, timestamp,
                     sequence_number, todos, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    session_db_id,
                    msg.message_uuid,
                    msg.parent_uuid,
                    msg.message_type,
                    msg.user_type,
                    msg.role,
                    msg.model,
                    msg.content_text,
                    msg.content_thinking,
                    msg.content_images,
                    msg.content_tool_uses,
                    msg.content_tool_results,
                    1 if msg.is_sidechain else 0,
                    msg.cwd,
                    msg.git_branch,
                    msg.input_tokens,
                    msg.output_tokens,
                    msg.cache_read_tokens,
                    msg.cache_creation_tokens,
                    msg.stop_reason,
                    msg.request_id,
                    msg.timestamp,
                    msg.sequence_number,
                    msg.todos,
                    msg.metadata
                ))

            # Insert subagents
            for subagent in session.subagents:
                cursor.execute('''
                    INSERT OR IGNORE INTO claude_subagents
                    (parent_session_id, subagent_id, source_file)
                    VALUES (?, ?, ?)
                ''', (
                    session_db_id,
                    subagent['subagent_id'],
                    subagent['source_file']
                ))

            self.conn.commit()
            return session_db_id

        except sqlite3.Error as e:
            logger.error(f"Failed to ingest session {session.session_id}: {e}")
            self.conn.rollback()
            return None

    def close(self):
        """Close database connection."""
        self.conn.close()


def main():
    """Main entry point for CLI usage."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Parse Claude Code conversation data'
    )
    parser.add_argument(
        '--claude-dir', '-c',
        default='~/.claude',
        help='Path to Claude directory (default: ~/.claude)'
    )
    parser.add_argument(
        '--device', '-d',
        default='desktop',
        help='Source device name (default: desktop)'
    )
    parser.add_argument(
        '--db', '-b',
        default='~/Programs/datalake/datalake.db',
        help='Path to datalake database'
    )
    parser.add_argument(
        '--stats-only', '-s',
        action='store_true',
        help='Only show statistics, do not ingest'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Verbose output'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Initialize parser
    claude_parser = ClaudeParser(args.claude_dir, args.device)

    # Show stats
    stats = claude_parser.get_stats()
    print(f"\nClaude Code Statistics for {args.device}:")
    print(f"  History entries: {stats['history_entries']}")
    print(f"  Projects: {stats['projects']}")
    print(f"  Sessions: {stats['sessions']}")

    if args.stats_only:
        return

    # Ingest data
    db_path = os.path.expanduser(args.db)
    print(f"\nIngesting data into: {db_path}")

    ingester = DatalakeIngester(db_path)

    # Ingest history
    print("Ingesting history...")
    history_count = ingester.ingest_history(claude_parser.parse_history())
    print(f"  Ingested {history_count} history entries")

    # Ingest sessions
    print("Ingesting sessions...")
    session_count = 0
    for session in claude_parser.parse_sessions():
        result = ingester.ingest_session(session)
        if result:
            session_count += 1
            if args.verbose:
                print(f"  {session.session_id}: {session.total_messages} messages")

    print(f"  Ingested {session_count} sessions")

    ingester.close()
    print("\nDone!")


if __name__ == '__main__':
    main()
