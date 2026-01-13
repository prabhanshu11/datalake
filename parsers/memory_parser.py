#!/usr/bin/env python3
"""
Claude Memory Metrics Parser

Parses memory monitoring data from:
- /var/log/claude-memory/metrics.jsonl (time-series RAM data)
- /var/log/claude-memory/events.jsonl (event log)

Designed for ingestion into the datalake database.
"""

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional
import logging
import argparse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S%z'
)
logger = logging.getLogger(__name__)


@dataclass
class MemoryMetric:
    """Represents a single memory metric entry."""
    pid: int
    session_id: Optional[str]
    rss_bytes: int
    rss_mb: float
    memory_rate_mb_min: Optional[float]
    command: Optional[str]
    timestamp: str
    timestamp_unix: int
    source_device: str


@dataclass
class MemoryEvent:
    """Represents a memory event entry."""
    event_type: str
    pid: Optional[int]
    session_id: Optional[str]
    severity: str
    message: Optional[str]
    details: Optional[str]
    timestamp: str
    timestamp_unix: int
    source_device: str


class MemoryParser:
    """Parser for Claude memory monitoring data."""

    def __init__(self, log_dir: str = "/var/log/claude-memory",
                 source_device: str = "desktop"):
        self.log_dir = Path(log_dir)
        self.source_device = source_device
        self.metrics_file = self.log_dir / "metrics.jsonl"
        self.events_file = self.log_dir / "events.jsonl"

    def parse_metrics(self, since_unix: int = 0) -> Iterator[MemoryMetric]:
        """Parse metrics.jsonl file, optionally filtering by timestamp."""
        if not self.metrics_file.exists():
            logger.warning(f"Metrics file not found: {self.metrics_file}")
            return

        logger.info(f"Parsing metrics from: {self.metrics_file}")

        with open(self.metrics_file, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                try:
                    data = json.loads(line.strip())

                    timestamp_unix = data.get('timestamp', 0)
                    if timestamp_unix <= since_unix:
                        continue

                    # Convert unix timestamp to ISO format
                    timestamp_iso = datetime.fromtimestamp(
                        timestamp_unix
                    ).isoformat()

                    yield MemoryMetric(
                        pid=data.get('pid', 0),
                        session_id=data.get('session_id'),
                        rss_bytes=data.get('rss_bytes', 0),
                        rss_mb=data.get('rss_mb', 0.0),
                        memory_rate_mb_min=data.get('rate_mb_min'),
                        command=data.get('command'),
                        timestamp=timestamp_iso,
                        timestamp_unix=timestamp_unix,
                        source_device=self.source_device
                    )
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse metrics line {line_num}: {e}")
                except Exception as e:
                    logger.error(f"Error processing metrics line {line_num}: {e}")

    def parse_events(self, since_unix: int = 0) -> Iterator[MemoryEvent]:
        """Parse events.jsonl file, optionally filtering by timestamp."""
        if not self.events_file.exists():
            logger.warning(f"Events file not found: {self.events_file}")
            return

        logger.info(f"Parsing events from: {self.events_file}")

        with open(self.events_file, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                try:
                    data = json.loads(line.strip())

                    timestamp_unix = data.get('timestamp', 0)
                    if timestamp_unix <= since_unix:
                        continue

                    timestamp_iso = datetime.fromtimestamp(
                        timestamp_unix
                    ).isoformat()

                    # Handle details as JSON string
                    details = data.get('details')
                    if details and not isinstance(details, str):
                        details = json.dumps(details)

                    yield MemoryEvent(
                        event_type=data.get('type', 'unknown'),
                        pid=data.get('pid'),
                        session_id=data.get('session_id'),
                        severity=data.get('severity', 'info'),
                        message=data.get('message'),
                        details=details,
                        timestamp=timestamp_iso,
                        timestamp_unix=timestamp_unix,
                        source_device=self.source_device
                    )
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse events line {line_num}: {e}")
                except Exception as e:
                    logger.error(f"Error processing events line {line_num}: {e}")

    def get_stats(self) -> dict:
        """Get statistics about available data."""
        stats = {
            'metrics_file_exists': self.metrics_file.exists(),
            'events_file_exists': self.events_file.exists(),
            'metrics_lines': 0,
            'events_lines': 0,
        }

        if self.metrics_file.exists():
            with open(self.metrics_file, 'r') as f:
                stats['metrics_lines'] = sum(1 for _ in f)

        if self.events_file.exists():
            with open(self.events_file, 'r') as f:
                stats['events_lines'] = sum(1 for _ in f)

        return stats


class DatalakeMemoryIngester:
    """Ingests parsed memory data into the datalake database."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

    def get_last_metric_timestamp(self, source_device: str) -> int:
        """Get the timestamp of the most recent metric for a device."""
        cursor = self.conn.execute('''
            SELECT MAX(timestamp_unix) as last_ts
            FROM memory_metrics
            WHERE source_device = ?
        ''', (source_device,))
        row = cursor.fetchone()
        return row['last_ts'] or 0

    def get_last_event_timestamp(self, source_device: str) -> int:
        """Get the timestamp of the most recent event for a device."""
        cursor = self.conn.execute('''
            SELECT MAX(timestamp_unix) as last_ts
            FROM memory_events
            WHERE source_device = ?
        ''', (source_device,))
        row = cursor.fetchone()
        return row['last_ts'] or 0

    def ingest_metrics(self, metrics: Iterator[MemoryMetric]) -> int:
        """Ingest memory metrics into the database."""
        cursor = self.conn.cursor()
        count = 0

        for metric in metrics:
            try:
                cursor.execute('''
                    INSERT INTO memory_metrics
                    (pid, session_id, rss_bytes, rss_mb, memory_rate_mb_min,
                     command, timestamp, timestamp_unix, source_device)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    metric.pid,
                    metric.session_id,
                    metric.rss_bytes,
                    metric.rss_mb,
                    metric.memory_rate_mb_min,
                    metric.command,
                    metric.timestamp,
                    metric.timestamp_unix,
                    metric.source_device
                ))
                count += 1
            except sqlite3.Error as e:
                logger.error(f"Failed to insert metric: {e}")

        self.conn.commit()
        logger.info(f"Ingested {count} metrics")
        return count

    def ingest_events(self, events: Iterator[MemoryEvent]) -> int:
        """Ingest memory events into the database."""
        cursor = self.conn.cursor()
        count = 0

        for event in events:
            try:
                cursor.execute('''
                    INSERT INTO memory_events
                    (event_type, pid, session_id, severity, message,
                     details, timestamp, timestamp_unix, source_device)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    event.event_type,
                    event.pid,
                    event.session_id,
                    event.severity,
                    event.message,
                    event.details,
                    event.timestamp,
                    event.timestamp_unix,
                    event.source_device
                ))
                count += 1
            except sqlite3.Error as e:
                logger.error(f"Failed to insert event: {e}")

        self.conn.commit()
        logger.info(f"Ingested {count} events")
        return count

    def close(self):
        """Close database connection."""
        self.conn.close()


def run_test():
    """Run a test with mock data."""
    import tempfile

    # Create mock data
    mock_metrics = [
        {"timestamp": 1736847600, "pid": 12345, "rss_bytes": 524288000,
         "rss_mb": 500.0, "rate_mb_min": 12.5, "command": "claude",
         "session_id": "abc-123"},
        {"timestamp": 1736847610, "pid": 12345, "rss_bytes": 536870912,
         "rss_mb": 512.0, "rate_mb_min": 72.0, "command": "claude",
         "session_id": "abc-123"},
    ]

    mock_events = [
        {"timestamp": 1736847605, "type": "hook_warn", "pid": 12345,
         "severity": "warning", "message": "Memory growing fast",
         "details": {"rate": 72.0, "threshold": 50.0}},
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        # Write mock files
        metrics_path = Path(tmpdir) / "metrics.jsonl"
        events_path = Path(tmpdir) / "events.jsonl"

        with open(metrics_path, 'w') as f:
            for m in mock_metrics:
                f.write(json.dumps(m) + '\n')

        with open(events_path, 'w') as f:
            for e in mock_events:
                f.write(json.dumps(e) + '\n')

        # Parse
        parser = MemoryParser(tmpdir, "test-device")

        print("Testing metrics parsing...")
        metrics = list(parser.parse_metrics())
        print(f"  Parsed {len(metrics)} metrics")
        for m in metrics:
            print(f"    PID={m.pid}, RSS={m.rss_mb}MB, Rate={m.memory_rate_mb_min}MB/min")

        print("\nTesting events parsing...")
        events = list(parser.parse_events())
        print(f"  Parsed {len(events)} events")
        for e in events:
            print(f"    Type={e.event_type}, Severity={e.severity}, Message={e.message}")

        print("\nTest passed!")


def main():
    """Main entry point for CLI usage."""
    parser = argparse.ArgumentParser(
        description='Parse Claude memory monitoring data'
    )
    parser.add_argument(
        '--log-dir', '-l',
        default='/var/log/claude-memory',
        help='Path to log directory (default: /var/log/claude-memory)'
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
        '--test', '-t',
        action='store_true',
        help='Run test with mock data'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Verbose output'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.test:
        run_test()
        return

    # Initialize parser
    memory_parser = MemoryParser(args.log_dir, args.device)

    # Show stats
    stats = memory_parser.get_stats()
    print(f"\nMemory Log Statistics for {args.device}:")
    print(f"  Metrics file exists: {stats['metrics_file_exists']}")
    print(f"  Events file exists: {stats['events_file_exists']}")
    print(f"  Metrics lines: {stats['metrics_lines']}")
    print(f"  Events lines: {stats['events_lines']}")

    if args.stats_only:
        return

    if not stats['metrics_file_exists'] and not stats['events_file_exists']:
        print("\nNo log files found. Waiting for claude-memory-monitor service...")
        return

    # Ingest data
    db_path = os.path.expanduser(args.db)
    print(f"\nIngesting data into: {db_path}")

    ingester = DatalakeMemoryIngester(db_path)

    # Get last timestamps for incremental ingestion
    last_metric_ts = ingester.get_last_metric_timestamp(args.device)
    last_event_ts = ingester.get_last_event_timestamp(args.device)

    print(f"  Last metric timestamp: {last_metric_ts}")
    print(f"  Last event timestamp: {last_event_ts}")

    # Ingest metrics
    print("Ingesting metrics...")
    metric_count = ingester.ingest_metrics(
        memory_parser.parse_metrics(since_unix=last_metric_ts)
    )
    print(f"  Ingested {metric_count} new metrics")

    # Ingest events
    print("Ingesting events...")
    event_count = ingester.ingest_events(
        memory_parser.parse_events(since_unix=last_event_ts)
    )
    print(f"  Ingested {event_count} new events")

    ingester.close()
    print("\nDone!")


if __name__ == '__main__':
    main()
