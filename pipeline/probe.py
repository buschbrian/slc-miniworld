"""Coverage probe for Google Photorealistic 3D Tiles.

  python pipeline/probe.py prepare      # writes cam/<city>_probe_points.json
  node render3d/server.mjs --mode probe # top-down 300 m render + raycast at each point
  python pipeline/probe.py finish       # freezes h0 into cam/<city>_probe.json and prints a report

h0 (ground ellipsoidal height at the anchor) is the 5th-percentile surface height in the anchor
patch, so the temple spire does not lift the ground plane. Once frozen, it never changes.
"""
import argparse
import json
import re

import numpy as np
from PIL import Image

from geo import ROOT, enu, load_cam

WIDTH_M = 300.0


def decode_height(path):
    a = np.asarray(Image.open(path).convert("RGB")).astype(np.int64)
    v = (a[..., 0] * 256 + a[..., 1]) * 0.04 - 300.0
    return np.where(a[..., 2] == 255, v, np.nan)


def prepare(city):
    cam = load_cam(city)
    places = json.loads((ROOT / "data" / "places.json").read_text())
    pts = [{"name": "anchor", "lat": cam["anchor"]["lat"], "lon": cam["anchor"]["lon"]}]
    pts += [{"name": p["name"], "lat": p["lat"], "lon": p["lon"]} for p in places]
    for lvl, d in cam["levels"].items():
        a = d["aoi"]
        for tag, la, lo in [("NW", a["north"], a["west"]), ("NE", a["north"], a["east"]),
                            ("SW", a["south"], a["west"]), ("SE", a["south"], a["east"])]:
            pts.append({"name": f"{lvl} corner {tag}", "lat": la, "lon": lo})
    for p in pts:
        p["enu"] = [round(float(v), 3) for v in enu(cam, p["lat"], p["lon"], cam["h0"])]
        p["width_m"] = WIDTH_M
    (ROOT / "cam" / f"{city}_probe_points.json").write_text(json.dumps(pts, indent=1))
    print(f"{len(pts)} probe points; h0 guess {cam['h0']}")


def finish(city, force):
    cam = load_cam(city)
    out = ROOT / "cam" / f"{city}_probe.json"
    if out.exists() and not force:
        raise SystemExit(f"{out.name} is frozen; pass --force only before any painting has started")
    pdir = ROOT / "renders" / "probe"
    res = json.loads((pdir / "result.json").read_text())
    rows = []
    for r in res:
        hp = pdir / (re.sub(r"[^A-Za-z0-9_.-]", "_", r["name"]) + "_h.png")
        h = decode_height(hp) if hp.exists() else None
        cov = float(np.isfinite(h).mean()) if h is not None else 0.0
        p5, p50, p95 = (np.nanpercentile(h, [5, 50, 95]).round(1).tolist() if cov > 0 else [None] * 3)
        relief = None if p5 is None else round(p95 - p5, 1)
        status = "no" if cov < 0.5 or not r["loaded"] else ("yes" if relief and relief > 8 else "partial")
        rows.append({**r, "coverage": round(cov, 3), "h_p5": p5, "h_p50": p50, "h_p95": p95,
                     "relief_m": relief, "status": status})
    anchor = next(r for r in rows if r["name"] == "anchor")
    if anchor["h_p5"] is None:
        raise SystemExit("anchor probe has no geometry; check the API key and Map Tiles API enablement")
    h0 = round(cam["ground_h_guess"] + anchor["h_p5"], 2)
    attributions = sorted({a for r in rows for a in r.get("attributions", [])})
    out.write_text(json.dumps({"h0": h0, "h0_method": "anchor patch 5th percentile",
                               "attributions": attributions, "points": rows}, indent=1))
    print(f"h0 = {h0} m (ellipsoidal)\n")
    print(f"{'point':38s} status  cover  relief_m  p50_rel")
    for r in rows:
        print(f"{r['name']:38s} {r['status']:7s} {r['coverage']:5.2f}  {str(r['relief_m']):8s}  {r['h_p50']}")
    print("\nattribution:", "; ".join(attributions))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["prepare", "finish"])
    ap.add_argument("--city", default="slc")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    prepare(a.city) if a.step == "prepare" else finish(a.city, a.force)
