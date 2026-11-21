"""Contributor helper: claim a 5 x 5 block of detail squares, render it, paint it with Codex, pack it.

  python pipeline/contrib.py open                  # unpainted blocks open to contributors, nearest first
  python pipeline/contrib.py show b2_-3            # what is in a block and what is left to do
  python pipeline/contrib.py prepare b2_-3         # style reference + painted neighbours, render, QA, masks
  python pipeline/contrib.py paint b2_-3           # paint the block's open squares with Codex
  python pipeline/contrib.py pack b2_-3 --github yourname   # zip(s) to attach to your claim issue

Squares the maintainer's own run paints (data/frames_by_area.json "reserved") and squares already on
the live site are never rendered, painted or packed here.
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

from PIL import Image

from geo import ROOT, frame_name, parse_name

SITE = os.environ.get("SLC_MINIWORLD_SITE", "https://slc-miniworld.pages.dev").rstrip("/")
B = 5
LEVEL = "detail"
PAINTED = ROOT / "painted" / LEVEL
RENDERS = ROOT / "renders" / LEVEL
ZIP_LIMIT = 24 * 1024 * 1024  # GitHub issue attachments top out at 25 MB


def block_of(name):
    r, c = parse_name(name)
    return f"b{r // B}_{c // B}"


def block_range(block):
    br, bc = (int(v) for v in block[1:].split("_"))
    return range(br * B, br * B + B), range(bc * B, bc * B + B)


def shots():
    return [s["name"] for s in json.loads((ROOT / "cam" / f"slc_{LEVEL}_shots.json").read_text())["shots"]]


def areas():
    return json.loads((ROOT / "data" / "frames_by_area.json").read_text(encoding="utf-8"))


def fetch(path):
    req = urllib.request.Request(f"{SITE}/{path}", headers={"User-Agent": "slc-miniworld-contrib"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def live_painted():
    try:
        return set(json.loads(fetch("painted.json")).get(LEVEL, []))
    except Exception as e:  # noqa: BLE001 - offline still lets you work; pack re-checks later
        print(f"warning: could not read {SITE}/painted.json ({e}); treating nothing as painted")
        return set()


def block_frames(block, all_names):
    rows, cols = block_range(block)
    return [n for n in all_names if parse_name(n)[0] in rows and parse_name(n)[1] in cols]


def todo(block, all_names, reserved, live):
    return [n for n in block_frames(block, all_names) if n not in reserved and n not in live]


def run(cmd):
    print("$ " + " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT).returncode


def cmd_open(a):
    names, ar, live = shots(), areas(), live_painted()
    reserved, slc = set(ar["reserved"]), set(ar["Salt Lake City"])
    blocks = {}
    for n in slc - reserved - live:
        blocks.setdefault(block_of(n), []).append(n)
    def dist(b):
        br, bc = (int(v) for v in b[1:].split("_"))
        return (br * B + 2) ** 2 + (bc * B + 2) ** 2
    print(f"{len(blocks)} blocks with open Salt Lake City squares (nearest the temple first):")
    for b in sorted(blocks, key=dist)[: a.limit]:
        print(f"  {b:10s} {len(todo(b, names, reserved, live)):2d} squares to paint")


def cmd_show(a):
    names, ar, live = shots(), areas(), live_painted()
    reserved = set(ar["reserved"])
    fr = block_frames(a.block, names)
    left = todo(a.block, names, reserved, live)
    rendered = [n for n in left if (RENDERS / f"{n}.jpg").exists()]
    painted = [n for n in left if (PAINTED / f"{n}.png").exists()]
    print(f"{a.block}: {len(fr)} squares in the grid, {sum(n in live for n in fr)} on the live site, "
          f"{sum(n in reserved for n in fr)} reserved, {len(left)} for you "
          f"({len(rendered)} rendered, {len(painted)} painted here)")
    if left:
        print("  " + ",".join(left))


def cmd_prepare(a):
    names, ar, live = shots(), areas(), live_painted()
    reserved = set(ar["reserved"])
    left = todo(a.block, names, reserved, live)
    if not left:
        sys.exit(f"{a.block} has nothing left to paint")
    ref = ROOT / "style" / "ref.png"
    if not ref.exists():
        ref.parent.mkdir(exist_ok=True)
        ref.write_bytes(fetch("style/ref.png"))
        print("downloaded style/ref.png")
    rows, cols = block_range(a.block)
    ring = {frame_name(r, c) for r in range(rows.start - 1, rows.stop + 1) for c in range(cols.start - 1, cols.stop + 1)}
    PAINTED.mkdir(parents=True, exist_ok=True)
    got = 0
    for n in sorted(ring & live):
        p = PAINTED / f"{n}.png"
        if not p.exists():
            p.write_bytes(fetch(f"painted/{LEVEL}/{n}.png"))
            got += 1
    print(f"{got} painted neighbours downloaded for seam context")
    need = [n for n in left if not (RENDERS / f"{n}.jpg").exists()]
    for i in range(0, len(need), 40):
        run(["node", "render3d/server.mjs", "--mode", "render", "--level", LEVEL,
             "--only", ",".join(need[i:i + 40]), "--timeout", "150000"])
    run([sys.executable, "pipeline/prep_renders.py", "--level", LEVEL])
    qa = json.loads((RENDERS / "qa.json").read_text()) if (RENDERS / "qa.json").exists() else {}
    bad = [n for n in left if "black_or_missing" in qa.get(n, {}).get("flags", [])]
    missing = [n for n in left if not (RENDERS / f"{n}.jpg").exists()]
    if bad:
        print("re-rendering squares with missing geometry: " + ",".join(bad))
        run(["node", "render3d/server.mjs", "--mode", "render", "--level", LEVEL, "--only", ",".join(bad),
             "--timeout", "150000", "--redo"])
        run([sys.executable, "pipeline/prep_renders.py", "--level", LEVEL])
    run([sys.executable, "pipeline/water.py", "masks", "--level", LEVEL])
    print(f"ready: {len(left) - len(missing)} of {len(left)} squares rendered"
          + (f"; still missing {','.join(missing)} (run prepare again)" if missing else ""))


def cmd_paint(a):
    names, ar, live = shots(), areas(), live_painted()
    left = [n for n in todo(a.block, names, set(ar["reserved"]), live) if not (PAINTED / f"{n}.png").exists()]
    if not left:
        sys.exit(f"{a.block}: nothing left to paint here; run pack")
    sys.exit(run([sys.executable, "pipeline/paint.py", "--level", LEVEL, "--only", ",".join(left),
                  "--workers", str(a.workers)]))


def last_log():
    out = {}
    f = PAINTED / "log.jsonl"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if "error" not in e and e.get("name"):
                out[e["name"]] = {k: e.get(k) for k in ("mode", "attempt", "scale", "dx", "dy", "peak", "context_mad")}
    return out


def cmd_pack(a):
    names, ar, live = shots(), areas(), live_painted()
    left = todo(a.block, names, set(ar["reserved"]), live)
    done = [n for n in left if (PAINTED / f"{n}.png").exists()]
    if not done:
        sys.exit(f"{a.block}: no painted squares to pack")
    if len(done) < len(left):
        print(f"note: {len(left) - len(done)} squares are not painted yet: "
              + ",".join(n for n in left if n not in done))
    log = last_log()
    out_dir = ROOT / "submissions"
    out_dir.mkdir(exist_ok=True)
    parts, cur, size = [], [], 0
    for n in done:
        buf = io.BytesIO()
        Image.open(PAINTED / f"{n}.png").convert("RGB").save(buf, "JPEG", quality=92)
        if cur and size + buf.tell() > ZIP_LIMIT:
            parts.append(cur)
            cur, size = [], 0
        cur.append((n, buf.getvalue()))
        size += buf.tell()
    parts.append(cur)
    for i, part in enumerate(parts, 1):
        suffix = f"-part{i}" if len(parts) > 1 else ""
        path = out_dir / f"{a.block}{suffix}.zip"
        manifest = {"block": a.block, "github": a.github, "painter": "codex", "part": i, "parts": len(parts),
                    "squares": {n: log.get(n, {}) for n, _ in part}}
        with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
            z.writestr("manifest.json", json.dumps(manifest, indent=1))
            for n, data in part:
                z.writestr(f"{n}.jpg", data)
        print(f"wrote {path.relative_to(ROOT)} ({len(part)} squares, {path.stat().st_size / 2**20:.1f} MB)")
    print("Attach the zip file(s) to your claim issue on GitHub.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("open")
    p.add_argument("--limit", type=int, default=25)
    for name in ("show", "prepare", "paint", "pack"):
        p = sub.add_parser(name)
        p.add_argument("block", help="block id such as b2_-3")
        if name == "paint":
            p.add_argument("--workers", type=int, default=3)
        if name == "pack":
            p.add_argument("--github", required=True, help="your GitHub username, for the credits")
    a = ap.parse_args()
    if getattr(a, "block", None) and not re.fullmatch(r"b-?\d+_-?\d+", a.block):
        sys.exit("block ids look like b2_-3")
    {"open": cmd_open, "show": cmd_show, "prepare": cmd_prepare, "paint": cmd_paint, "pack": cmd_pack}[a.cmd](a)


if __name__ == "__main__":
    main()
