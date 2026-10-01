"""Incremental parse (parsers/claude_parser.py + parse_manifest).

Every run used to re-read all of ~/.claude (1.8 GB on the desktop), re-insert all
4 219 history lines (claude_history has no unique key) and upsert every message,
which rewrote its FTS5 entry. Now unchanged files are skipped and only new history
lines are read; --full restores the old full pass.
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from parsers import claude_parser  # noqa: E402

SID = "11111111-2222-3333-4444-555555555555"


def msg(i, text):
    return json.dumps({"type": "user", "uuid": f"u-{i}", "parentUuid": f"u-{i-1}" if i else None,
                       "sessionId": SID, "timestamp": f"2026-10-01T10:00:{i:02d}Z", "cwd": "/p",
                       "message": {"role": "user", "content": text}}) + "\n"


def hist(i):
    return json.dumps({"display": f"prompt {i}", "timestamp": 1_790_000_000_000 + i, "project": "/p",
                       "sessionId": SID}) + "\n"


def setup(tmp_path):
    claude = tmp_path / ".claude"
    proj = claude / "projects" / "-p"
    proj.mkdir(parents=True)
    (claude / "history.jsonl").write_text(hist(0) + hist(1))
    (proj / f"{SID}.jsonl").write_text(msg(0, "wombatique first") + msg(1, "second"))
    db = tmp_path / "dl.db"
    conn = sqlite3.connect(db)
    conn.executescript((ROOT / "schema_v2.sql").read_text())
    conn.executescript((ROOT / "scripts" / "migrate-add-explorer.sql").read_text())
    conn.close()
    return claude, proj, db


def run(claude, db, *extra):
    sys_argv = sys.argv
    sys.argv = ["claude_parser", "--claude-dir", str(claude), "--device", "desktop", "--db", str(db), *extra]
    try:
        claude_parser.main()
    finally:
        sys.argv = sys_argv
    conn = sqlite3.connect(db)
    out = {
        "history": conn.execute("SELECT count(*) FROM claude_history").fetchone()[0],
        "messages": conn.execute("SELECT count(*) FROM claude_messages").fetchone()[0],
        "hist_seq": conn.execute("SELECT seq FROM sqlite_sequence WHERE name='claude_history'").fetchone()[0],
        "fts_rows": conn.execute("SELECT count(*) FROM claude_messages_fts_docsize").fetchone()[0],
        "fts_hits": conn.execute("SELECT count(*) FROM claude_messages_fts WHERE claude_messages_fts MATCH 'wombatique'").fetchone()[0],
    }
    conn.close()
    return out


def test_second_run_skips_unchanged_and_appends_only_new(tmp_path, capsys):
    claude, proj, db = setup(tmp_path)
    first = run(claude, db)
    assert first["history"] == 2 and first["messages"] == 2 and first["fts_hits"] == 1

    second = run(claude, db)
    assert second == first                                # no duplicate history, nothing rewritten
    assert "skipped 1 unchanged" in capsys.readouterr().out

    with open(claude / "history.jsonl", "a") as f:
        f.write(hist(2))
    with open(proj / f"{SID}.jsonl", "a") as f:
        f.write(msg(2, "third"))
    third = run(claude, db)
    assert third["history"] == 3 and third["messages"] == 3 and third["fts_hits"] == 1
    assert third["fts_rows"] == 3


def test_partial_history_line_waits_for_next_run(tmp_path):
    claude, proj, db = setup(tmp_path)
    run(claude, db)
    with open(claude / "history.jsonl", "a") as f:
        f.write(hist(2)[:20])                             # writer mid-line
    assert run(claude, db)["history"] == 2
    with open(claude / "history.jsonl", "a") as f:
        f.write(hist(2)[20:])
    assert run(claude, db)["history"] == 3


def test_rewritten_history_is_reread_and_full_flag(tmp_path):
    claude, proj, db = setup(tmp_path)
    run(claude, db)
    (claude / "history.jsonl").write_text(hist(7))        # truncated/rotated: smaller file
    assert run(claude, db)["history"] == 3
    # --full is the old behaviour: re-reads everything (history has no unique key)
    assert run(claude, db, "--full")["history"] == 4
