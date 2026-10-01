#!/usr/bin/env python3
"""Incremental secondary -> primary datalake sync (stdlib only; runs on both machines).

Replaces the old "VACUUM INTO the whole 23 GB DB + scp it every 30 min" path of
sync-to-primary.sh (star-trek-camera docs/night-1002/datalake-incr-REPORT.md).

Three subcommands, each self-contained so the script can be piped over ssh
(`ssh host python3 - merge ... < sync_delta.py`) without the remote checkout
being on the same commit:

  keys    (primary)   write the primary's knowledge of <device> rows into a small
                      keys DB: session_ids, message_uuids, max history timestamp.
                      Only needed for the first run / when the watermark is lost.
  export  (secondary) write rows of <device> newer than the watermark (or, with
                      --keys, every row the primary lacks) into a small delta DB.
                      Prints the new watermark as JSON. Never writes the source DB.
  merge   (primary)   ATTACH the delta and INSERT the missing rows (same dedup rules
                      as the old full merge). FTS5 stays consistent through the
                      AFTER INSERT triggers on claude_messages / claude_history.
                      --dry-run rolls the transaction back.

Watermarks are the AUTOINCREMENT ids of claude_history / claude_sessions /
claude_messages: new rows always get a larger id, so `id > watermark` is exactly
"inserted since the last successful sync". Updates to existing rows were never
propagated by the old merge either (INSERT OR IGNORE / NOT IN), so nothing is lost.
"""
import argparse
import json
import os
import sqlite3
import sys
import time

TABLES = ("claude_history", "claude_sessions", "claude_messages")
HISTORY_MARGIN_MS = 2 * 24 * 3600 * 1000  # reconcile window before the primary's newest row

SESSION_COLS = (
    "session_id, project_path, project_encoded, summary, model_primary, claude_version, "
    "git_branch, total_messages, user_messages, assistant_messages, total_input_tokens, "
    "total_output_tokens, total_cache_read_tokens, total_cache_creation_tokens, "
    "source_device, source_file, started_at, ended_at, duration_seconds, created_at, ingested_at"
)
MESSAGE_COLS = (
    "message_uuid, parent_uuid, message_type, user_type, role, model, "
    "content_text, content_thinking, content_images, content_tool_uses, content_tool_results, "
    "is_sidechain, cwd, git_branch, input_tokens, output_tokens, "
    "cache_read_tokens, cache_creation_tokens, stop_reason, request_id, "
    "timestamp, sequence_number, todos, metadata"
)
HISTORY_COLS = "session_id, display, pasted_contents, project, source_device, timestamp, timestamp_unix"


def _connect(path, readonly=False):
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, isolation_level=None)
    else:
        conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA busy_timeout = 60000")
    return conn


def keys(db, device, out):
    """Primary side: what the primary already holds for `device`."""
    if os.path.exists(out):
        os.remove(out)
    conn = _connect(db, readonly=True)
    conn.execute("ATTACH DATABASE ? AS k", (f"file:{out}?mode=rwc",))
    conn.execute("BEGIN")
    conn.execute("CREATE TABLE k.sessions (session_id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE k.messages (message_uuid TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE k.meta (k TEXT PRIMARY KEY, v)")
    conn.execute("INSERT OR IGNORE INTO k.sessions SELECT session_id FROM claude_sessions WHERE source_device = ?", (device,))
    conn.execute(
        "INSERT OR IGNORE INTO k.messages SELECT m.message_uuid FROM claude_messages m "
        "WHERE m.session_id IN (SELECT id FROM claude_sessions WHERE source_device = ?)", (device,))
    (hmax,) = conn.execute("SELECT max(timestamp_unix) FROM claude_history WHERE source_device = ?", (device,)).fetchone()
    conn.execute("INSERT INTO k.meta VALUES ('history_max_ts', ?)", (hmax or 0,))
    conn.execute("COMMIT")
    counts = {t: conn.execute(f"SELECT count(*) FROM k.{t}").fetchone()[0] for t in ("sessions", "messages")}
    counts["history_max_ts"] = hmax or 0
    conn.close()
    return counts


def _maxes(conn):
    return {t: conn.execute(f"SELECT coalesce(max(id), 0) FROM main.{t}").fetchone()[0] for t in TABLES}


