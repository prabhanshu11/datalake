"""Runs ON the Pi 5 NAS: print one Google Photos takeout item to stdout.

The datalake web app (web/app.py, /api/photos/full/<id>) pipes this file into
`ssh pi5 python3 - <json-args>`, so nothing has to be installed on the Pi and
the code stays in this repo. `pi5` picks his channel (LAN -> VPS relay ->
Tailscale) by itself: local-bootstrapping dotfiles/ssh/home-routes.conf.

Where the photo is looked for, in order (local-bootstrapping
dotfiles/network/nas.json "photos"):
  1. the extracted copy: <extracted_root>/<zip member path>
  2. the zip itself, in each of archive_dirs

args (one JSON object): {"member": str, "archive": str, "fit": int|0,
                         "extracted_root": str, "archive_dirs": [str],
                         "source": str}
fit > 0 -> a JPEG whose long edge is at most `fit` px (EXIF orientation applied,
provenance in EXIF per ~/Programs/CLAUDE.md); fit == 0 -> the original bytes.
Exit 0 with stdout = one line "NASPHOTO {read_from, size, fitted}" + the bytes;
exit 3 with a one-line reason on stderr.
"""
import io
import json
import os
import sys
import zipfile
from datetime import datetime, timezone


def fail(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(3)


def read_original(a):
    member = a["member"]
    if ".." in member.split("/"):
        fail("bad member path")
    ext = os.path.join(a["extracted_root"], member)
    if os.path.isfile(ext):
        with open(ext, "rb") as f:
            return f.read(), "extracted"
    for d in a["archive_dirs"]:
        z = os.path.join(d, a["archive"])
        if not os.path.isfile(z):
            continue
        try:
            with zipfile.ZipFile(z) as zf:
                return zf.read(member), "zip:" + d
        except KeyError:
            continue
        except zipfile.BadZipFile:
            continue
    fail("not found on the NAS: %s in %s (looked in the extracted copy and %d archive dirs)"
         % (member, a["archive"], len(a["archive_dirs"])))


def fitted(data, a, where):
    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(data))
    im = ImageOps.exif_transpose(im)
    im.thumbnail((a["fit"], a["fit"]))
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    exif = Image.Exif()
    prov = json.dumps({
        "source": a.get("source") or a["member"],
        "archive": a["archive"],
        "read_from": where,
        "pipeline": "datalake/web/nas_photo.py fit=%d" % a["fit"],
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    exif[0x010E] = prov  # ImageDescription
    out = io.BytesIO()
    im.save(out, "JPEG", quality=84, exif=exif.tobytes())
    return out.getvalue()


def main():
    a = json.loads(sys.argv[1])
    data, where = read_original(a)
    fit_done = False
    if a.get("fit"):
        try:
            data = fitted(data, a, where)
            fit_done = True
        except Exception as e:  # HEIC/RAW Pillow cannot open: send the original
            sys.stderr.write("fit skipped (%s), sending original\n" % e.__class__.__name__)
    # One header line first, so the laptop knows the size (live progress + speed in
    # the UI) and where the bytes came from, then the bytes.
    head = {"read_from": where, "size": len(data), "fitted": fit_done}
    sys.stdout.buffer.write(("NASPHOTO " + json.dumps(head) + "\n").encode())
    sys.stdout.buffer.write(data)


if __name__ == "__main__":
    main()
