"""Stitch frames into a Leaflet tile pyramid in global camera pixels, plus an overview image.

  python pipeline/stitch.py --level detail [--source painted|renders]

1. Colour offsets: one additive RGB offset per frame from least squares over neighbour overlaps;
   frames >= 60% water are pinned to zero so large water stays one colour.
2. Native tiles (256 px) at the level's zoom: weighted blend of every frame covering the tile,
   with linear ramps across the 256 px overlap (weights sum to 1).
3. Lower zooms by 2x2 box reduction; stitched/<level>_<source>.jpg is the largest level <= 8192 px.
4. viewer/config.json gets this level's zoom range and bounds; places get pixel positions.
Global pixel (X, Y) at the level's native zoom Z is Leaflet CRS.Simple point (X, Y) at zoom Z.
"""
import argparse
import json
import math
from functools import lru_cache

import numpy as np
from PIL import Image

from geo import ROOT, latlon_px, load_cam, parse_name
from prep_renders import load_height

TILE = 256
BG = (24, 26, 31)


def sources(level, source, tag=None):
    if source == "renders":
        return {p.stem: p for p in sorted((ROOT / "renders" / level).glob("r*_c*.jpg"))}
    base = (ROOT / "painted" / "bakeoff" / tag if tag else ROOT / "painted") / level
    out = {p.stem: p for p in sorted(base.glob("r*_c*.png"))}
    out.update({p.stem: p for p in sorted((base / "fixed").glob("r*_c*.png"))})
    return out


def solve_offsets(files, size, step, water, lam=0.1):
    names = sorted(files)
    idx = {n: i for i, n in enumerate(names)}
    ov = size - step
    rows, rhs = [], []
    load = lambda n: np.asarray(Image.open(files[n]).convert("RGB"), np.float32)
    for n in names:
        r, c = parse_name(n)
        a = None
        for (dr, dc) in ((0, 1), (1, 0)):
            m = f"r{r + dr}_c{c + dc}"
            if m not in idx:
                continue
            a = load(n) if a is None else a
            b = load(m)
            pa = a[:, step:] if dc else a[step:, :]
            pb = b[:, :ov] if dc else b[:ov, :]
            row = np.zeros(len(names))
            row[idx[n]], row[idx[m]] = 1, -1
            rows.append(row)
            rhs.append(np.median(pb - pa, axis=(0, 1)))
    if not rows:
        return {n: np.zeros(3) for n in names}
    for n in names:
        row = np.zeros(len(names))
        w = 100.0 if water.get(n, 0) >= 0.6 else lam
        row[idx[n]] = w
        rows.append(row)
        rhs.append(np.zeros(3))
    sol, *_ = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)
    return {n: np.clip(sol[idx[n]], -30, 30) for n in names}


def ramp(size, ov):
    t = np.arange(size) + 0.5
    return np.clip(np.minimum(t, size - t) / ov, 1e-3, 1.0).astype(np.float32)


def build_native(cam, level, files, offsets, out_dir, Z):
    size, step = cam["frame_px"], cam["step_px"]
    half = size // 2
    w1 = ramp(size, size - step)
    frames = {parse_name(n): n for n in files}

    @lru_cache(maxsize=160)
    def frame(rc):
        a = np.asarray(Image.open(files[frames[rc]]).convert("RGB"), np.float32) + offsets[frames[rc]]
        return np.clip(a, 0, 255).astype(np.uint8)

    tiles = set()
    for (r, c) in frames:
        x0, y0 = c * step - half, r * step - half
        for ty in range(math.floor(y0 / TILE), math.floor((y0 + size - 1) / TILE) + 1):
            for tx in range(math.floor(x0 / TILE), math.floor((x0 + size - 1) / TILE) + 1):
                tiles.add((tx, ty))
    for tx, ty in sorted(tiles, key=lambda t: (t[1], t[0])):
        X0, Y0 = tx * TILE, ty * TILE
        acc = np.zeros((TILE, TILE, 3), np.float32)
        wsum = np.zeros((TILE, TILE), np.float32)
        for r in range(math.ceil((Y0 - half + 1) / step), math.floor((Y0 + TILE - 1 + half) / step) + 1):
            for c in range(math.ceil((X0 - half + 1) / step), math.floor((X0 + TILE - 1 + half) / step) + 1):
                if (r, c) not in frames:
                    continue
                fx0, fy0 = X0 - (c * step - half), Y0 - (r * step - half)
                xs, ys = slice(max(fx0, 0), min(fx0 + TILE, size)), slice(max(fy0, 0), min(fy0 + TILE, size))
                if xs.start >= xs.stop or ys.start >= ys.stop:
                    continue
                tx_s = slice(xs.start - fx0, xs.stop - fx0)
                ty_s = slice(ys.start - fy0, ys.stop - fy0)
                w = np.outer(w1[ys], w1[xs])
                acc[ty_s, tx_s] += frame((r, c))[ys, xs] * w[..., None]
                wsum[ty_s, tx_s] += w
        img = np.where(wsum[..., None] > 0, acc / np.maximum(wsum, 1e-6)[..., None], BG)
        p = out_dir / str(Z) / str(tx)
        p.mkdir(parents=True, exist_ok=True)
        Image.fromarray(img.round().astype(np.uint8)).save(p / f"{ty}.jpg", quality=86)
    return tiles


