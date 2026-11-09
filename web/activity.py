"""What is moving right now: transfers, network speed per link, sync jobs.

His words 2026-11-09: "in the datalake UI, display upload/download speed from
now on, when operations happen... and any info about any sync operations that
are happening." Served as /api/activity and drawn by the activity dock in
web/templates/base.html on every page.

Three sources, all read from this machine only (nothing is sent anywhere):
  1. transfers the app itself makes (a photo from the Pi NAS): bytes, speed,
     channel, live while they run;
  2. bytes per second on each network link (/proc/net/dev, sampled every
     second): wlan0/ethernet, wg-vdi (VPS relay), tailscale0;
  3. sync jobs: the systemd user units that sync or refresh data (state, last
     run, next run, result) and any rsync/scp/sftp/rclone/... process with its
     read/write rate from /proc/<pid>/io.
"""
import os
import re
import subprocess
import threading
import time
from collections import deque

_LOCK = threading.Lock()
_ACTIVE = {}                 # id -> op dict
_RECENT = deque(maxlen=30)   # finished ops, newest last
_NEXT_ID = [1]

# ---- 1. transfers made by this app --------------------------------------------------


class Op:
    """One transfer. Use: op = start(...); op.add(n) per chunk; op.finish(ok, note)."""

    def __init__(self, kind, label, direction, route, total=None):
        with _LOCK:
            self.id = _NEXT_ID[0]
            _NEXT_ID[0] += 1
        self.kind, self.label, self.direction, self.route = kind, label, direction, route
        self.total = total
        self.bytes = 0
        self.started = time.time()
        self.ended = None
        self.ok = None
        self.note = ''
        with _LOCK:
            _ACTIVE[self.id] = self

    def add(self, n):
        self.bytes += n

    def finish(self, ok=True, note=''):
        if self.ended:
            return
        self.ended, self.ok, self.note = time.time(), ok, note
        with _LOCK:
            _ACTIVE.pop(self.id, None)
            _RECENT.append(self)

    def as_dict(self):
        dur = (self.ended or time.time()) - self.started
        return {
            'id': self.id, 'kind': self.kind, 'label': self.label,
            'direction': self.direction, 'route': self.route,
            'bytes': self.bytes, 'total': self.total,
            'seconds': round(dur, 1),
            'bps': round(self.bytes / dur) if dur > 0.05 else 0,
            'ok': self.ok, 'note': self.note,
            'ended_ago': round(time.time() - self.ended) if self.ended else None,
        }


def start(kind, label, direction='down', route='?', total=None):
    return Op(kind, label, direction, route, total)


# ---- 2 + process io: one sampler thread, every second -------------------------------

_LINKS = {}          # iface -> {'rx_bps', 'tx_bps', 'rx', 'tx'}
_PROCS = {}          # pid -> {'comm', 'args', 'read_bps', 'write_bps', 'started'}
_SKIP_IFACE = re.compile(r'^(lo|docker|br-|veth|virbr|vnet)')
TRANSFER_COMMS = {'rsync', 'scp', 'sftp', 'rclone', 'sshfs', 'wget', 'curl', 'yt-dlp',
                  'unzip', 'zip', 'tar', 'cp', 'mv', 'git-remote-http', 'git-remote-https'}
_SECRET = re.compile(r'(token|key|pass|secret|authorization|bearer)', re.I)


def _read_net():
    out = {}
    with open('/proc/net/dev') as f:
        for line in f.readlines()[2:]:
            name, rest = line.split(':', 1)
            name = name.strip()
            if _SKIP_IFACE.match(name):
                continue
            v = rest.split()
            out[name] = (int(v[0]), int(v[8]))
    return out


def _clean_args(argv):
    """The paths/hosts a transfer works on, never a secret-looking value."""
    keep = []
    for a in argv[1:]:
        if a.startswith('-') or _SECRET.search(a):
            continue
        if '/' in a or ':' in a:
            keep.append(a if len(a) < 70 else '…' + a[-69:])
    return ' → '.join(keep[-2:])


def _scan_procs(prev, dt):
    now = {}
    uid = os.getuid()
    for pid in os.listdir('/proc'):
        if not pid.isdigit():
            continue
        try:
            st = os.stat(f'/proc/{pid}')
            if st.st_uid != uid:
                continue
            with open(f'/proc/{pid}/comm') as f:
                comm = f.read().strip()
            if comm not in TRANSFER_COMMS:
                continue
            with open(f'/proc/{pid}/io') as f:
                io = dict(l.split(':') for l in f.read().split('\n') if ':' in l)
            r, w = int(io['rchar']), int(io['wchar'])
            with open(f'/proc/{pid}/cmdline', 'rb') as f:
                argv = [a.decode(errors='replace') for a in f.read().split(b'\0') if a]
        except (OSError, KeyError, ValueError):
            continue
        p = prev.get(pid)
        now[pid] = {
            'pid': int(pid), 'comm': comm, 'args': _clean_args(argv),
            'r': r, 'w': w,
            'read_bps': round((r - p['r']) / dt) if p else 0,
            'write_bps': round((w - p['w']) / dt) if p else 0,
            'started': p['started'] if p else time.time(),
        }
    return now


