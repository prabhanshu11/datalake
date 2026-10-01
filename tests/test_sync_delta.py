"""Incremental secondary -> primary sync (scripts/sync_delta.py).

The old path copied the whole 23 GB desktop DB every 30 min. These tests pin the
incremental path: reconcile (first run, no watermark) and watermark runs move only
the missing rows, the FTS5 index on the primary finds them, history keys are not
duplicated, --dry-run changes nothing, and the source DB is never written.
"""
import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
spec = importlib.util.spec_from_file_location("sync_delta", ROOT / "scripts" / "sync_delta.py")
sync_delta = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync_delta)


def make_db(path):
    conn = sqlite3.connect(path)
    conn.executescript((ROOT / "schema_v2.sql").read_text())
    conn.execute("PRAGMA journal_mode=WAL")
    conn.commit()
    return conn


def add_session(conn, sid, device, n_msgs, word, ts="2026-10-01T10:00:00"):
    conn.execute(
        "INSERT INTO claude_sessions (session_id, project_path, source_device, started_at) VALUES (?, '/p', ?, ?)",
        (sid, device, ts))
    db_id = conn.execute("SELECT id FROM claude_sessions WHERE session_id = ?", (sid,)).fetchone()[0]
    for i in range(n_msgs):
        add_message(conn, db_id, f"{sid}-m{i}", f"{word} message {i}", ts)
    conn.commit()
    return db_id


def add_message(conn, session_db_id, uuid, text, ts="2026-10-01T10:00:00"):
    conn.execute(
        "INSERT INTO claude_messages (session_id, message_uuid, message_type, role, content_text, timestamp) "
        "VALUES (?, ?, 'user', 'user', ?, ?)", (session_db_id, uuid, text, ts))


def add_history(conn, sid, device, ts_unix, display, copies=1):
    for _ in range(copies):  # the parser used to re-insert every history line on every run
        conn.execute(
            "INSERT INTO claude_history (session_id, display, project, source_device, timestamp, timestamp_unix) "
            "VALUES (?, ?, '/p', ?, 'x', ?)", (sid, display, device, ts_unix))
    conn.commit()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def count(conn, sql, *args):
    return conn.execute(sql, args).fetchone()[0]


@pytest.fixture
def pair(tmp_path):
    src_path, dst_path = tmp_path / "desktop.db", tmp_path / "laptop.db"
    src, dst = make_db(src_path), make_db(dst_path)
    now = 1_790_000_000_000
    # Already synced in the past (present on both sides)
    add_session(src, "s-old", "desktop", 3, "alpha")
    add_session(dst, "s-old", "desktop", 3, "alpha")
    add_history(src, "s-old", "desktop", now - 10 * 86400_000, "old prompt", copies=5)
    add_history(dst, "s-old", "desktop", now - 10 * 86400_000, "old prompt")
    # Desktop-only, never synced: a new session + a new message on the old session
    add_session(src, "s-new", "desktop", 2, "zebracorn")
    old_id = src.execute("SELECT id FROM claude_sessions WHERE session_id='s-old'").fetchone()[0]
    add_message(src, old_id, "s-old-m3", "quokkaline appended later")
    add_history(src, "s-new", "desktop", now, "new prompt", copies=4)
    # A laptop session on the primary and one on the desktop DB must not travel
    add_session(src, "s-lap", "laptop", 1, "laptoponly")
    add_session(dst, "s-primary", "laptop", 1, "primaryonly")
    src.commit()
    src.close()
    dst.close()
    return src_path, dst_path, tmp_path


def run_reconcile(src_path, dst_path, tmp_path):
    keys_db, delta = str(tmp_path / "keys.db"), str(tmp_path / "delta.db")
    sync_delta.keys(str(dst_path), "desktop", keys_db)
    exp = sync_delta.export(str(src_path), "desktop", delta, keys_db=keys_db)
    res = sync_delta.merge(str(dst_path), delta, "desktop")
    return exp, res