def build_lower(out_dir, Z, tiles, zmin):
    levels = {Z: tiles}
    for z in range(Z - 1, zmin - 1, -1):
        parents = {(tx // 2, ty // 2) for tx, ty in levels[z + 1]}
        for px, py in parents:
            canvas = Image.new("RGB", (2 * TILE, 2 * TILE), BG)
            for dx in (0, 1):
                for dy in (0, 1):
                    f = out_dir / str(z + 1) / str(2 * px + dx) / f"{2 * py + dy}.jpg"
                    if f.exists():
                        canvas.paste(Image.open(f), (dx * TILE, dy * TILE))
            p = out_dir / str(z) / str(px)
            p.mkdir(parents=True, exist_ok=True)
            canvas.reduce(2).save(p / f"{py}.jpg", quality=86)
        levels[z] = parents
    return levels


def composite(out_dir, levels, max_px=8192):
    for z in sorted(levels, reverse=True):
        t = levels[z]
        xs, ys = [a for a, _ in t], [b for _, b in t]
        W, H = (max(xs) - min(xs) + 1) * TILE, (max(ys) - min(ys) + 1) * TILE
        if max(W, H) <= max_px:
            canvas = Image.new("RGB", (W, H), BG)
            for tx, ty in t:
                canvas.paste(Image.open(out_dir / str(z) / str(tx) / f"{ty}.jpg"),
                             ((tx - min(xs)) * TILE, (ty - min(ys)) * TILE))
            return canvas, z


def place_px(cam, level, place):
    """Iterate height lookups so a landmark on a hill lands on the hill, not the ground plane."""
    h = 0.0
    if cam["probe"]:
        hit = next((p for p in cam["probe"]["points"] if p["name"] == place["name"]), None)
        anchor = next((p for p in cam["probe"]["points"] if p["name"] == "anchor"), None)
        if hit and hit.get("h_p50") is not None and anchor:
            h = hit["h_p50"] - anchor["h_p5"]
    size, step = cam["frame_px"], cam["step_px"]
    for _ in range(4):
        X, Y = latlon_px(cam, level, place["lat"], place["lon"], h)
        r, c = round(Y / step), round(X / step)
        hp = ROOT / "heights" / level / f"r{r}_c{c}.png"
        if not hp.exists():
            break
        hm = load_height(level, f"r{r}_c{c}")
        fx, fy = int(X - (c * step - size // 2)), int(Y - (r * step - size // 2))
        win = hm[max(fy - 3, 0):fy + 4, max(fx - 3, 0):fx + 4]
        if not np.isfinite(win).any():
            break
        h = float(np.nanmedian(win))
    X, Y = latlon_px(cam, level, place["lat"], place["lon"], h)
    return float(X), float(Y)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="slc")
    ap.add_argument("--level", default="detail")
    ap.add_argument("--source", default="painted", choices=["painted", "renders"])
    ap.add_argument("--tag", help="stitch painted/bakeoff/<tag>/ instead of painted/")
    a = ap.parse_args()
    cam = load_cam(a.city)
    Z = cam["levels"][a.level]["zoom"]
    files = sources(a.level, a.source, a.tag)
    if not files:
        raise SystemExit(f"no {a.source} frames for {a.level}")
    wpath = ROOT / "masks" / a.level / "water.json"
    water = json.loads(wpath.read_text()) if wpath.exists() else {}
    offsets = solve_offsets(files, cam["frame_px"], cam["step_px"], water)
    tag = f"{a.level}_render" if a.source == "renders" else (f"{a.level}-{a.tag}" if a.tag else a.level)
    out_dir = ROOT / "tiles" / tag
    tiles = build_native(cam, a.level, files, offsets, out_dir, Z)
    levels = build_lower(out_dir, Z, tiles, max(0, Z - 8))
    img, zc = composite(out_dir, levels)
    (ROOT / "stitched").mkdir(exist_ok=True)
    img.save(ROOT / "stitched" / f"{tag}.jpg", quality=90)

    xs = [tx for tx, _ in tiles]
    ys = [ty for _, ty in tiles]
    cfg_path = ROOT / "viewer" / "config.json"
    cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {"layers": {}}
    cfg["layers"][tag] = {"path": f"../tiles/{tag}/{{z}}/{{x}}/{{y}}.jpg", "native_zoom": Z,
                          "min_zoom": min(levels), "level": a.level, "frames": len(files),
                          "bounds_px": [min(xs) * TILE, min(ys) * TILE, (max(xs) + 1) * TILE, (max(ys) + 1) * TILE]}
    places = json.loads((ROOT / "data" / "places.json").read_text())
    dz = cam["levels"]["detail"]["zoom"]
    for p in places:
        X, Y = place_px(cam, "detail", p)  # markers live in detail-zoom pixels
        p["px"] = [round(X, 1), round(Y, 1), dz]
    cfg["places"] = places
    cfg["attribution"] = ("3D source: Google (" + "; ".join(cam["probe"]["attributions"]) + ")"
                          if cam["probe"] else "3D source: Google") + " · Water © OpenStreetMap contributors · Painted with Codex"
    cfg_path.write_text(json.dumps(cfg, indent=1))
    off = np.array(list(offsets.values()))
    print(f"{tag}: {len(files)} frames -> {len(tiles)} native tiles at z{Z}; composite z{zc} {img.size}; "
          f"offset |max| {np.abs(off).max():.1f}")


if __name__ == "__main__":
    main()
