#!/usr/bin/env python3
"""
Freeze-Monitor Velocity Parser

Parses high-resolution memory velocity JSONL from freeze-monitor:
  ~/Programs/utilities/freeze-monitor/logs/velocity-YYYYMMDD.jsonl

Each line contains a 3-second system memory snapshot with:
  - RAM usage, swap, velocity (MB/s delta)
  - Severity classification (nominal/elevated/warning/critical)
  - Top 5 memory consumers with per-sample RSS deltas

Ingests into datalake tables:
  - memory_velocity (one row per sample)
  - memory_velocity_consumers (top consumers per sample)
  - memory_severity_events (severity transitions)
"""

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional
import logging
import argparse
import glob

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S%z'
)
logger = logging.getLogger(__name__)


@dataclass
class Consumer:
    """A top memory consumer from a single sample."""
    pid: int
    name: str
    rss_mb: int
    delta_mb: int
    window_s: int


@dataclass
class VelocitySample:
    """A single memory velocity sample from freeze-monitor JSONL."""
    timestamp_utc: str
    timestamp_unix: int
    source_device: str
    ram_total_mb: int
    ram_used_mb: int
    ram_available_mb: int
    swap_used_mb: int
    swap_total_mb: int
    velocity_mb_s: float
    severity: str
    top_consumers: list[Consumer] = field(default_factory=list)