def test_reconcile_moves_only_missing_rows_and_fts_finds_them(pair):
    src_path, dst_path, tmp_path = pair
    src_hash = sha(src_path)
    exp, res = run_reconcile(src_path, dst_path, tmp_path)

    assert exp["mode"] == "reconcile"
    assert exp["rows"]["claude_messages"] == 3          # 2 new-session msgs + 1 appended
    # 4 copies of the new key -> 1; the old key is inside the 2-day window before the
    # primary's newest row, travels once and is deduped by the merge
    assert exp["rows"]["claude_history"] == 2
    assert res["added"] == {"claude_history": 1, "claude_sessions": 1, "claude_messages": 3}
    assert sha(src_path) == src_hash                    # source never written

    dst = sqlite3.connect(dst_path)
    assert count(dst, "SELECT count(*) FROM claude_messages_fts WHERE claude_messages_fts MATCH 'zebracorn'") == 2
    assert count(dst, "SELECT count(*) FROM claude_messages_fts WHERE claude_messages_fts MATCH 'quokkaline'") == 1
    assert count(dst, "SELECT count(*) FROM claude_history_fts WHERE claude_history_fts MATCH 'new'") == 1
    assert count(dst, "SELECT count(*) FROM claude_sessions WHERE session_id = 's-lap'") == 0
    assert count(dst, "SELECT count(*) FROM claude_history WHERE session_id = 's-old'") == 1
    # The appended message hangs off the primary's own id for s-old
    assert count(dst, "SELECT count(*) FROM claude_messages m JOIN claude_sessions s ON s.id = m.session_id "
                      "WHERE s.session_id = 's-old'") == 4
    dst.execute("INSERT INTO claude_messages_fts(claude_messages_fts) VALUES ('integrity-check')")


def test_watermark_run_moves_only_rows_inserted_since(pair):
    src_path, dst_path, tmp_path = pair
    exp, _ = run_reconcile(src_path, dst_path, tmp_path)
    wm = exp["watermark"]

    # Nothing new -> empty delta
    delta = str(tmp_path / "delta2.db")
    exp2 = sync_delta.export(str(src_path), "desktop", delta, watermark=wm)
    assert exp2["mode"] == "watermark"
    assert exp2["rows"] == {"claude_history": 0, "claude_sessions": 0, "claude_messages": 0}

    # One new message on an existing session + one new history line (+ a duplicate copy)
    src = sqlite3.connect(src_path)
    new_id = src.execute("SELECT id FROM claude_sessions WHERE session_id='s-new'").fetchone()[0]
    add_message(src, new_id, "s-new-m9", "narwhalix tick two")
    add_history(src, "s-new", "desktop", 1_790_000_100_000, "tick two prompt", copies=2)
    src.commit()
    src.close()

    exp3 = sync_delta.export(str(src_path), "desktop", delta, watermark=exp2["watermark"])
    assert exp3["rows"] == {"claude_history": 1, "claude_sessions": 1, "claude_messages": 1}
    res = sync_delta.merge(str(dst_path), delta, "desktop")
    assert res["added"] == {"claude_history": 1, "claude_sessions": 0, "claude_messages": 1}
    dst = sqlite3.connect(dst_path)
    assert count(dst, "SELECT count(*) FROM claude_messages_fts WHERE claude_messages_fts MATCH 'narwhalix'") == 1

    # Re-merging the same delta is a no-op (safe to retry after a failed watermark write)
    again = sync_delta.merge(str(dst_path), delta, "desktop")
    assert again["added"] == {"claude_history": 0, "claude_sessions": 0, "claude_messages": 0}


