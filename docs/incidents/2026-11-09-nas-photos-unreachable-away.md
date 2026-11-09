# Incident 2026-11-09: photos (and most of the NAS) unreachable away from home

## His words (verbatim, 2026-11-09, in Kanpur, on a phone hotspot)

> in recent days, since I've been in kanpur, I have realized my NAS setup is not as
> accessible as calude agents have led me to believe in the past year.
> When I try to access many of my items, like tv series folders, photos etc. I was
> not able to access them.
> recently an agent worked on it ... it promised me that it has solved the problem
> and now it will first use VPS, then try to access through tailscale as the last
> backup. but now I tried accessing my datalake's photos, and for each photo, it
> gives me an error, "full image not available on this host"

> docemnet this failure and absence of foresight from both of us in the datalake
> repo. In future this should not happen.. imagine google drive/photos like
> seamless behaviour.

And, while the fix was being built:

> Are you trying to be lazy and download all the photos ? what will you do ?
> continously download all my data to all my devices ?

> before coming to kanpur, I purposefully cleared space from this laptop...

## What he saw

Every photo in `http://localhost:5050/files/photos` opened as a blurry thumbnail
with "full image not available on this host". The Thunar bookmarks for the Pi's
drives and the desktop HDD did not open. The `/mnt/rpi5/DS9` folder hung Thunar.

## Why, layer by layer

| # | Fault | Since | How long unnoticed |
|---|---|---|---|
| 1 | `/api/photos/full` was built **laptop-only**: it read the zip from `~/Downloads` and returned 503 for anything else ("For Pi5-side zips (9-001/002/003), returns 503 — uses thumb"). 2021-2024 full images never worked on any machine. | 2026-05-15 (`39255f0`) | 6 months |
| 2 | The Pi unzipped 9-001..003 to `/mnt/nas/elements/google-photos-extracted`. The viewer was never told. | 2026-02-14 | 9 months |
| 3 | The ssh alias `pi5` pointed at `192.168.29.10`, an address that no longer existed. embedded-device-bootstrapping CLAUDE.md wrote it down as dead on 2026-04-10. An agent noticed again on 2026-07-20 (`setup-ssh.sh` comment, `26ca17f`) and **added `pi5-lan` beside it instead of fixing it**. Every datalake Pi feature (status, search, extract) and agent-tracker's fallback kept calling the dead one. | dead since 2026-04-10 | 7 months |
| 4 | The laptop offload moved zips 9-004/9-005 (most of 2025) from `~/Downloads` to the Pi's Elements drive. The viewer's only source vanished. **No one asked "who reads these files?"** before moving them. | 2026-10-02 | 5 weeks |
| 5 | The T7 SSD's contents moved to the Seagate. `/mnt/nas/t7` became empty, and the datalake's extract endpoint still pointed there. | 2026-11-01 | 1 week |
| 6 | The 2026-11-06 fix (`b0fca8f`, `6dc50c2`) made **video playback** (mpv-history) go LAN → VPS relay → Tailscale. It was described as solving NAS access. No one listed the other programs that read the NAS, so photos, Thunar and the datalake Pi features stayed broken. | 2026-11-06 | 3 days |
| 7 | Thunar bookmarks were bare LAN IPs (`sftp://pi@192.168.0.2/...`). They can only work at home. | 2026-10 | until he travelled |
| 8 | The Pi's Tailscale was logged out. This was written down as "needs his login" on 11-06 but never brought to him as a one-tap action. | ≤ 2026-11-06 | 3+ days |
| 9 | Found by the new activity bar: six laptop user timers (`local-bootstrapping-sync`, `datalake-refresh`, `datalake-healthcheck`, `clipboard-health`, `moonlight-health`, `wallpaper-rotate`) **stuck since 2026-10-06**: "elapsed", no next run, no alarm. Cause: `OnBootSec` in a user manager counts from system boot; his session started ~10 min after boot, so the first run never came and `OnUnitActiveSec` had nothing to count from. | 2026-10-06 | 34 days |

## Absence of foresight: ours (the agents)

- **Building for the machine we were sitting on.** The viewer, the bookmarks and the
  ssh alias were each written so they worked at home on the day of writing. None
  asked "does this work from a hotspot in another city?", even though the laptop
  is the machine that travels.
- **Moving data without checking who reads it.** Two moves (10-02, 11-01) changed
  where photos live. Nothing searched the code for the old paths, and there was no
  shared list of data locations to update.
- **Working around a broken thing instead of fixing it.** The dead `pi5` alias was
  noticed and kept. A workaround that leaves the broken name in place means every
  caller that uses that name stays broken.
- **Fixing the symptom that was reported, then calling the whole area solved.** The
  11-06 work fixed videos and its summary read as "the NAS now works from away".
  The other programs that read the NAS were never listed or tested.
- **"Works" was never proven from away.** Every test ran on the home LAN, where
  everything works.
- **Silent failure.** "full image not available on this host" told him nothing:
  not where the photo was, what was tried, or why it failed. The stuck timers had no alarm at all.

## Absence of foresight: his side (he asked for both)

- He travelled without one away-from-home rehearsal: opening a photo, a TV series
  and a Thunar bookmark from the phone hotspot while still at home.
