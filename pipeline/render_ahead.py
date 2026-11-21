"""Maintainer: render the nearest open blocks ahead of contributors, so they can paint without a Google key.

  python pipeline/render_ahead.py --blocks 20          # make sure the 20 nearest open blocks are rendered
  python pipeline/render_ahead.py --blocks 20 --dry-run

"Open" is the same rule contrib.py uses: Salt Lake County squares, minus the reserved run, minus
squares already painted here. Renders go through render3d (40 squares per Chrome launch, one Google
root request each) and prep_renders.py; squares flagged for missing geometry get one re-render.
deploy/build_site.py then lists the clean ones in renders.json and sync_tiles.ps1 shares them.
"""
import argparse
import json
import subprocess
import sys

from contrib import B, PAINTED, RENDERS, areas, block_of, paintable
from geo import ROOT

LEVEL = "detail"


def run(cmd):
    print("$ " + " ".join(cmd[:6]) + (" ..." if len(cmd) > 6 else ""), flush=True)
    return subprocess.run(cmd, cwd=ROOT).returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blocks", type=int, default=20)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    painted = {p.stem for p in PAINTED.glob("r*_c*.png")}
    blocks = {}
    for n in paintable(areas()) - painted:
        blocks.setdefault(block_of(n), []).append(n)

    def dist(b):
        br, bc = (int(v) for v in b[1:].split("_"))
        return (br * B + 2) ** 2 + (bc * B + 2) ** 2
    near = sorted(blocks, key=dist)[: a.blocks]
    qa_path = RENDERS / "qa.json"
    qa = json.loads(qa_path.read_text()) if qa_path.exists() else {}
    squares = [n for b in near for n in sorted(blocks[b])]
    need = [n for n in squares if not (RENDERS / f"{n}.jpg").exists()]
    unchecked = [n for n in squares if n not in need and n not in qa]  # early renders made before QA existed
    print(f"{len(near)} nearest open blocks ({near[0]} .. {near[-1]}): {len(need)} squares to render, "
          f"{len(unchecked)} to re-render for QA")
    if a.dry_run or not (need or unchecked):
        return
    for names, extra in ((need, []), (unchecked, ["--redo"])):
        for i in range(0, len(names), 40):
            run(["node", "render3d/server.mjs", "--mode", "render", "--level", LEVEL,
                 "--only", ",".join(names[i:i + 40]), "--timeout", "150000", *extra])
            run([sys.executable, "pipeline/prep_renders.py", "--level", LEVEL])
    need += unchecked
    qa = json.loads(qa_path.read_text())
    bad = [n for n in need if "black_or_missing" in qa.get(n, {}).get("flags", [])]
    if bad:
        print(f"re-rendering {len(bad)} with missing geometry")
        run(["node", "render3d/server.mjs", "--mode", "render", "--level", LEVEL, "--only", ",".join(bad),
             "--timeout", "150000", "--redo"])
        run([sys.executable, "pipeline/prep_renders.py", "--level", LEVEL])
    run([sys.executable, "pipeline/water.py", "masks", "--level", LEVEL])
    done = sum((RENDERS / f"{n}.jpg").exists() for n in need)
    print(f"rendered {done} of {len(need)}")


if __name__ == "__main__":
    main()
