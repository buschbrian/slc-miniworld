"""Water masks and the water/defect pass.

  python pipeline/water.py masks --level detail   # masks/<level>/<name>.png + water.json fractions
  python pipeline/water.py fix   --level detail   # painted/<level>/fixed/<name>.png

Masks: each pixel's height (from the height render) inverts the camera to a ground (e, n)
position, which is tested against OSM water rasterised in a local ENU grid. A pixel counts as
water only if it is also within 1.5 m of the frame's water surface (piers, boats and bridges stay)
and the render there is not bright (exposed salt/mud flats inside the lake polygon stay land).
Fix: masked pixels the painter turned into non-water are repainted with the frame's water colour.
"""
import argparse
import json
import math

import numpy as np
from PIL import Image, ImageDraw

from geo import ROOT, enu, frame_origin, load_cam, parse_name
from prep_renders import load_height

GRID_M = 0.5


def load_water_enu(cam):
    data = json.loads((ROOT / "data" / "osm_water.json").read_text())

    def conv(coords):
        a = np.array(coords, float)
        return enu(cam, a[:, 1], a[:, 0], cam["h0"])[:, :2]
    areas = [{"outer": conv(x["outer"]), "inners": [conv(i) for i in x["inners"]]} for x in data["areas"]]
    lines = [{"coords": conv(x["coords"]), "width_m": x["width_m"]} for x in data["lines"]]
    return areas, lines


def pixel_ground(cam, level, r, c, h):
    """Per-pixel ENU (e, n) by inverting the orthographic camera at the pixel's height."""
    ppm = cam["levels"][level]["ppm"]
    size = cam["frame_px"]
    ox, oy = frame_origin(cam, r, c)
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float64)
    sx, sy = (xx + 0.5 + ox) / ppm, -(yy + 0.5 + oy) / ppm
    H, E = math.radians(cam["heading_deg"]), math.radians(cam["elevation_deg"])
    b = (sy - h * math.cos(E)) / math.sin(E)
    return sx * math.cos(H) + b * math.sin(H), -sx * math.sin(H) + b * math.cos(H)


def osm_mask(e, n, areas, lines):
    e0, e1, n0, n1 = e.min() - 5, e.max() + 5, n.min() - 5, n.max() + 5
    W, Hh = int((e1 - e0) / GRID_M) + 1, int((n1 - n0) / GRID_M) + 1
    canvas = Image.new("L", (W, Hh), 0)
    d = ImageDraw.Draw(canvas)
    to_px = lambda p: [((x - e0) / GRID_M, (n1 - y) / GRID_M) for x, y in p]
    hit = lambda p: p[:, 0].max() >= e0 and p[:, 0].min() <= e1 and p[:, 1].max() >= n0 and p[:, 1].min() <= n1
    for a in areas:
        if hit(a["outer"]):
            d.polygon(to_px(a["outer"]), fill=255)
            for i in a["inners"]:
                if hit(i):
                    d.polygon(to_px(i), fill=0)
    for ln in lines:
        if hit(ln["coords"]):
            d.line(to_px(ln["coords"]), fill=255, width=max(1, int(ln["width_m"] / GRID_M)), joint="curve")
    grid = np.asarray(canvas) > 0
    ix = np.clip(((e - e0) / GRID_M).astype(int), 0, W - 1)
    iy = np.clip(((n1 - n) / GRID_M).astype(int), 0, Hh - 1)
    return grid[iy, ix]


def frame_mask(cam, level, name, areas, lines):
    r, c = parse_name(name)
    h = load_height(level, name)
    fill = np.nanmedian(h) if np.isfinite(h).any() else 0.0
    hf = np.where(np.isfinite(h), h, fill)
    e, n = pixel_ground(cam, level, r, c, hf)
    m = osm_mask(e, n, areas, lines)
    if m.sum() < 50:
        return np.zeros_like(m)
    level_h = np.nanpercentile(hf[m], 30)  # water surface: the low, flat majority inside the polygon
    render = np.asarray(Image.open(ROOT / "renders" / level / f"{name}.jpg").convert("RGB"), np.float32)
    bright = render.mean(-1) > 175
    return m & (hf <= level_h + 1.5) & ~bright


def cmd_masks(cam, level):
    areas, lines = load_water_enu(cam)
    out = ROOT / "masks" / level
    out.mkdir(parents=True, exist_ok=True)
    frac = {}
    for hp in sorted((ROOT / "heights" / level).glob("r*_c*.png")):
        name = hp.stem
        m = frame_mask(cam, level, name, areas, lines)
        Image.fromarray((m * 255).astype(np.uint8)).save(out / f"{name}.png")
        frac[name] = round(float(m.mean()), 4)
    (out / "water.json").write_text(json.dumps(frac, indent=1))
    wet = {k: v for k, v in frac.items() if v > 0.01}
    print(f"{len(frac)} masks; frames with water: {len(wet)}; >=60% water: {sum(v >= 0.6 for v in frac.values())}")


def looks_like_water(px, ref):
    p = px.astype(np.float32)
    close = np.abs(p - ref).sum(-1) < 70
    bluish = (p[..., 2] > p[..., 0] + 8) & (p[..., 2] >= p[..., 1] - 12) & (p.mean(-1) < 200)
    return close | bluish


def cmd_fix(cam, level):
    src = ROOT / "painted" / level
    out = src / "fixed"
    out.mkdir(parents=True, exist_ok=True)
    default = np.array(cam.get("water_rgb", [74, 128, 150]), np.float32)
    report = {}
    for pp in sorted(src.glob("r*_c*.png")):
        name = pp.stem
        mp = ROOT / "masks" / level / f"{name}.png"
        img = np.asarray(Image.open(pp).convert("RGB")).copy()
        if not mp.exists():
            Image.fromarray(img).save(out / f"{name}.png")
            continue
        m = np.asarray(Image.open(mp)) > 0
        if m.sum() < 200:
            Image.fromarray(img).save(out / f"{name}.png")
            continue
        wl = looks_like_water(img[m], default)
        ref = np.median(img[m][wl], axis=0) if wl.mean() > 0.2 else default
        bad = np.zeros_like(m)
        bad[m] = ~looks_like_water(img[m], ref)
        img[bad] = ref.astype(np.uint8)
        report[name] = {"water_px": int(m.sum()), "repainted_px": int(bad.sum())}
        Image.fromarray(img).save(out / f"{name}.png")
    (out / "report.json").write_text(json.dumps(report, indent=1))
    fixed = {k: v for k, v in report.items() if v["repainted_px"] > 0}
    print(f"water fix: {len(fixed)} frames changed; {sum(v['repainted_px'] for v in fixed.values())} px repainted")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["masks", "fix"])
    ap.add_argument("--level", default="detail")
    ap.add_argument("--city", default="slc")
    a = ap.parse_args()
    cam = load_cam(a.city)
    (cmd_masks if a.step == "masks" else cmd_fix)(cam, a.level)
