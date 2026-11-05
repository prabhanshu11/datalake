#!/usr/bin/env python3
"""Ingest the watch history (the cone icon on the bar) into the datalake: every video he played, in any player
(mpv, VLC, ...) and in the browser (YouTube etc.), on every machine.

His words 2026-11-06 (local-bootstrapping docs/mpv-history.md): "The feature should create and maintain its own
artifacts which are synced with my datalake as well."

    python3 scripts/ingest_media_history.py [--db datalake.db] [--no-pull]

Source: ~/.local/state/mpv-history/history.jsonl on each machine (written by the mpv script and by
media-history-recorder; one start / progress / end line per play, same id). Each run:
  1. copies this machine's file to data/media-history/<host>.jsonl (the datalake keeps its own copy),
  2. on the primary (laptop) also pulls the other machines' files over ssh (LAN alias first, Tailscale fallback,
     5 s timeouts, at most every 30 min; skipped quietly when unreachable),
  3. merges the lines of every data/media-history/*.jsonl by (host, id) and UPSERTs them.
Idempotent. Run by media-history-recorder after every play ends. Table (created here):
  media_plays  one row per play: host, id, player, kind (file|web), path, url, title, artist, duration, position,
               start_pos, started, ended, reason, source, video
Query examples:
  SELECT started, player, title, position, duration FROM media_plays ORDER BY started DESC LIMIT 20;
  SELECT title, url, position FROM media_plays WHERE kind = 'web' ORDER BY started DESC;
  SELECT path, MAX(position) FROM media_plays WHERE path LIKE '%DS9%' GROUP BY path ORDER BY MAX(started) DESC;
"""
import argparse
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                       "mpv-history", "history.jsonl")
COPIES = os.path.join(HERE, "data", "media-history")
PULL_FROM = [("desktop-lan", "desktop")]       # (LAN alias, Tailscale fallback) per other machine
PULL_EVERY = 1800
COLS = ["host", "id", "player", "kind", "path", "url", "title", "artist", "duration", "position", "start_pos",
        "started", "ended", "reason", "source", "video"]
SCHEMA = """
CREATE TABLE IF NOT EXISTS media_plays (
  host TEXT, id TEXT, player TEXT, kind TEXT, path TEXT, url TEXT, title TEXT, artist TEXT, duration REAL,
  position REAL, start_pos REAL, started TEXT, ended TEXT, reason TEXT, source TEXT, video INTEGER,
  PRIMARY KEY (host, id));
CREATE INDEX IF NOT EXISTS media_plays_started ON media_plays (started);
"""


def is_primary():
    try:
        with open(os.path.expanduser("~/Programs/local-bootstrapping/device-role.conf")) as f:
            return 'DEVICE_ROLE="primary"' in f.read()
    except OSError:
        return False


def copy_local():
    if not os.path.exists(HISTORY):
        return
    os.makedirs(COPIES, exist_ok=True)
    dest = os.path.join(COPIES, socket.gethostname() + ".jsonl")
    if not os.path.exists(dest) or os.path.getsize(dest) != os.path.getsize(HISTORY) \
            or os.path.getmtime(dest) < os.path.getmtime(HISTORY):
        shutil.copyfile(HISTORY, dest + ".tmp")
        os.replace(dest + ".tmp", dest)


def pull_others():
    stamp = os.path.join(COPIES, ".last-pull")
    try:
        if time.time() - os.path.getmtime(stamp) < PULL_EVERY:
            return
    except OSError:
        pass
    os.makedirs(COPIES, exist_ok=True)
    for aliases in PULL_FROM:
        for alias in aliases:
            try:
                r = subprocess.run(["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", alias,
                                    "hostname; cat ~/.local/state/mpv-history/history.jsonl 2>/dev/null"],
                                   capture_output=True, text=True, timeout=30)
            except subprocess.TimeoutExpired:
                continue
            if r.returncode not in (0, 1) or not r.stdout:
                continue
            host, _, body = r.stdout.partition("\n")
            host = host.strip()
            if host and host != socket.gethostname() and body.strip():
                with open(os.path.join(COPIES, host + ".jsonl.tmp"), "w", encoding="utf-8") as f:
                    f.write(body)
                os.replace(os.path.join(COPIES, host + ".jsonl.tmp"), os.path.join(COPIES, host + ".jsonl"))
            break
    with open(stamp, "w") as f:
        f.write(time.strftime("%Y-%m-%dT%H:%M:%S%z\n"))


def plays(path, host_default):
    by_id = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict) or rec.get("event") == "seed" or rec.get("source") == "inferred-atime":
                continue
            rid = rec.get("id")
            if not rid:
                continue
            by_id.setdefault(rid, {}).update({k: v for k, v in rec.items() if v is not None})
    for rid, p in by_id.items():
        p.setdefault("host", host_default)
        p.setdefault("player", "mpv" if p.get("source") == "mpv" else "")
        p.setdefault("kind", "web" if p.get("url") and not p.get("path") else "file")
        if p.get("position") is None:
            p["position"] = p.get("start_pos")
        p["video"] = 0 if p.get("video") is False else 1
        yield [p.get(c) for c in COLS]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(HERE, "datalake.db"))
    ap.add_argument("--no-pull", action="store_true")
    a = ap.parse_args()
    copy_local()
    if is_primary() and not a.no_pull:
        pull_others()
    files = sorted(f for f in os.listdir(COPIES) if f.endswith(".jsonl")) if os.path.isdir(COPIES) else []
    con = sqlite3.connect(a.db, timeout=60)
    con.executescript(SCHEMA)
    n = 0
    with con:
        for fn in files:
            rows = list(plays(os.path.join(COPIES, fn), fn[:-len(".jsonl")]))
            con.executemany(f"INSERT OR REPLACE INTO media_plays ({','.join(COLS)}) "
                            f"VALUES ({','.join('?' * len(COLS))})", rows)
            n += len(rows)
    print(f"media_plays: {n} plays from {len(files)} machine file(s)")


if __name__ == "__main__":
    main()
