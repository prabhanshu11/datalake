#!/usr/bin/env python3
"""
Waybar Icon Validation Parser

Parses verification-log.jsonl from visual regression tests and ingests
results into the datalake icon_validations table.

Source: ~/Programs/local-bootstrapping/reference-screenshots/verification-log.jsonl
"""

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional
import logging
import argparse

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S%z'
)
logger = logging.getLogger(__name__)


@dataclass
class IconValidation:
    """Represents a single icon validation test result."""
    screenshot_path: Optional[str]
    test_name: str
    vision_model: str
    icons_found: Optional[str]  # JSON array
    icons_missing: Optional[str]  # JSON array
    all_present: Optional[bool]
    battery_color: Optional[str]
    power_profile_text: Optional[str]
    ac_power: Optional[bool]
    notes: Optional[str]
    passed: bool
    source_device: str
    created_at: str
    metadata: Optional[str]  # JSON string of full response


class IconValidationParser:
    """Parser for verification-log.jsonl from waybar icon tests."""

    def __init__(self, log_path: str, source_device: str = "desktop"):
        self.log_path = Path(log_path)
        self.source_device = source_device

    def parse(self, since_timestamp: str = "") -> Iterator[IconValidation]:
        """Parse verification-log.jsonl, optionally filtering by timestamp."""
        if not self.log_path.exists():
            logger.warning(f"Log file not found: {self.log_path}")
            return

        logger.info(f"Parsing: {self.log_path}")

        with open(self.log_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse line {line_num}: {e}")
                    continue

                timestamp = data.get("timestamp", "")
                if since_timestamp and timestamp <= since_timestamp:
                    continue

                response = data.get("response", {})

                # Determine test name from screenshot field
                screenshot = data.get("screenshot", "")
                if "battery" in screenshot or "power" in screenshot:
                    test_name = "test_battery_charging_indicator"
                else:
                    test_name = "test_waybar_icons_visible"

                # Extract fields from model response
                icons_found = response.get("icons_found")
                icons_missing = response.get("icons_missing")
                all_present = response.get("all_present")
                battery_color = response.get("battery_icon_color")
                power_profile_text = response.get("power_profile_text")
                notes = response.get("notes")

                # Parse AC power from expected string (e.g., "ac=on, profile=BAL")
                expected = data.get("expected", "")
                ac_power = None
                if "ac=on" in expected:
                    ac_power = True
                elif "ac=off" in expected:
                    ac_power = False

                yield IconValidation(
                    screenshot_path=screenshot,
                    test_name=test_name,
                    vision_model=data.get("model", "unknown"),
                    icons_found=json.dumps(icons_found) if icons_found else None,
                    icons_missing=json.dumps(icons_missing) if icons_missing else None,
                    all_present=all_present,
                    battery_color=battery_color,
                    power_profile_text=power_profile_text,
                    ac_power=ac_power,
                    notes=notes,
                    passed=data.get("match", False),
                    source_device=self.source_device,
                    created_at=timestamp,
                    metadata=json.dumps(response),
                )

    def get_stats(self) -> dict:
        """Get statistics about available data."""
        stats = {
            'log_file_exists': self.log_path.exists(),
            'line_count': 0,
        }
        if self.log_path.exists():
            with open(self.log_path, 'r') as f:
                stats['line_count'] = sum(1 for line in f if line.strip())
        return stats


class DatalakeIconIngester:
    """Ingests icon validation results into the datalake database."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

    def get_last_timestamp(self, source_device: str) -> str:
        """Get the timestamp of the most recent validation for a device."""
        cursor = self.conn.execute('''
            SELECT MAX(created_at) as last_ts
            FROM icon_validations
            WHERE source_device = ?
        ''', (source_device,))
        row = cursor.fetchone()
        return row['last_ts'] or ""

    def ingest(self, validations: Iterator[IconValidation]) -> int:
        """Ingest icon validation results into the database."""
        cursor = self.conn.cursor()
        count = 0

        for v in validations:
            try:
                cursor.execute('''
                    INSERT INTO icon_validations
                    (screenshot_path, test_name, vision_model,
                     icons_found, icons_missing, all_present,
                     battery_color, power_profile_text, ac_power,
                     notes, passed, source_device, created_at, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    v.screenshot_path,
                    v.test_name,
                    v.vision_model,
                    v.icons_found,
                    v.icons_missing,
                    1 if v.all_present else 0 if v.all_present is not None else None,
                    v.battery_color,
                    v.power_profile_text,
                    1 if v.ac_power else 0 if v.ac_power is not None else None,
                    v.notes,
                    1 if v.passed else 0,
                    v.source_device,
                    v.created_at,
                    v.metadata,
                ))
                count += 1
            except sqlite3.Error as e:
                logger.error(f"Failed to insert validation: {e}")

        self.conn.commit()
        logger.info(f"Ingested {count} icon validations")
        return count

    def close(self):
        """Close database connection."""
        self.conn.close()


def main():
    """Main entry point for CLI usage."""
    parser = argparse.ArgumentParser(
        description='Parse waybar icon validation results'
    )
    parser.add_argument(
        '--log-file', '-l',
        default=os.path.expanduser(
            '~/Programs/local-bootstrapping/reference-screenshots/verification-log.jsonl'
        ),
        help='Path to verification-log.jsonl'
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

    log_parser = IconValidationParser(args.log_file, args.device)

    stats = log_parser.get_stats()
    print(f"\nIcon Validation Log Statistics:")
    print(f"  Log file exists: {stats['log_file_exists']}")
    print(f"  Entries: {stats['line_count']}")

    if args.stats_only:
        return

    if not stats['log_file_exists']:
        print("\nNo verification log found. Run visual tests first.")
        return

    db_path = os.path.expanduser(args.db)
    print(f"\nIngesting into: {db_path}")

    ingester = DatalakeIconIngester(db_path)

    last_ts = ingester.get_last_timestamp(args.device)
    print(f"  Last ingested timestamp: {last_ts or '(none)'}")

    count = ingester.ingest(log_parser.parse(since_timestamp=last_ts))
    print(f"  Ingested {count} new validations")

    ingester.close()
    print("\nDone!")


if __name__ == '__main__':
    main()
