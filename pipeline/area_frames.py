"""Detail frames that show an area's ground, using real terrain heights.

  python pipeline/area_frames.py --name "Salt Lake County" --bounds data/county_bounds.geojson \
      --dem slco_dem.bin [--write]

The camera looks down at 30 degrees, so ground 2,000 m up the Wasatch lands about 8 rows higher on
screen than valley ground at the same latitude. Each sample point inside the boundary (about every
60 m) is projected at its DEM height (and 50 m above it, for buildings and trees), and every frame
whose core it lands in is kept. --dem is an ENVI float32 grid in EPSG:4326 with orthometric metres,
for example USGS 3DEP warped with: gdalwarp -t_srs EPSG:4326 -tr 0.002 0.002 -r bilinear -of ENVI.
--write stores the sorted list under the area's name in data/frames_by_area.json.
"""
import argparse
import json
import re
from pathlib import Path

import numpy as np

from geo import ROOT, latlon_px, load_cam

STEP_DEG = 0.0006
LIFT_M = 50.0


def read_envi(path):
    hdr = Path(path).with_suffix(".hdr").read_text()
    val = lambda k: re.search(rf"^{k}\s*=\s*(.+)$", hdr, re.M).group(1).strip()  # noqa: E731
    w, h = int(val("samples")), int(val("lines"))
    info = [s.strip() for s in val("map info").strip("{}").split(",")]
    x0, y0, dx, dy = float(info[3]), float(info[4]), float(info[5]), float(info[6])
    return np.fromfile(path, np.float32).reshape(h, w), x0, y0, dx, dy


def bilinear(grid, x0, y0, dx, dy, lon, lat):
    fx, fy = (lon - x0) / dx - 0.5, (y0 - lat) / dy - 0.5
    i, j = np.floor(fy).astype(int), np.floor(fx).astype(int)
    i, j = np.clip(i, 0, grid.shape[0] - 2), np.clip(j, 0, grid.shape[1] - 2)
    ty, tx = np.clip(fy - i, 0, 1), np.clip(fx - j, 0, 1)
    return (grid[i, j] * (1 - tx) * (1 - ty) + grid[i, j + 1] * tx * (1 - ty)
            + grid[i + 1, j] * (1 - tx) * ty + grid[i + 1, j + 1] * tx * ty)


def inside(lon, lat, rings):
    hit = np.zeros(lon.shape, bool)
    for ring in rings:
        x, y = np.asarray(ring)[:, 0], np.asarray(ring)[:, 1]
        for a, b, c, d in zip(x, y, np.roll(x, -1), np.roll(y, -1)):
            hit ^= ((b > lat) != (d > lat)) & (lon < (c - a) * (lat - b) / (d - b + 1e-15) + a)
    return hit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--bounds", required=True, type=Path)
    ap.add_argument("--dem", required=True)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    cam = load_cam("slc")
    step = cam["step_px"]
    dem, x0, y0, dx, dy = read_envi(a.dem)
    if (dem < -1000).any():
        raise SystemExit("DEM has nodata inside the area's bounding box")
    frames = set()
    for f in json.loads((ROOT / a.bounds).read_text())["features"]:
        g = f["geometry"]
        for rings in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]):
            pts = np.concatenate([np.asarray(r) for r in rings])
            (w, s), (e, n) = pts.min(0), pts.max(0)
            lon, lat = np.meshgrid(np.arange(w, e, STEP_DEG), np.arange(s, n, STEP_DEG))
            lon, lat = lon.ravel(), lat.ravel()
            keep = inside(lon, lat, rings)
            lon, lat = lon[keep], lat[keep]
            h_rel = bilinear(dem, x0, y0, dx, dy, lon, lat) + cam["geoid_offset_m"] - cam["h0"]
            print(f"{len(lon)} samples, ground {h_rel.min():.0f} to {h_rel.max():.0f} m relative to the anchor")
            for lift in (0.0, LIFT_M):
                X, Y = latlon_px(cam, "detail", lat, lon, h_rel + lift).T
                frames.update(zip(np.round(Y / step).astype(int).tolist(), np.round(X / step).astype(int).tolist()))
    names = sorted(f"r{r}_c{c}" for r, c in frames)
    rows, cols = [r for r, _ in frames], [c for _, c in frames]
    print(f"{a.name}: {len(names)} frames, rows {min(rows)}..{max(rows)}, cols {min(cols)}..{max(cols)}")
    if a.write:
        p = ROOT / "data" / "frames_by_area.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        data[a.name] = names
        p.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        print(f"wrote {a.name} to {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
