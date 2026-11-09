#!/usr/bin/env python3
"""Does every photo the datalake shows still have a home it can be opened from?

Written after docs/incidents/2026-11-09-nas-photos-unreachable-away.md: zips
were moved (2026-10-02 laptop offload, 2026-11-01 T7 -> Seagate) and nothing
told the photo viewer, so every full image failed for weeks unnoticed.

For each takeout archive in the photo index (~/Programs/takeout-parser/local-
index.db) it asks the Pi, over `ssh pi5` (his channel order, from anywhere),
whether a sample of its photos is in the extracted copy and whether the zip is
in one of the archive dirs of local-bootstrapping dotfiles/network/nas.json.
One ssh call; nothing is copied.

    uv run python3 scripts/check_data_locations.py          # table, exit 1 if any archive has no home
    uv run python3 scripts/check_data_locations.py --json

RUN IT after moving ANY data the datalake points at (offloads, disk swaps,
re-extractions), and before saying photos "work from anywhere".
"""
import json
import shlex
import sqlite3
import subprocess
import sys
from pathlib import Path

INDEX = Path.home() / 'Programs' / 'takeout-parser' / 'local-index.db'
NAS_MAP = Path.home() / 'Programs' / 'local-bootstrapping' / 'dotfiles' / 'network' / 'nas.json'
SAMPLES = 5

REMOTE = r'''
import json, os, sys, zipfile
a = json.loads(sys.argv[1]); out = {}
for arch, members in a["archives"].items():
    ext = sum(os.path.isfile(os.path.join(a["extracted_root"], m)) for m in members)
    zips = [d for d in a["archive_dirs"] if os.path.isfile(os.path.join(d, arch))]
    zip_ok = None
    if zips:
        try:
            with zipfile.ZipFile(os.path.join(zips[0], arch)) as z:
                names = set(z.namelist())
            zip_ok = sum(m in names for m in members)
        except Exception as e:
            zip_ok = "unreadable: %s" % e.__class__.__name__
    out[arch] = {"extracted": ext, "zip_dirs": zips, "zip_members_found": zip_ok}
print(json.dumps(out))
'''


def main():
    as_json = '--json' in sys.argv
    photos = json.loads(NAS_MAP.read_text())['photos']
    db = sqlite3.connect(INDEX)
    rows = db.execute("SELECT source_archive, COUNT(*) FROM files WHERE source_service='photos' "
                      "GROUP BY 1 ORDER BY 1").fetchall()
    archives = {}
    for arch, _ in rows:
        archives[arch] = [r[0] for r in db.execute(
            "SELECT path FROM files WHERE source_service='photos' AND source_archive=? "
            "AND extension NOT IN ('.json') ORDER BY RANDOM() LIMIT ?", (arch, SAMPLES))]
    args = json.dumps({'archives': archives, 'extracted_root': photos['extracted_root'],
                       'archive_dirs': photos['archive_dirs']})
    route = subprocess.run(['home-route', 'pick', 'pi'], capture_output=True, text=True).stdout.strip()
    p = subprocess.run(['ssh', '-o', 'BatchMode=yes', 'pi5', 'python3 - ' + shlex.quote(args)],
                       input=REMOTE, capture_output=True, text=True, timeout=300)
    if p.returncode != 0:
        print(f"could not ask the Pi (route {route}, exit {p.returncode}): {p.stderr.strip()[-300:]}")
        return 2
    res = json.loads(p.stdout)
    bad = 0
    report = []
    for arch, count in rows:
        r = res[arch]
        n = len(archives[arch])
        homes = []
        if r['extracted'] == n and n:
            homes.append('extracted copy')
        if isinstance(r['zip_members_found'], int) and r['zip_members_found'] == n:
            homes.append('zip in ' + r['zip_dirs'][0])
        ok = bool(homes)
        bad += not ok
        report.append({'archive': arch, 'photos': count, 'ok': ok, 'homes': homes, 'raw': r})
    if as_json:
        print(json.dumps({'route': route, 'archives': report}, indent=1))
    else:
        print(f"asked the Pi via {route}; {SAMPLES} sample items per archive")
        for x in report:
            print(f"{'OK ' if x['ok'] else 'NO HOME'}  {x['archive']:<38} {x['photos']:>6} items  "
                  f"{' + '.join(x['homes']) or x['raw']}")
        print(f"{len(report) - bad}/{len(report)} archives reachable")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
