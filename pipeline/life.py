"""Paths for the viewer's moving cars, people and trains: OSM roads, footpaths and light rail inside
the painted squares, projected through the frozen camera onto the ground.

Ground height comes from the public Terrarium DEM tiles (USGS 3DEP in the US), not from Google's
height renders, so this works for squares painted on other machines. Output: viewer/life.json.

  python pipeline/life.py            # painted squares from painted/detail/
  python pipeline/life.py --live     # painted squares from the live site's painted.json
"""
import argparse
import io
import json
import math
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from geo import ROOT, enu, global_px, load_cam, parse_name

UA = {"User-Agent": "slc-miniworld-life/1.0"}
CACHE = ROOT / "cache"
OUT = ROOT / "viewer" / "life.json"
LEVEL = "detail"
DEM_Z = 14
KINDS = ["motorway", "major", "minor", "service", "foot", "rail"]
ROAD = {"motorway": 0, "trunk": 0, "motorway_link": 1, "trunk_link": 1, "primary": 1, "primary_link": 1,
        "secondary": 1, "secondary_link": 1, "tertiary": 2, "tertiary_link": 2, "unclassified": 2,
        "residential": 2, "living_street": 2, "service": 3, "footway": 4, "path": 4, "pedestrian": 4,
        "steps": 4, "cycleway": 4, "track": 4}
OVERPASS = "https://overpass-api.de/api/interpreter"


def fetch(url, data=None, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers=UA)
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.read()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(5 * (i + 1))


def painted_names(live):
    if live:
        return json.loads(fetch("https://slc-miniworld.pages.dev/painted.json"))["detail"]
    return sorted(p.stem for p in (ROOT / "painted" / LEVEL).glob("r*_c*.png"))


def inverse_ground(cam, X, Y):
    """Global px at the anchor ground plane -> (lat, lon), for the OSM query box."""
    ppm = cam["levels"][LEVEL]["ppm"]
    m = np.array([[cam["right"][0], cam["right"][1]], [-cam["up"][0], -cam["up"][1]]]) * ppm
    e, n = np.linalg.solve(m, np.array([X, Y], float))
    lat0, lon0 = cam["anchor"]["lat"], cam["anchor"]["lon"]
    return lat0 + n / 111132.0, lon0 + e / (111320.0 * math.cos(math.radians(lat0)))


def osm_ways(bbox):
    s, w, n, e = bbox
    key = CACHE / f"osm_life_{s:.4f}_{w:.4f}_{n:.4f}_{e:.4f}.json"
    if key.exists():
        return json.loads(key.read_text())
    box = f"{s},{w},{n},{e}"
    q = (f'[out:json][timeout:170];(way["highway"~"^({"|".join(ROAD)})$"]({box});'
         f'way["railway"~"^(light_rail|tram)$"]({box}););out body geom;')
    data = json.loads(fetch(OVERPASS, urllib.parse.urlencode({"data": q}).encode()))
    CACHE.mkdir(exist_ok=True)
    key.write_text(json.dumps(data))
    return data


def osm_buildings(bbox):
    """Buildings tall enough to hide a street behind them in the 30-degree view."""
    s, w, n, e = bbox
    key = CACHE / f"osm_buildings_{s:.4f}_{w:.4f}_{n:.4f}_{e:.4f}.json"
    if key.exists():
        return json.loads(key.read_text())
    box = f"{s},{w},{n},{e}"
    big = "apartments|commercial|retail|office|university|college|hospital|hotel|civic|government|" \
          "school|church|cathedral|temple|stadium|industrial|warehouse|parking|dormitory|public"
    q = (f'[out:json][timeout:240];(way["building"]["height"]({box});way["building"]["building:levels"]({box});'
         f'way["building"~"^({big})$"]({box}););out tags geom;')
    data = json.loads(fetch(OVERPASS, urllib.parse.urlencode({"data": q}).encode()))
    key.write_text(json.dumps(data))
    return data


def building_height(t):
    for k in ("height", "building:height"):
        try:
            return float(t[k].split()[0].replace("m", ""))
        except (KeyError, ValueError, IndexError):
            pass
    try:
        return float(t["building:levels"]) * 3.6 + 2
    except (KeyError, ValueError):
        return 9.0