def test_dry_run_changes_nothing(pair):
    src_path, dst_path, tmp_path = pair
    keys_db, delta = str(tmp_path / "keys.db"), str(tmp_path / "delta.db")
    sync_delta.keys(str(dst_path), "desktop", keys_db)
    sync_delta.export(str(src_path), "desktop", delta, keys_db=keys_db)
    dst = sqlite3.connect(dst_path)
    before = [count(dst, f"SELECT count(*) FROM {t}") for t in sync_delta.TABLES]
    dst.close()
    res = sync_delta.merge(str(dst_path), delta, "desktop", dry_run=True)
    assert res["added"]["claude_messages"] == 3 and res["dry_run"]
    dst = sqlite3.connect(dst_path)
    assert [count(dst, f"SELECT count(*) FROM {t}") for t in sync_delta.TABLES] == before


def test_cli_export_reads_watermark_file(pair, capsys):
    src_path, dst_path, tmp_path = pair
    exp, _ = run_reconcile(src_path, dst_path, tmp_path)
    wm_file = tmp_path / "wm.json"
    wm_file.write_text(json.dumps(exp["watermark"]))
    assert sync_delta.main(["export", "--db", str(src_path), "--device", "desktop",
                            "--out", str(tmp_path / "d.db"), "--watermark-file", str(wm_file)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "watermark" and out["rows"]["claude_messages"] == 0


def _fake_remote(tmp_path):
    """ssh/scp shims: the 'primary' is a local HOME dir, so the shell script runs end to end."""
    import os
    import stat
    home, bindir = tmp_path / "remote_home", tmp_path / "bin"
    home.mkdir()
    bindir.mkdir()
    (bindir / "ssh").write_text(
        '#!/usr/bin/env bash\nwhile [[ "$1" == -* ]]; do [[ "$1" == -o ]] && shift; shift; done\n'
        f'shift\ncd "{home}" && HOME="{home}" exec bash -c "$*"\n')
    (bindir / "scp").write_text(
        '#!/usr/bin/env bash\nargs=()\nfor a in "$@"; do [[ "$a" == -* ]] && continue; '
        f'if [[ "$a" == *:* ]]; then a="{home}/${{a#*:}}"; fi; args+=("$a"); done\nexec cp "${{args[@]}}"\n')
    for f in ("ssh", "scp"):
        (bindir / f).chmod((bindir / f).stat().st_mode | stat.S_IEXEC)
    return home, bindir


def test_shell_script_incremental_end_to_end(pair):
    import os
    import subprocess
    src_path, dst_path, tmp_path = pair
    home, bindir = _fake_remote(tmp_path)
    remote_db = home / "laptop.db"
    remote_db.write_bytes(Path(dst_path).read_bytes())
    src_hash = sha(src_path)
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", LOCAL_DB=str(src_path),
               REMOTE_HOST="fakehost", REMOTE_DB=str(remote_db), LOCAL_DEVICE="desktop",
               DEVICE_CONFIG="/nonexistent", LOG_DIR=str(tmp_path / "logs"),
               STATE_DIR=str(tmp_path / "state"))
    script = ROOT / "scripts" / "sync-to-primary.sh"

    def run(**extra):
        r = subprocess.run(["bash", str(script)], env=dict(env, **extra), capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stdout + r.stderr
        return r.stdout

    out = run(DRY_RUN="1")                                    # dry run: nothing merged, no watermark
    assert "reconciling" in out and "DRY_RUN=1" in out
    assert not (tmp_path / "state" / "sync-watermark-desktop.json").exists()
    out = run()                                               # first real run: reconcile
    assert '"claude_messages": 3' in out
    assert (tmp_path / "state" / "sync-watermark-desktop.json").exists()
    out = run()                                               # second run: watermark, nothing new
    assert "Nothing new since the watermark" in out
    dst = sqlite3.connect(remote_db)
    assert count(dst, "SELECT count(*) FROM claude_messages_fts WHERE claude_messages_fts MATCH 'zebracorn'") == 2
    # Source only gained its own sync_log rows; no snapshot files left behind
    assert list((tmp_path / "state").glob("*.db")) == []
    assert not list(home.glob(".cache/datalake/*.db"))