- "Solved" claims were accepted on the agent's word, without asking for proof from
  outside the home network.
- The Pi's Tailscale stayed logged out. It needs his login, and the request to him
  was easy to miss.

## Target: Google Drive / Google Photos behaviour

What "seamless" means here, measured against what he gets from Google:

1. **Any item opens from anywhere.** Where the bytes are (laptop, Pi, desktop) is the
   system's problem, never his. A UI that lists an item can open it on any network.
2. **The system knows where everything is.** One map
   (`local-bootstrapping/dotfiles/network/nas.json`) says where each kind of data
   lives. Programs read the map and never hard-code a path or an IP.
3. **Moving data updates the map in the same change**, then
   `scripts/check_data_locations.py` proves every archive still has a home.
4. **It is honest about the network.** While an item loads, the UI shows the channel and
   the live speed. When it can't load, the UI says what was tried and what failed.
5. **It does not fill his disks.** Opening an item streams it. Nothing is
   synced, mirrored or cached on the laptop unless he asks (`Cache-Control: no-store`).
6. **Sync is visible.** Every sync job shows when it last ran and when it will
   next run. A stuck or failed job shows in red where he looks.

## What was built 2026-11-09

| Piece | Where |
|---|---|
| One ssh name per home machine, channel picked in his order (LAN → VPS relay → Tailscale); a channel counts only if its sshd answers; a stalled channel is skipped for 2 min | local-bootstrapping `dotfiles/local-bin/home-route`, `dotfiles/ssh/home-routes.conf` (`e56558e`) |
| Photos stream from the Pi: the extracted copy first, then the zip; a screen-sized JPEG; no-store | `web/nas_photo.py`, `/api/photos/full` (`2d2698a` and this commit) |
| Thunar bookmarks on `sftp://pi5/...`, `sftp://desktop-auto/...` | local-bootstrapping `dotfiles/gtk-3.0/bookmarks` |
| Activity bar on every datalake page: speed per link (Wi-Fi, VPS relay, Tailscale), each transfer live (bytes, %, speed, channel), recent transfers, sync jobs (running / stuck / failed, last and next run), other programs moving files | `web/activity.py`, `web/templates/activity_dock.html`, `/api/activity` |
| Data-location check: every photo archive in the index has a reachable home | `scripts/check_data_locations.py` (2026-11-09: 7/7 archives, 47,494 photos, 4 s over the relay) |

Measured 2026-11-09 from the Kanpur hotspot (moto g14, -78 dBm): a 2025 photo
loaded in his Chrome "via VPS relay in 9.3 s". An extracted 2024 photo took 1.6 s.
A stalled relay fell through to Tailscale (20 s) and the photo still loaded.

## Rules that stop this happening again

1. **Away-first test.** Nothing that reads home data is "done" until it has worked
   from outside the home network (a hotspot, or `HOME_ROUTE_SKIP="lan" ...` to
   simulate it). The claim quotes the channel and the time measured.
2. **Before moving data, search for its readers.** `git grep` the old path in every
   repo under `~/Programs`, update `nas.json`, then run
   `scripts/check_data_locations.py`. A move that leaves a reader pointing at the
   old path is not finished.
3. **No new picker, no IPs in app code.** Use `pi5` / `desktop-auto`. A dead name is
   fixed where it is defined, never worked around with a second name.
4. **Fixing one consumer means listing all of them.** A fix to "NAS access" names
   every program that reads the NAS and says which ones it covers
   (`local-bootstrapping docs/network-and-nas.md` §"Every service that reads the NAS").
5. **Errors say what was tried.** Never "not available on this host": give the
   place, the channel, and the reason.
6. **Anything that needs his hands goes to him as a one-tap action** (a terminal
   popped up at the right prompt), not as a line in a doc.
7. **Remote access never copies his data** onto the laptop by default.

## Done later the same day (his two yeses)

- `local-bootstrapping-sync` and `datalake-healthcheck` run again: `OnActiveSec`
  replaces `OnBootSec` (local-bootstrapping `6d1d01e`).
- The Pi is a member of the VPS relay at 10.77.0.4 (vps_bootstrap `41f2b67`,
  local-bootstrapping `a0c7ec9`), and its Tailscale is logged in again
  (100.124.200.77, from a terminal popped up over `ssh pi5`). `pi5` now tries the
  Pi's own relay address first: a fresh ssh takes 0.45 s (was 3.7 s via the
  desktop), and a 0.55 MB photo 5.5 s (was 8-10 s) on the same hotspot.
- Speeds are shown in KB/s and MB/s (his "sane" units).

## Still open (2026-11-09)

- `datalake-refresh` stays stuck until he is home: its first run pulls a month of
  datalake data onto the laptop. Fix it the same way then.
- `clipboard-health`, `moonlight-health`, `wallpaper-rotate`: same bug, waiting for
  his word (`wallpaper-rotate` would visibly start changing the wallpaper).
- `/mnt/rpi5/DS9` (cifs) still hangs when away. The mount fix waits for his call
  (local-bootstrapping `docs/issues/mpv-history-panel-empty-cifs-hang.md`).
- Pages that do not extend `base.html` (control, memory, memory events) do not
  show the activity bar yet.
