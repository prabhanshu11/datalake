#!/usr/bin/env python3
"""Ingest ~/Programs/agent-tracker into the datalake: every scheduled / event agent and loop on his machines, their runs,
what was paused or stopped and why, the journals archived when they were stopped, and per-call token usage (telemetry).

His words 2026-11-02 (agent-tracker): "Make sure the stopped ones also accessible by future agents somewhene in thefilesystem,
so thta they are not lost or if they have to be erused, or their runs examined its accessible throguh datalake itself..."

    python3 scripts/ingest_agents.py [--db datalake.db] [--tracker ~/Programs/agent-tracker]

Idempotent (INSERT OR IGNORE / UPSERT); run by agent-tracker after every collector run. Tables (created here):
  agent_units    one row per (host, unit): what it is, schedule, command, models/effort, state (active/paused/stopped/off),
                 archive path, last result + last log lines. Paused/stopped units stay forever.
  agent_runs     one row per run start seen in any snapshot (history grows beyond the 7-day journal window).
  agent_actions  archive/registry.jsonl: every pause / resume / run / reschedule, who did it, why, his words.
  agent_journal  the journal lines archived when a unit was paused (archive/<host>/<unit>/journal-7d-*.jsonl.gz).
  agent_calls    one row per Claude API request reported by the local telemetry sink (model, tokens, cost, unit, cwd).
Query examples:
  SELECT host, unit, state, why FROM agent_units WHERE state != 'active';
  SELECT * FROM agent_runs WHERE unit LIKE 'strek-triage-watch%' ORDER BY started_at DESC LIMIT 20;
  SELECT unit, model, SUM(input_tokens+cache_read_tokens+cache_creation_tokens) ctx, SUM(cost_usd) FROM agent_calls GROUP BY 1, 2;
"""
import argparse
import glob
import gzip
import json
import os
import sqlite3

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_units (
  host TEXT, unit TEXT, scope TEXT, kind TEXT, category TEXT, description TEXT, about TEXT, schedule TEXT, command TEXT,
  cwd TEXT, unit_file TEXT, models TEXT, efforts TEXT, state TEXT, state_since TEXT, why TEXT, archive_path TEXT,
  last_run TEXT, last_result TEXT, last_log TEXT, runs_7d INTEGER, fails_7d INTEGER, first_seen TEXT, last_seen TEXT,
  PRIMARY KEY (host, unit));
CREATE TABLE IF NOT EXISTS agent_runs (host TEXT, unit TEXT, started_at TEXT, result TEXT, PRIMARY KEY (host, unit, started_at));
CREATE TABLE IF NOT EXISTS agent_actions (at TEXT, host TEXT, unit TEXT, action TEXT, why TEXT, his_words TEXT, by TEXT, archive TEXT,
  PRIMARY KEY (at, host, unit, action));
CREATE TABLE IF NOT EXISTS agent_journal (host TEXT, unit TEXT, ts TEXT, source TEXT, message TEXT, archive_file TEXT,
  PRIMARY KEY (host, unit, ts, message));
CREATE TABLE IF NOT EXISTS agent_calls (at TEXT, host TEXT, unit TEXT, cwd TEXT, session_id TEXT, model TEXT, effort TEXT,
  input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER, cache_creation_tokens INTEGER, cost_usd REAL,
  duration_ms INTEGER, pid INTEGER, caller TEXT, PRIMARY KEY (at, host, session_id, input_tokens, output_tokens));