class Occluder:
    """Ground raster of building-top heights (metres above the anchor ground), 2 m cells. A ground
    point is hidden when a building between it and the camera rises above the line of sight."""
    CELL = 2.0

    def __init__(self, cam, data, dem, h_ref, ground):
        self.cam = cam
        tops = []
        for el in data.get("elements", []):
            if el.get("type") != "way" or "geometry" not in el:
                continue
            la = np.array([g["lat"] for g in el["geometry"]])
            lo = np.array([g["lon"] for g in el["geometry"]])
            base = dem.height(float(la.mean()), float(lo.mean())) - h_ref
            p = enu(cam, la, lo, cam["h0"])
            tops.append((p[:, :2], base + building_height(el.get("tags", {}))))
        pts = np.concatenate([p for p, _ in tops] + [ground])
        self.e0, self.n0 = pts.min(0) - 300
        w, h = ((pts.max(0) + 300 - [self.e0, self.n0]) / self.CELL).astype(int) + 1
        img = Image.new("F", (int(w), int(h)), -1000.0)
        draw = ImageDraw.Draw(img)
        for p, top in sorted(tops, key=lambda t: t[1]):
            xy = [((x - self.e0) / self.CELL, (self.n0 - y) / self.CELL + h - 1) for x, y in p]
            if len(xy) >= 3:
                draw.polygon(xy, fill=float(top))
        self.top = np.asarray(img)
        hd = math.radians(cam["heading_deg"])
        self.back = np.array([-math.sin(hd), -math.cos(hd)])
        self.slope = math.tan(math.radians(cam["elevation_deg"]))

    def hidden(self, en, u):
        """en: (N, 2) ground ENU, u: (N,) height above anchor ground -> bool (N,)."""
        d = np.arange(3.0, 260.0, 2.0)
        q = en[:, None, :] + d[None, :, None] * self.back
        ix = ((q[..., 0] - self.e0) / self.CELL).astype(int)
        iy = (self.top.shape[0] - 1 - (q[..., 1] - self.n0) / self.CELL).astype(int)
        ok = (ix >= 0) & (iy >= 0) & (ix < self.top.shape[1]) & (iy < self.top.shape[0])
        tops = np.where(ok, self.top[iy.clip(0, self.top.shape[0] - 1), ix.clip(0, self.top.shape[1] - 1)], -1000)
        return (tops > u[:, None] + d[None, :] * self.slope + 1.0).any(1)