def export(db, device, out, watermark=None, keys_db=None):
    """Secondary side: write the delta DB. Returns {"watermark": {...}, "rows": {...}, "mode": ...}.

    watermark: {"claude_history": id, "claude_sessions": id, "claude_messages": id}
    keys_db:   output of keys(); used when there is no watermark (reconcile).
    """
    if watermark is None and keys_db is None:
        raise ValueError("export needs a watermark or a keys DB (reconcile)")
    if os.path.exists(out):
        os.remove(out)
    conn = _connect(db, readonly=True)
    conn.execute("ATTACH DATABASE ? AS d", (f"file:{out}?mode=rwc",))
    if keys_db:
        conn.execute("ATTACH DATABASE ? AS k", (f"file:{keys_db}?mode=ro",))
    conn.execute("BEGIN")  # one read snapshot of the source (WAL) for maxes + rows
    top = _maxes(conn)
    for t in TABLES:
        conn.execute(f"CREATE TABLE d.{t} AS SELECT * FROM main.{t} WHERE 0")

    if keys_db is None:
        wm = watermark
        conn.execute(
            "INSERT INTO d.claude_messages SELECT m.* FROM main.claude_messages m "
            "JOIN main.claude_sessions s ON s.id = m.session_id "
            "WHERE m.id > ? AND m.id <= ? AND s.source_device = ?",
            (wm["claude_messages"], top["claude_messages"], device))
        conn.execute(
            "INSERT INTO d.claude_sessions SELECT * FROM main.claude_sessions WHERE source_device = ? "
            "AND ((id > ? AND id <= ?) OR id IN (SELECT session_id FROM d.claude_messages))",
            (device, wm["claude_sessions"], top["claude_sessions"]))
        hist_where, hist_args = "id > ? AND id <= ?", (wm["claude_history"], top["claude_history"])
        mode = "watermark"
    else:
        # Index-only scan of message_uuid (never the 20+ GB table body), then fetch by id.
        conn.execute(
            "CREATE TEMP TABLE missing AS SELECT id FROM main.claude_messages INDEXED BY idx_claude_messages_uuid "
            "WHERE id <= ? AND message_uuid NOT IN (SELECT message_uuid FROM k.messages)",
            (top["claude_messages"],))
        conn.execute(
            "INSERT INTO d.claude_messages SELECT m.* FROM main.claude_messages m "
            "JOIN main.claude_sessions s ON s.id = m.session_id "
            "WHERE m.id IN (SELECT id FROM temp.missing) AND s.source_device = ?", (device,))
        conn.execute(
            "INSERT INTO d.claude_sessions SELECT * FROM main.claude_sessions WHERE source_device = ? AND id <= ? "
            "AND (session_id NOT IN (SELECT session_id FROM k.sessions) "
            "     OR id IN (SELECT session_id FROM d.claude_messages))",
            (device, top["claude_sessions"]))
        (hmax,) = conn.execute("SELECT v FROM k.meta WHERE k = 'history_max_ts'").fetchone()
        hist_where = "timestamp_unix >= ? AND id <= ?"
        hist_args = (max(0, int(hmax) - HISTORY_MARGIN_MS), top["claude_history"])
        mode = "reconcile"

    # History: one row per (session_id, timestamp_unix) key. The primary's merge dedups
    # against its own rows but not within one batch, so the delta must not carry copies.
    conn.execute(
        f"INSERT INTO d.claude_history SELECT * FROM main.claude_history WHERE id IN ("
        f"  SELECT min(id) FROM main.claude_history WHERE source_device = ? AND {hist_where} "
        f"  GROUP BY session_id, timestamp_unix)",
        (device, *hist_args))
    conn.execute("COMMIT")
    rows = {t: conn.execute(f"SELECT count(*) FROM d.{t}").fetchone()[0] for t in TABLES}
    conn.close()
    return {"mode": mode, "watermark": top, "rows": rows, "bytes": os.path.getsize(out)}


MERGE_SQL = f"""
INSERT INTO claude_history ({HISTORY_COLS})
SELECT {HISTORY_COLS} FROM delta.claude_history sh
WHERE sh.source_device = :device
  AND NOT EXISTS (SELECT 1 FROM claude_history ch
                  WHERE ch.session_id = sh.session_id AND ch.timestamp_unix = sh.timestamp_unix);

INSERT OR IGNORE INTO claude_sessions ({SESSION_COLS})
SELECT {SESSION_COLS} FROM delta.claude_sessions ss
WHERE ss.source_device = :device
  AND ss.session_id NOT IN (SELECT session_id FROM claude_sessions);

INSERT OR IGNORE INTO claude_messages (session_id, {MESSAGE_COLS})
SELECT (SELECT id FROM claude_sessions WHERE session_id = ss.session_id),
       {', '.join('sm.' + c.strip() for c in MESSAGE_COLS.split(','))}
FROM delta.claude_messages sm
JOIN delta.claude_sessions ss ON sm.session_id = ss.id
WHERE ss.source_device = :device
  AND sm.message_uuid NOT IN (SELECT message_uuid FROM claude_messages WHERE message_uuid IS NOT NULL);
"""


def merge(db, delta, device, dry_run=False):
    """Primary side: insert the delta's missing rows. Same rules as the old full merge."""
    conn = _connect(db)
    conn.execute("ATTACH DATABASE ? AS delta", (delta,))
    conn.execute("BEGIN IMMEDIATE")
    added = {}
    for stmt, table in zip([s for s in MERGE_SQL.split(";") if s.strip()], TABLES):
        cur = conn.execute(stmt, {"device": device})
        added[table] = cur.rowcount
    conn.execute("ROLLBACK" if dry_run else "COMMIT")
    conn.execute("DETACH DATABASE delta")
    conn.close()
    return {"added": added, "dry_run": dry_run}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keys")
    k.add_argument("--db", required=True)
    k.add_argument("--device", required=True)
    k.add_argument("--out", required=True)
    e = sub.add_parser("export")
    e.add_argument("--db", required=True)
    e.add_argument("--device", required=True)
    e.add_argument("--out", required=True)
    e.add_argument("--watermark-file")
    e.add_argument("--keys")
    m = sub.add_parser("merge")
    m.add_argument("--db", required=True)
    m.add_argument("--delta", required=True)
    m.add_argument("--device", required=True)
    m.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    t0 = time.monotonic()
    db = os.path.expanduser(a.db)
    if a.cmd == "keys":
        res = keys(db, a.device, os.path.expanduser(a.out))
    elif a.cmd == "export":
        wm = None
        if a.watermark_file and os.path.exists(a.watermark_file) and not a.keys:
            with open(a.watermark_file) as f:
                wm = json.load(f)
        res = export(db, a.device, os.path.expanduser(a.out), watermark=wm,
                     keys_db=os.path.expanduser(a.keys) if a.keys else None)
    else:
        res = merge(db, os.path.expanduser(a.delta), a.device, dry_run=a.dry_run)
    res["seconds"] = round(time.monotonic() - t0, 2)
    print(json.dumps(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