CREATE INDEX IF NOT EXISTS agent_runs_unit ON agent_runs (unit, started_at);
CREATE INDEX IF NOT EXISTS agent_calls_unit ON agent_calls (unit, at);
CREATE TABLE IF NOT EXISTS agent_ingest_files (path TEXT PRIMARY KEY, size INTEGER);
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(HERE, "datalake.db"))
    ap.add_argument("--tracker", default=os.path.expanduser("~/Programs/agent-tracker"))
    a = ap.parse_args()
    con = sqlite3.connect(a.db, timeout=60)
    con.executescript(SCHEMA)
    snap = json.load(open(os.path.join(a.tracker, "data", "snapshot.json")))
    now = snap["generated_at"]

    # actions first: they decide the state of a unit
    state = {}
    reg = os.path.join(a.tracker, "archive", "registry.jsonl")
    n_act = 0
    if os.path.exists(reg):
        for line in open(reg):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            con.execute("INSERT OR IGNORE INTO agent_actions VALUES (?,?,?,?,?,?,?,?)",
                        (r["at"], r["host"], r["unit"], r["action"], r.get("why"), r.get("his_words"), r.get("by"), r.get("archive")))
            n_act += 1
            if r["action"] in ("pause", "resume", "stop"):
                state[(r["host"], r["unit"])] = ("active" if r["action"] == "resume" else "paused", r["at"], r.get("why"), r.get("archive"))

    n_units = n_runs = 0
    seen = set()
    for h in snap["hosts"]:
        d = h.get("data")
        if not d:
            continue
        for t in d["triggers"]:
            if t.get("vendor") or t.get("kind") == "hook":
                continue
            key = (h["name"], t["id"])
            seen.add(key)
            llm = t.get("llm") or {}
            st = state.get(key)
            on = bool(t.get("next")) or t.get("active") == "active"
            s = st[0] if st and st[0] == "paused" else ("active" if on else "off")
            con.execute("""INSERT INTO agent_units VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(host, unit) DO UPDATE SET kind=excluded.kind, category=excluded.category, description=excluded.description,
              about=excluded.about, schedule=excluded.schedule, command=excluded.command, cwd=excluded.cwd, unit_file=excluded.unit_file,
              models=excluded.models, efforts=excluded.efforts, state=excluded.state,
              state_since=COALESCE(excluded.state_since, agent_units.state_since), why=COALESCE(excluded.why, agent_units.why),
              archive_path=COALESCE(excluded.archive_path, agent_units.archive_path), last_run=excluded.last_run,
              last_result=excluded.last_result, last_log=excluded.last_log, runs_7d=excluded.runs_7d, fails_7d=excluded.fails_7d,
              last_seen=excluded.last_seen""",
                        (h["name"], t["id"], t.get("scope"), t.get("kind"), (t.get("agent") or {}).get("class"),
                         t.get("description"), t.get("about"), json.dumps(t.get("schedule")), json.dumps(t.get("command")),
                         t.get("cwd"), t.get("unit_file"), json.dumps(llm.get("models")), json.dumps(llm.get("efforts")), s,
                         st[1] if st else None, st[2] if st else None, st[3] if st else None, t.get("last"), t.get("result"),
                         "\n".join(t.get("log_tail") or [])[-4000:], t.get("runs_total_7d"), t.get("fails_7d"), now, now))
            n_units += 1
            for r in t.get("runs") or []:
                cur = con.execute("INSERT OR IGNORE INTO agent_runs VALUES (?,?,?,?)", (h["name"], t["id"], r["t"], r["result"]))
                n_runs += cur.rowcount
    # paused units that no longer show in a probe (e.g. a host unreachable) keep their row; mark paused from the registry
    for (host, unit), st in state.items():
        if (host, unit) not in seen:
            con.execute("""INSERT INTO agent_units (host, unit, state, state_since, why, archive_path, first_seen, last_seen)
              VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(host, unit) DO UPDATE SET state=excluded.state, state_since=excluded.state_since,
              why=excluded.why, archive_path=excluded.archive_path""", (host, unit, st[0], st[1], st[2], st[3], now, now))

    # archived journals (one-time per file)
    n_j = 0
    for f in glob.glob(os.path.join(a.tracker, "archive", "*", "*", "journal-*.jsonl.gz")):
        size = os.path.getsize(f)
        if con.execute("SELECT 1 FROM agent_ingest_files WHERE path=? AND size=?", (f, size)).fetchone():
            continue
        host, unit = f.split(os.sep)[-3], f.split(os.sep)[-2]
        rows = []
        with gzip.open(f, "rt", errors="replace") as fh:
            for line in fh:
                try:
                    j = json.loads(line)
                except ValueError:
                    continue
                msg = j.get("MESSAGE")
                if isinstance(msg, list):
                    msg = bytes(msg).decode("utf-8", "replace")
                rows.append((host, unit, j.get("__REALTIME_TIMESTAMP"), j.get("SYSLOG_IDENTIFIER") or j.get("_COMM"), msg,
                             os.path.relpath(f, a.tracker)))
        con.executemany("INSERT OR IGNORE INTO agent_journal VALUES (?,?,?,?,?,?)", rows)
        con.execute("INSERT OR REPLACE INTO agent_ingest_files VALUES (?,?)", (f, size))
        n_j += len(rows)

    # telemetry calls (data/calls/<host>.jsonl, written by the collector from each host's sink)
    n_c = 0
    for f in glob.glob(os.path.join(a.tracker, "data", "calls", "*.jsonl")):
        host = os.path.basename(f)[:-6]
        for line in open(f):
            try:
                c = json.loads(line)
            except ValueError:
                continue
            cur = con.execute("INSERT OR IGNORE INTO agent_calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (c.get("at"), host, c.get("unit"), c.get("cwd"), c.get("session_id"), c.get("model"), c.get("effort"),
                               c.get("input_tokens"), c.get("output_tokens"), c.get("cache_read_tokens"), c.get("cache_creation_tokens"),
                               c.get("cost_usd"), c.get("duration_ms"), c.get("pid"), c.get("caller")))
            n_c += cur.rowcount
    con.commit()
    print("agents ingest: units %d, new runs %d, actions %d, journal lines %d, new calls %d" % (n_units, n_runs, n_act, n_j, n_c))


if __name__ == "__main__":
    main()
