"""Maintainer intake for a contributor's zip. Treat every zip as untrusted.

  python -I pipeline/intake.py path/to/b2_-3.zip            # check, stage, write a review sheet
  python -I pipeline/intake.py path/to/b2_-3.zip --apply    # after review: copy staged squares into painted/

Nothing is extracted to disk as-is: members are read in memory, only manifest.json and r<row>_c<col>.jpg
names from the shot list are accepted, and every image is decoded and re-encoded by Pillow. Each square
is registered against this machine's own render, so a square that is shifted, rescaled or not the right
place is rejected. Existing painted squares are never overwritten.
"""
import argparse
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from PIL import Image  # noqa: E402

from geo import ROOT  # noqa: E402
from paint import register  # noqa: E402

Image.MAX_IMAGE_PIXELS = 4_000_000
LEVEL = "detail"
NAME = re.compile(r"r-?\d{1,3}_c-?\d{1,3}\.jpg")
MAX_MEMBER = 8 * 1024 * 1024
MAX_MEMBERS = 80


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("zip", type=Path)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    shots = {s["name"] for s in json.loads((ROOT / "cam" / f"slc_{LEVEL}_shots.json").read_text())["shots"]}
    reserved = set(json.loads((ROOT / "data" / "frames_by_area.json").read_text(encoding="utf-8"))["reserved"])
    painted = ROOT / "painted" / LEVEL
    stage = ROOT / "painted" / "intake" / a.zip.stem
    if a.apply:
        return apply(stage, painted)
    with zipfile.ZipFile(a.zip) as z:
        infos = z.infolist()
        if len(infos) > MAX_MEMBERS:
            sys.exit(f"too many members ({len(infos)})")
        bad = [i.filename for i in infos if i.filename != "manifest.json" and not NAME.fullmatch(i.filename)]
        big = [i.filename for i in infos if i.file_size > MAX_MEMBER]
        if bad or big:
            sys.exit(f"rejected: unexpected members {bad[:5]} oversized {big[:5]}")
        manifest = json.loads(z.read("manifest.json")) if "manifest.json" in z.namelist() else {}
        print(f"manifest: block {manifest.get('block')}, github {manifest.get('github')}, "
              f"part {manifest.get('part')}/{manifest.get('parts')}")
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir(parents=True)
        ok, rows, need_render = [], [], []
        for i in infos:
            if i.filename == "manifest.json":
                continue
            n = i.filename[:-4]
            why = None
            if n not in shots:
                why = "not in the shot list"
            elif n in reserved:
                why = "reserved for the maintainer's run"
            elif (painted / f"{n}.png").exists():
                why = "already painted"
            elif not (ROOT / "renders" / LEVEL / f"{n}.jpg").exists():
                need_render.append(n)
                why = "no local render to check against"
            if why:
                print(f"  skip {n}: {why}")
                continue
            with z.open(i) as f:
                img = Image.open(f)
                img.load()
            if img.size != (1024, 1024):
                print(f"  skip {n}: size {img.size}")
                continue
            img = img.convert("RGB")
            render = Image.open(ROOT / "renders" / LEVEL / f"{n}.jpg").convert("RGB")
            s, dx, dy, peak = register(img, render)
            fine = peak >= 6 and abs(dx) <= 4 and abs(dy) <= 4 and abs(s - 1) <= 0.02
            print(f"  {'ok  ' if fine else 'FAIL'} {n}: scale {s:.2f} shift ({dx:+.0f}, {dy:+.0f}) peak {peak:.1f}")
            if fine:
                img.save(stage / f"{n}.png")
                ok.append(n)
                rows.append((render, img))
    if need_render:
        print("render these first, then run intake again:\n  node render3d/server.mjs --mode render --level detail "
              f"--only {','.join(need_render)}\n  python pipeline/prep_renders.py --level detail")
    if rows:
        cell = 256
        sheet = Image.new("RGB", (cell * 2 * min(4, len(rows)), cell * ((len(rows) + 3) // 4)), (24, 26, 31))
        for k, (r, p) in enumerate(rows):
            x, y = (k % 4) * cell * 2, (k // 4) * cell
            sheet.paste(r.resize((cell, cell)), (x, y))
            sheet.paste(p.resize((cell, cell)), (x + cell, y))
        out = ROOT / "stitched" / f"intake_{a.zip.stem}.jpg"
        out.parent.mkdir(exist_ok=True)
        sheet.save(out, quality=88)
        print(f"review sheet (render | painting): {out.relative_to(ROOT)}")
    (stage / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"{len(ok)} squares staged in {stage.relative_to(ROOT)}; re-run with --apply after review")


def apply(stage, painted):
    if not stage.exists():
        sys.exit(f"nothing staged at {stage}")
    painted.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((stage / "manifest.json").read_text(encoding="utf-8"))
    added = []
    for p in sorted(stage.glob("r*_c*.png")):
        dest = painted / p.name
        if dest.exists():
            print(f"  keep existing {p.name}")
            continue
        shutil.copy2(p, dest)
        added.append(p.stem)
    with (ROOT / "painted" / "intake" / "applied.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"block": manifest.get("block"), "github": manifest.get("github"), "squares": added}) + "\n")
    print(f"{len(added)} squares added to {painted.relative_to(ROOT)}; run water fix + stitch, then deploy")


if __name__ == "__main__":
    main()