class Dem:
    """Terrarium PNG tiles: metres = R*256 + G + B/256 - 32768 (orthometric)."""

    def __init__(self):
        self.tiles = {}

    def tile(self, x, y):
        if (x, y) not in self.tiles:
            path = CACHE / "dem" / f"{DEM_Z}_{x}_{y}.png"
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(fetch(
                    f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{DEM_Z}/{x}/{y}.png"))
            a = np.asarray(Image.open(io.BytesIO(path.read_bytes())).convert("RGB")).astype(np.float64)
            self.tiles[(x, y)] = a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768
        return self.tiles[(x, y)]

    def height(self, lat, lon):
        n = 2 ** DEM_Z
        fx = (lon + 180) / 360 * n * 256
        fy = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n * 256
        x0, y0 = math.floor(fx - 0.5), math.floor(fy - 0.5)
        tx, ty = fx - 0.5 - x0, fy - 0.5 - y0

        def px(x, y):
            return self.tile(x // 256, y // 256)[y % 256, x % 256]
        return ((px(x0, y0) * (1 - tx) + px(x0 + 1, y0) * tx) * (1 - ty) +
                (px(x0, y0 + 1) * (1 - tx) + px(x0 + 1, y0 + 1) * tx) * ty)


def rdp(pts, tol):
    if len(pts) < 3:
        return pts
    a, b = pts[0], pts[-1]
    d = b - a
    norm = math.hypot(*d) or 1.0
    dist = np.abs(d[0] * (pts[:, 1] - a[1]) - d[1] * (pts[:, 0] - a[0])) / norm
    i = int(dist.argmax())
    if dist[i] <= tol:
        return np.array([a, b])
    return np.concatenate([rdp(pts[:i + 1], tol)[:-1], rdp(pts[i:], tol)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="use the live site's painted.json")
    a = ap.parse_args()
    cam = load_cam()
    step = cam["step_px"]
    names = painted_names(a.live)
    painted = {parse_name(n) for n in names}
    corners = [inverse_ground(cam, c * step + dx, r * step + dy)
               for r, c in painted for dx in (-step, step) for dy in (-step, step)]
    lats, lons = zip(*corners)
    bbox = (min(lats) - 0.008, min(lons) - 0.008, max(lats) + 0.012, max(lons) + 0.008)
    osm = osm_ways(bbox)
    dem = Dem()
    h_ref = cam["h0"] - cam["geoid_offset_m"]
    heights = {}

    def project(geom, ids):
        la = np.array([g["lat"] for g in geom])
        lo = np.array([g["lon"] for g in geom])
        for g, nid in zip(geom, ids):
            if nid not in heights:
                heights[nid] = dem.height(g["lat"], g["lon"]) - h_ref
        u = np.array([heights[nid] for nid in ids])
        p = enu(cam, la, lo, cam["h0"] + u)
        return global_px(cam, LEVEL, p), p[:, :2], u

    def inside(p):
        return (round(p[1] / step), round(p[0] / step)) in painted

    node_index, ways = {}, []

    def node_ref(nid):
        return node_index.setdefault(nid, len(node_index))

    for el in osm.get("elements", []):
        t = el.get("tags", {})
        if el.get("type") != "way" or "geometry" not in el:
            continue
        if t.get("tunnel") in ("yes", "building_passage") or t.get("indoor") == "yes" or t.get("area") == "yes":
            continue
        if t.get("access") in ("private", "no") and "railway" not in t:
            continue
        if "railway" in t:
            kind = KINDS.index("rail")
        else:
            kind = ROAD[t["highway"]]
            if t["highway"] == "service" and t.get("service") in ("driveway", "parking_aisle", "drive-through"):
                continue
        geom, ids = el["geometry"], el["nodes"]
        ow = t.get("oneway")
        oneway = ow in ("yes", "true", "1", "-1") or t.get("junction") == "roundabout" or \
            (t.get("highway") in ("motorway", "motorway_link") and ow != "no")
        if ow == "-1":
            geom, ids = geom[::-1], ids[::-1]
        if kind in (KINDS.index("foot"), KINDS.index("rail")):
            oneway = False
        pts, en, u = project(geom, ids)
        dense = []
        for i in range(len(pts) - 1):
            k = max(1, int(math.hypot(*(pts[i + 1] - pts[i])) // 6))
            for j in range(k):
                f = j / k
                dense.append((pts[i] + (pts[i + 1] - pts[i]) * f, en[i] + (en[i + 1] - en[i]) * f,
                              u[i] + (u[i + 1] - u[i]) * f, ids[i] if j == 0 else None))
        dense.append((pts[-1], en[-1], u[-1], ids[-1]))
        run, start = [], None
        for d in dense:
            if inside(d[0]):
                if not run:
                    start = d[3]
                run.append(d)
            elif run:
                ways.append((kind, oneway, start, None, run))
                run = []
        if run:
            ways.append((kind, oneway, start, run[-1][3], run))

    ground = np.concatenate([np.array([d[1] for d in run]) for *_, run in ways])
    occ = Occluder(cam, osm_buildings(bbox), dem, h_ref, ground)
    flat_en = ground
    flat_u = np.concatenate([np.array([d[2] for d in run]) for *_, run in ways])
    hidden_all = np.concatenate([occ.hidden(flat_en[i:i + 20000], flat_u[i:i + 20000])
                                 for i in range(0, len(flat_en), 20000)])
    print(f"occlusion: {hidden_all.mean():.1%} of path points hidden behind buildings")

    out, cursor = [], 0
    for kind, oneway, start, end, run in ways:
        hid = hidden_all[cursor:cursor + len(run)]
        cursor += len(run)
        dense = np.array([d[0] for d in run])
        seg = np.hypot(*np.diff(dense, axis=0).T)
        if seg.sum() < 12:
            continue
        s_at = np.concatenate([[0.0], np.cumsum(seg)])
        spans, open_at = [], None
        for i, h in enumerate(hid):
            if h and open_at is None:
                open_at = s_at[i]
            elif not h and open_at is not None:
                spans += [round(open_at), round(s_at[i])]
                open_at = None
        if open_at is not None:
            spans += [round(open_at), round(s_at[-1]) + 1]
        q = np.round(rdp(dense, 0.75)).astype(int)
        flat = [int(q[0, 0]), int(q[0, 1])] + np.diff(q, axis=0).ravel().tolist()
        w = [kind, int(oneway), node_ref(start) if start is not None else -1,
             node_ref(end) if end is not None else -1, flat]
        if spans:
            w.append(spans)
        out.append(w)
    payload = {"v": 1, "zoom": cam["levels"][LEVEL]["zoom"], "ppm": cam["levels"][LEVEL]["ppm"],
               "heading_deg": cam["heading_deg"], "elevation_deg": cam["elevation_deg"],
               "squares": len(painted), "kinds": KINDS, "ways": out}
    OUT.write_text(json.dumps(payload, separators=(",", ":")))
    counts = {k: sum(1 for w in out if w[0] == i) for i, k in enumerate(KINDS)}
    print(f"wrote {OUT.relative_to(ROOT)}: {len(out)} paths over {len(painted)} squares "
          f"({OUT.stat().st_size // 1024} KB) {counts}")


if __name__ == "__main__":
    main()
