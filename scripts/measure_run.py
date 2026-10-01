#!/usr/bin/env python3
"""Run a command and report what it cost the box (stdlib only).

Samples /proc/loadavg (1-min) and /proc/stat iowait/busy % once a second while the
command runs, and, if a star-trek-camera cycles.jsonl is given, the tracker's cycle
rate (c/s) during the run and in the same-length window just before it.

  measure_run.py --label NAME [--cycles PATH] -- cmd args...

Prints one JSON line (also appended to --out if given). Used for the before/after
numbers in star-trek-camera docs/night-1002/datalake-incr-REPORT.md.
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time


def cpu_times():
    with open("/proc/stat") as f:
        vals = [int(v) for v in f.readline().split()[1:]]
    total = sum(vals)
    iowait = vals[4]
    idle = vals[3] + iowait
    return total, idle, iowait


def cycles_rate(path, t0, t1):
    """Cycles per second with ts in [t0, t1), reading only the file's tail."""
    if not path or not os.path.exists(path) or t1 <= t0:
        return None
    size = os.path.getsize(path)
    chunk = 64 * 1024 * 1024
    with open(path, "rb") as f:
        f.seek(max(0, size - chunk))
        data = f.read()
    n = 0
    for line in data.splitlines():
        if b'"kind": "cycle"' not in line:
            continue
        try:
            ts = json.loads(line)["ts"]
        except Exception:
            continue
        if t0 <= ts < t1:
            n += 1
    return round(n / (t1 - t0), 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--cycles")
    ap.add_argument("--out")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd and a.cmd[0] == "--" else a.cmd

    samples, stop = [], threading.Event()

    def sampler():
        prev = cpu_times()
        while not stop.wait(1.0):
            cur = cpu_times()
            dt = max(1, cur[0] - prev[0])
            with open("/proc/loadavg") as f:
                load1 = float(f.read().split()[0])
            samples.append((load1, 100.0 * (cur[2] - prev[2]) / dt, 100.0 * (1 - (cur[1] - prev[1]) / dt)))
            prev = cur

    th = threading.Thread(target=sampler, daemon=True)
    t0 = time.time()
    th.start()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    t1 = time.time()
    stop.set()
    th.join()

    def stats(i):
        xs = sorted(s[i] for s in samples)
        if not xs:
            return None
        return {"mean": round(sum(xs) / len(xs), 2), "max": round(xs[-1], 2)}

    res = {
        "label": a.label, "start": time.strftime("%H:%M:%S", time.localtime(t0)),
        "seconds": round(t1 - t0, 1), "rc": proc.returncode,
        "load1": stats(0), "iowait_pct": stats(1), "busy_pct": stats(2), "n_samples": len(samples),
        "cps_during": cycles_rate(a.cycles, t0, t1),
        "cps_before": cycles_rate(a.cycles, t0 - max(60.0, t1 - t0), t0),
        "stdout_tail": proc.stdout.strip().splitlines()[-6:],
        "stderr_tail": proc.stderr.strip().splitlines()[-3:],
    }
    line = json.dumps(res)
    print(line)
    if a.out:
        with open(a.out, "a") as f:
            f.write(line + "\n")
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