def _sampler():
    global _PROCS
    last_net, last_t = _read_net(), time.time()
    procs, n = {}, 0
    while True:
        time.sleep(1)
        t = time.time()
        dt = max(t - last_t, 0.001)
        try:
            net = _read_net()
            links = {}
            for name, (rx, tx) in net.items():
                p = last_net.get(name)
                if p:
                    links[name] = {'rx_bps': round((rx - p[0]) / dt), 'tx_bps': round((tx - p[1]) / dt)}
            last_net, last_t = net, t
            with _LOCK:
                _LINKS.clear()
                _LINKS.update(links)
            n += 1
            if n % 2 == 0:                       # processes every 2 s
                procs = _scan_procs(procs, 2.0)
                with _LOCK:
                    _PROCS = procs
        except Exception:
            pass


_started = [False]


def ensure_sampler():
    if not _started[0]:
        _started[0] = True
        threading.Thread(target=_sampler, name='activity-sampler', daemon=True).start()


# ---- 3. sync jobs (systemd user units) ----------------------------------------------

SYNC_UNITS = [
    # (unit, what it does, in his words where we have them)
    ('datalake-refresh', 'datalake: pull Claude conversations into datalake.db'),
    ('local-bootstrapping-sync', 'local-bootstrapping: pull configs from origin, self-heal'),
    ('datalake-healthcheck', 'datalake API health check (restarts it when down)'),
]
SYNC_NAME = re.compile(r'(sync|backup|offload|ingest|refresh|rsync|mirror|upload|download)', re.I)
_UNIT_CACHE = {'t': 0, 'data': []}


def _systemctl_show(unit, props):
    r = subprocess.run(['systemctl', '--user', 'show', unit, '-p', ','.join(props)],
                       capture_output=True, text=True, timeout=5)
    return dict(l.split('=', 1) for l in r.stdout.splitlines() if '=' in l)


def _ts(v):
    """systemd timestamps ('Mon 2026-11-09 19:35:06 IST') -> epoch or None."""
    if not v or v in ('n/a', '0'):
        return None
    try:
        r = subprocess.run(['date', '-d', v, '+%s'], capture_output=True, text=True, timeout=2)
        return int(r.stdout.strip())
    except Exception:
        return None


def sync_units():
    if time.time() - _UNIT_CACHE['t'] < 10:
        return _UNIT_CACHE['data']
    units = list(SYNC_UNITS)
    try:   # any other active user service whose name says it syncs/moves data
        r = subprocess.run(['systemctl', '--user', 'list-units', '--type=service', '--state=active,activating',
                            '--no-legend', '--plain'], capture_output=True, text=True, timeout=5)
        known = {u for u, _ in units}
        for line in r.stdout.splitlines():
            name = line.split()[0].removesuffix('.service') if line.split() else ''
            if name and name not in known and SYNC_NAME.search(name):
                units.append((name, 'running service (name matches sync/backup/offload…)'))
    except Exception:
        pass
    out = []
    for unit, what in units:
        try:
            s = _systemctl_show(unit + '.service', ['ActiveState', 'SubState', 'Result',
                                                    'ExecMainStartTimestamp', 'ExecMainExitTimestamp',
                                                    'ExecMainStatus', 'LoadState'])
            if s.get('LoadState') == 'not-found':
                continue
            tm = _systemctl_show(unit + '.timer', ['ActiveState', 'SubState', 'NextElapseUSecRealtime',
                                                   'LastTriggerUSec', 'LoadState'])
        except Exception:
            continue
        has_timer = tm.get('LoadState') == 'loaded'
        out.append({
            'unit': unit, 'what': what,
            'running': s.get('ActiveState') in ('active', 'activating') and s.get('SubState') != 'exited',
            'state': f"{s.get('ActiveState')}/{s.get('SubState')}",
            'result': s.get('Result'), 'exit_status': s.get('ExecMainStatus'),
            'last_start': _ts(s.get('ExecMainStartTimestamp')),
            'last_end': _ts(s.get('ExecMainExitTimestamp')),
            'timer': (tm.get('ActiveState') if has_timer else None),
            'next_run': _ts(tm.get('NextElapseUSecRealtime')) if has_timer else None,
            'last_trigger': _ts(tm.get('LastTriggerUSec')) if has_timer else None,
            # "elapsed" with no next run = the timer will never fire again on its own
            # (found 2026-11-09: three laptop sync timers stuck like this since 2026-10-06).
            'stuck': bool(has_timer and tm.get('ActiveState') == 'active'
                          and tm.get('SubState') == 'elapsed' and not tm.get('NextElapseUSecRealtime')),
        })
    _UNIT_CACHE.update(t=time.time(), data=out)
    return out


def snapshot():
    ensure_sampler()
    with _LOCK:
        active = [o.as_dict() for o in _ACTIVE.values()]
        recent = [o.as_dict() for o in list(_RECENT)[-8:]][::-1]
        links = dict(_LINKS)
        procs = [{k: v for k, v in p.items() if k not in ('r', 'w')} for p in _PROCS.values()]
    for p in procs:
        p['seconds'] = round(time.time() - p.pop('started'))
    return {'now': time.time(), 'links': links, 'active': active, 'recent': recent,
            'processes': procs, 'sync_units': sync_units()}