class VelocityParser:
    """Parser for freeze-monitor velocity JSONL files."""

    def __init__(self, log_dir: str, source_device: str = "omarchy"):
        self.log_dir = Path(log_dir)
        self.source_device = source_device

    def discover_files(self) -> list[Path]:
        """Find all velocity JSONL files, sorted by date."""
        pattern = str(self.log_dir / "velocity-*.jsonl")
        files = sorted(glob.glob(pattern))
        return [Path(f) for f in files]

    def parse_file(self, filepath: Path, since_unix: int = 0) -> Iterator[VelocitySample]:
        """Parse a single velocity JSONL file, yielding samples after since_unix."""
        if not filepath.exists():
            logger.warning(f"File not found: {filepath}")
            return

        logger.info(f"Parsing: {filepath.name}")
        line_count = 0
        yielded = 0

        with open(filepath, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                line_count += 1
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as e:
                    logger.warning(f"  {filepath.name}:{line_num} — JSON error: {e}")
                    continue

                ts_unix = data.get('timestamp_unix', 0)
                if ts_unix <= since_unix:
                    continue

                # Parse top consumers
                consumers = []
                for c in data.get('top_consumers', []):
                    consumers.append(Consumer(
                        pid=c.get('pid', 0),
                        name=c.get('name', 'unknown'),
                        rss_mb=c.get('rss_mb', 0),
                        delta_mb=c.get('delta_mb', 0),
                        window_s=c.get('window_s', 3),
                    ))

                # Handle velocity — can be string "0" or number
                vel = data.get('velocity_mb_s', 0)
                try:
                    vel = float(vel)
                except (ValueError, TypeError):
                    vel = 0.0

                yield VelocitySample(
                    timestamp_utc=data.get('timestamp_utc', ''),
                    timestamp_unix=ts_unix,
                    source_device=data.get('source_device', self.source_device),
                    ram_total_mb=data.get('ram_total_mb', 0),
                    ram_used_mb=data.get('ram_used_mb', 0),
                    ram_available_mb=data.get('ram_available_mb', 0),
                    swap_used_mb=data.get('swap_used_mb', 0),
                    swap_total_mb=data.get('swap_total_mb', 0),
                    velocity_mb_s=vel,
                    severity=data.get('severity', 'nominal'),
                    top_consumers=consumers,
                )
                yielded += 1

        logger.info(f"  {filepath.name}: {line_count} lines, {yielded} new samples")

    def parse_all(self, since_unix: int = 0) -> Iterator[VelocitySample]:
        """Parse all velocity files, yielding samples after since_unix."""
        files = self.discover_files()
        if not files:
            logger.warning(f"No velocity JSONL files in {self.log_dir}")
            return

        logger.info(f"Found {len(files)} velocity file(s)")
        for filepath in files:
            yield from self.parse_file(filepath, since_unix=since_unix)


class VelocityIngester:
    """Ingests parsed velocity data into the datalake database."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")

    def get_last_timestamp(self, source_device: str) -> int:
        """Get the most recent timestamp_unix for a device."""
        cursor = self.conn.execute('''
            SELECT MAX(timestamp_unix) as last_ts
            FROM memory_velocity
            WHERE source_device = ?
        ''', (source_device,))
        row = cursor.fetchone()
        return row['last_ts'] or 0

    def ingest(self, samples: Iterator[VelocitySample], batch_size: int = 500) -> dict:
        """Ingest velocity samples into the database.

        Returns dict with counts: {'velocity': N, 'consumers': N, 'events': N}
        """
        cursor = self.conn.cursor()
        counts = {'velocity': 0, 'consumers': 0, 'events': 0}
        prev_severity = None
        event_start_ts = None
        event_start_utc = None
        batch = 0

        for sample in samples:
            try:
                # Insert velocity sample
                cursor.execute('''
                    INSERT INTO memory_velocity
                    (timestamp_utc, timestamp_unix, source_device,
                     ram_total_mb, ram_used_mb, ram_available_mb,
                     swap_used_mb, swap_total_mb, velocity_mb_s, severity)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    sample.timestamp_utc, sample.timestamp_unix,
                    sample.source_device, sample.ram_total_mb,
                    sample.ram_used_mb, sample.ram_available_mb,
                    sample.swap_used_mb, sample.swap_total_mb,
                    sample.velocity_mb_s, sample.severity,
                ))
                velocity_id = cursor.lastrowid
                counts['velocity'] += 1

                # Insert top consumers
                for c in sample.top_consumers:
                    cursor.execute('''
                        INSERT INTO memory_velocity_consumers
                        (velocity_id, pid, process_name, rss_mb, delta_mb, window_s)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (velocity_id, c.pid, c.name, c.rss_mb, c.delta_mb, c.window_s))
                    counts['consumers'] += 1

                # Track severity transitions → memory_severity_events
                if sample.severity != 'nominal' and prev_severity == 'nominal':
                    # Entering elevated/warning/critical
                    event_start_ts = sample.timestamp_unix
                    event_start_utc = sample.timestamp_utc
                    top = sample.top_consumers[0] if sample.top_consumers else None
                    cursor.execute('''
                        INSERT INTO memory_severity_events
                        (timestamp_utc, timestamp_unix, source_device, severity,
                         ram_available_mb, swap_used_mb, velocity_mb_s,
                         top_consumer_pid, top_consumer_name, top_consumer_rss_mb)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        sample.timestamp_utc, sample.timestamp_unix,
                        sample.source_device, sample.severity,
                        sample.ram_available_mb, sample.swap_used_mb,
                        sample.velocity_mb_s,
                        top.pid if top else None,
                        top.name if top else None,
                        top.rss_mb if top else None,
                    ))
                    counts['events'] += 1

                elif sample.severity == 'nominal' and prev_severity and prev_severity != 'nominal':
                    # Returning to nominal — close the event
                    if event_start_ts:
                        duration = sample.timestamp_unix - event_start_ts
                        cursor.execute('''
                            UPDATE memory_severity_events
                            SET duration_s = ?, resolved_at = ?
                            WHERE timestamp_unix = ? AND source_device = ? AND resolved_at IS NULL
                        ''', (duration, sample.timestamp_utc,
                              event_start_ts, sample.source_device))
                        event_start_ts = None

                prev_severity = sample.severity

                # Commit in batches
                batch += 1
                if batch >= batch_size:
                    self.conn.commit()
                    batch = 0

            except sqlite3.Error as e:
                logger.error(f"DB error at ts={sample.timestamp_unix}: {e}")

        # Final commit
        self.conn.commit()
        return counts

    def get_stats(self) -> dict:
        """Get table statistics."""
        stats = {}
        for table in ['memory_velocity', 'memory_velocity_consumers', 'memory_severity_events']:
            cursor = self.conn.execute(f'SELECT COUNT(*) as n FROM {table}')
            stats[table] = cursor.fetchone()['n']

        cursor = self.conn.execute('''
            SELECT source_device, COUNT(*) as n,
                   MIN(timestamp_utc) as earliest,
                   MAX(timestamp_utc) as latest
            FROM memory_velocity
            GROUP BY source_device
        ''')
        stats['devices'] = [dict(row) for row in cursor.fetchall()]
        return stats

    def close(self):
        self.conn.close()


def run_test():
    """Run a test with mock velocity data."""
    import tempfile

    mock_lines = [
        json.dumps({
            "timestamp_utc": "2026-02-23T07:03:42Z",
            "timestamp_unix": 1771830222,
            "source_device": "test-device",
            "ram_total_mb": 32000,
            "ram_used_mb": 6000,
            "ram_available_mb": 26000,
            "swap_used_mb": 0,
            "swap_total_mb": 12000,
            "velocity_mb_s": 0,
            "severity": "nominal",
            "top_consumers": [
                {"pid": 1234, "name": "python", "rss_mb": 1200, "delta_mb": 0, "window_s": 3}
            ]
        }),
        json.dumps({
            "timestamp_utc": "2026-02-23T07:03:45Z",
            "timestamp_unix": 1771830225,
            "source_device": "test-device",
            "ram_total_mb": 32000,
            "ram_used_mb": 10000,
            "ram_available_mb": 22000,
            "swap_used_mb": 500,
            "swap_total_mb": 12000,
            "velocity_mb_s": 1333.3,
            "severity": "warning",
            "top_consumers": [
                {"pid": 1234, "name": "python", "rss_mb": 5200, "delta_mb": 4000, "window_s": 3}
            ]
        }),
        json.dumps({
            "timestamp_utc": "2026-02-23T07:03:48Z",
            "timestamp_unix": 1771830228,
            "source_device": "test-device",
            "ram_total_mb": 32000,
            "ram_used_mb": 7000,
            "ram_available_mb": 25000,
            "swap_used_mb": 0,
            "swap_total_mb": 12000,
            "velocity_mb_s": -1000,
            "severity": "nominal",
            "top_consumers": [
                {"pid": 1234, "name": "python", "rss_mb": 1200, "delta_mb": -4000, "window_s": 3}
            ]
        }),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        # Write mock JSONL
        velocity_file = Path(tmpdir) / "velocity-20260223.jsonl"
        velocity_file.write_text('\n'.join(mock_lines) + '\n')

        # Parse
        parser = VelocityParser(tmpdir, "test-device")
        samples = list(parser.parse_all())
        print(f"Parsed {len(samples)} samples")

        for s in samples:
            print(f"  {s.timestamp_utc} | {s.severity:8s} | "
                  f"avail={s.ram_available_mb}MB vel={s.velocity_mb_s}MB/s | "
                  f"top: {s.top_consumers[0].name}({s.top_consumers[0].rss_mb}MB)")

        # Test ingestion with in-memory DB
        db_path = Path(tmpdir) / "test.db"
        conn = sqlite3.connect(str(db_path))

        # Create schema
        schema_path = Path(__file__).parent.parent / "schema_v3_memory.sql"
        if schema_path.exists():
            # Need metadata table first
            conn.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)")
            conn.executescript(schema_path.read_text())
            conn.commit()
        else:
            print(f"  Schema not found at {schema_path}, skipping ingestion test")
            return

        conn.close()

        ingester = VelocityIngester(str(db_path))
        samples = list(parser.parse_all())  # Re-parse (generators are single-use)
        counts = ingester.ingest(iter(samples))
        print(f"\nIngested: {counts}")

        stats = ingester.get_stats()
        print(f"Stats: {stats}")
        ingester.close()

        print("\nTest passed!")


def main():
    parser = argparse.ArgumentParser(
        description='Parse freeze-monitor velocity JSONL into datalake'
    )
    parser.add_argument(
        '--log-dir', '-l',
        default=os.path.expanduser('~/Programs/utilities/freeze-monitor/logs'),
        help='Path to freeze-monitor logs directory'
    )
    parser.add_argument(
        '--device', '-d',
        default='omarchy',
        help='Source device name (default: omarchy)'
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
    velocity_parser = VelocityParser(args.log_dir, args.device)

    # Discover files
    files = velocity_parser.discover_files()
    print(f"\nVelocity JSONL files in {args.log_dir}:")
    for f in files:
        size_kb = f.stat().st_size / 1024
        print(f"  {f.name} ({size_kb:.0f} KB)")

    if not files:
        print("  No files found.")
        return

    # Connect to datalake
    db_path = os.path.expanduser(args.db)
    print(f"\nDatalake: {db_path}")

    ingester = VelocityIngester(db_path)

    # Show current stats
    stats = ingester.get_stats()
    print(f"  memory_velocity: {stats['memory_velocity']} rows")
    print(f"  memory_velocity_consumers: {stats['memory_velocity_consumers']} rows")
    print(f"  memory_severity_events: {stats['memory_severity_events']} rows")
    for dev in stats.get('devices', []):
        print(f"  Device '{dev['source_device']}': {dev['n']} samples "
              f"({dev['earliest']} → {dev['latest']})")

    if args.stats_only:
        ingester.close()
        return

    # Get last timestamp for incremental ingestion
    last_ts = ingester.get_last_timestamp(args.device)
    if last_ts:
        last_utc = datetime.utcfromtimestamp(last_ts).strftime('%Y-%m-%dT%H:%M:%SZ')
        print(f"\n  Last ingested: {last_utc} (unix: {last_ts})")
    else:
        print(f"\n  No previous data for device '{args.device}'")

    # Ingest
    print("Ingesting new samples...")
    samples = velocity_parser.parse_all(since_unix=last_ts)
    counts = ingester.ingest(samples)

    print(f"\nIngested:")
    print(f"  Velocity samples: {counts['velocity']}")
    print(f"  Consumer records: {counts['consumers']}")
    print(f"  Severity events:  {counts['events']}")

    ingester.close()
    print("\nDone!")


if __name__ == '__main__':
    main()
