#!/usr/bin/env python3
"""
Benchmark comparison: grep-based vs FTS5-based conversation search.

Usage:
    python benchmark.py "star trek" --iterations 10
    python benchmark.py "tapo camera" --json
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class BenchmarkResult:
    method: str
    query: str
    iterations: int
    avg_time_ms: float
    min_time_ms: float
    max_time_ms: float
    results_count: int
    sample_session_ids: list[str]


def benchmark_grep(query: str, iterations: int = 5) -> BenchmarkResult:
    """Benchmark grep-based search on history.jsonl"""
    history_file = Path.home() / ".claude" / "history.jsonl"
    times = []
    session_ids = set()

    for _ in range(iterations):
        start = time.perf_counter()

        # Run grep search
        result = subprocess.run(
            ["grep", "-i", query, str(history_file)],
            capture_output=True,
            text=True
        )

        # Extract session IDs
        for line in result.stdout.split("\n"):
            if match := re.search(r'"sessionId":"([^"]+)"', line):
                session_ids.add(match.group(1))

        end = time.perf_counter()
        times.append((end - start) * 1000)

    return BenchmarkResult(
        method="grep",
        query=query,
        iterations=iterations,
        avg_time_ms=sum(times) / len(times),
        min_time_ms=min(times),
        max_time_ms=max(times),
        results_count=len(session_ids),
        sample_session_ids=list(session_ids)[:5]
    )


def benchmark_fts5(query: str, iterations: int = 5) -> BenchmarkResult:
    """Benchmark FTS5-based search on datalake.db"""
    db_path = Path.home() / "Programs" / "datalake" / "datalake.db"
    times = []
    session_ids = []

    conn = sqlite3.connect(str(db_path))

    for _ in range(iterations):
        start = time.perf_counter()

        # FTS5 search on messages
        cursor = conn.execute("""
            SELECT DISTINCT cs.session_id, cs.started_at, cs.summary
            FROM claude_sessions cs
            WHERE cs.id IN (
                SELECT DISTINCT cm.session_id
                FROM claude_messages cm
                JOIN claude_messages_fts ON cm.id = claude_messages_fts.rowid
                WHERE claude_messages_fts MATCH ?
            )
            ORDER BY cs.started_at DESC
            LIMIT 20
        """, (query,))

        results = cursor.fetchall()
        session_ids = [r[0] for r in results]

        end = time.perf_counter()
        times.append((end - start) * 1000)

    conn.close()

    return BenchmarkResult(
        method="fts5",
        query=query,
        iterations=iterations,
        avg_time_ms=sum(times) / len(times),
        min_time_ms=min(times),
        max_time_ms=max(times),
        results_count=len(session_ids),
        sample_session_ids=session_ids[:5]
    )


def benchmark_fts5_history(query: str, iterations: int = 5) -> BenchmarkResult:
    """Benchmark FTS5 search on history (user prompts only)"""
    db_path = Path.home() / "Programs" / "datalake" / "datalake.db"
    times = []
    session_ids = []

    conn = sqlite3.connect(str(db_path))

    for _ in range(iterations):
        start = time.perf_counter()

        cursor = conn.execute("""
            SELECT DISTINCT ch.session_id, ch.timestamp, ch.display
            FROM claude_history ch
            JOIN claude_history_fts ON ch.id = claude_history_fts.rowid
            WHERE claude_history_fts MATCH ?
            ORDER BY ch.timestamp_unix DESC
            LIMIT 20
        """, (query,))

        results = cursor.fetchall()
        session_ids = [r[0] for r in results]

        end = time.perf_counter()
        times.append((end - start) * 1000)

    conn.close()

    return BenchmarkResult(
        method="fts5_history",
        query=query,
        iterations=iterations,
        avg_time_ms=sum(times) / len(times),
        min_time_ms=min(times),
        max_time_ms=max(times),
        results_count=len(session_ids),
        sample_session_ids=session_ids[:5]
    )


def main():
    parser = argparse.ArgumentParser(description="Benchmark conversation search methods")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--iterations", "-n", type=int, default=5, help="Number of iterations")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    results = []

    # Run benchmarks
    print(f"Benchmarking query: '{args.query}' ({args.iterations} iterations)\n")

    print("Running grep benchmark...")
    grep_result = benchmark_grep(args.query, args.iterations)
    results.append(grep_result)

    print("Running FTS5 (messages) benchmark...")
    fts5_result = benchmark_fts5(args.query, args.iterations)
    results.append(fts5_result)

    print("Running FTS5 (history) benchmark...")
    fts5_history_result = benchmark_fts5_history(args.query, args.iterations)
    results.append(fts5_history_result)

    if args.json:
        output = {
            "query": args.query,
            "iterations": args.iterations,
            "results": [
                {
                    "method": r.method,
                    "avg_ms": round(r.avg_time_ms, 3),
                    "min_ms": round(r.min_time_ms, 3),
                    "max_ms": round(r.max_time_ms, 3),
                    "count": r.results_count,
                    "sample_ids": r.sample_session_ids
                }
                for r in results
            ]
        }
        print(json.dumps(output, indent=2))
    else:
        print("\n" + "=" * 60)
        print(f"{'Method':<15} {'Avg (ms)':<12} {'Min (ms)':<12} {'Max (ms)':<12} {'Results'}")
        print("=" * 60)
        for r in results:
            print(f"{r.method:<15} {r.avg_time_ms:<12.3f} {r.min_time_ms:<12.3f} {r.max_time_ms:<12.3f} {r.results_count}")
        print("=" * 60)

        # Show speedup
        if grep_result.avg_time_ms > 0:
            speedup = grep_result.avg_time_ms / fts5_result.avg_time_ms
            print(f"\nFTS5 is {speedup:.1f}x faster than grep")


if __name__ == "__main__":
    main()
