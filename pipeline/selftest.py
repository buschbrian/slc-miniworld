"""Camera self-test (no Google key needed): render cubes at known ENU points in the browser and
check that each cube's centroid lands where geo.py says it should.

  python pipeline/selftest.py prepare && node render3d/server.mjs --mode selftest && python pipeline/selftest.py check
"""
import json
import sys

import numpy as np
from PIL import Image

from geo import ROOT, frame_origin, frame_target_enu, global_px, load_cam

LEVEL, R, C = "detail", 1, 2
POINTS = [[0, 0, 0], [60, 0, 0], [0, 60, 0], [0, 0, 60], [-50, -40, 20]]
COLORS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255)]
OUT = ROOT / "renders" / "selftest"


def prepare():
    cam = load_cam()
    tgt = frame_target_enu(cam, LEVEL, R, C)
    pts = [list(np.array(p, float) + tgt) for p in POINTS]
    OUT.mkdir(parents=True, exist_ok=True)
    job = {"shots": [{"name": "selftest", "target_enu": list(tgt)}],
           "points": [{"enu": p} for p in pts], "ppm": cam["levels"][LEVEL]["ppm"]}
    (OUT / "job.json").write_text(json.dumps(job))


def check():
    cam = load_cam()
    job = json.loads((OUT / "job.json").read_text())
    img = np.asarray(Image.open(OUT / "selftest.png").convert("RGB")).astype(int)
    hgt = np.asarray(Image.open(OUT / "h" / "selftest.png").convert("RGB")).astype(int)
    scale = cam["render_px"] / cam["frame_px"]
    ox, oy = frame_origin(cam, R, C)
    worst = 0.0
    for p, col in zip(job["points"], COLORS):
        mask = (np.abs(img - col).sum(-1) < 40)
        ys, xs = np.nonzero(mask)
        got = np.array([xs.mean(), ys.mean()]) / scale if len(xs) else None
        X, Y = global_px(cam, LEVEL, np.array(p["enu"]))
        want = np.array([X - ox, Y - oy])
        err = np.linalg.norm(got - want) if got is not None else float("inf")
        worst = max(worst, err)
        print(f"{col}: want {want.round(1)} got {None if got is None else got.round(1)} err {err:.2f}px")
    v = hgt[..., 0] * 256 + hgt[..., 1]  # 4 cm steps from -300 m
    top = v[hgt[..., 2] == 255]
    print("height range (m rel h0):", (top.min() * 0.04 - 300, top.max() * 0.04 - 300) if top.size else None)
    print("PASS" if worst < 2.0 else "FAIL")


if __name__ == "__main__":
    {"prepare": prepare, "check": check}[sys.argv[1]]()
