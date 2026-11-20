"""Shared camera geometry. Every script projects through these functions so renders,
masks, stitching and viewer markers agree to the pixel.

Frames: (r, c) is centred at global pixel (c*step, r*step); global X = sx*ppm, Y = -sy*ppm,
where (sx, sy) are screen-plane metres of a fixed orthographic camera through the anchor.
"""
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
A_WGS84 = 6378137.0
F_WGS84 = 1 / 298.257223563
E2 = F_WGS84 * (2 - F_WGS84)


def load_cam(city="slc"):
    cam = json.loads((ROOT / "cam" / f"{city}.json").read_text())
    probe = ROOT / "cam" / f"{city}_probe.json"
    cam["probe"] = json.loads(probe.read_text()) if probe.exists() else None
    cam["h0"] = cam["probe"]["h0"] if cam["probe"] else cam["ground_h_guess"]
    h, e = math.radians(cam["heading_deg"]), math.radians(cam["elevation_deg"])
    cam["fwd"] = np.array([math.cos(e) * math.sin(h), math.cos(e) * math.cos(h), -math.sin(e)])
    cam["right"] = np.array([math.cos(h), -math.sin(h), 0.0])
    cam["up"] = np.array([math.sin(e) * math.sin(h), math.sin(e) * math.cos(h), math.cos(e)])
    return cam


def ecef(lat, lon, h):
    lat, lon = np.radians(lat), np.radians(lon)
    n = A_WGS84 / np.sqrt(1 - E2 * np.sin(lat) ** 2)
    return np.stack([(n + h) * np.cos(lat) * np.cos(lon),
                     (n + h) * np.cos(lat) * np.sin(lon),
                     (n * (1 - E2) + h) * np.sin(lat)], axis=-1)


def enu(cam, lat, lon, h):
    """Geodetic (ellipsoidal h) -> ENU metres relative to the anchor at ground height h0."""
    lat0, lon0 = math.radians(cam["anchor"]["lat"]), math.radians(cam["anchor"]["lon"])
    d = ecef(np.asarray(lat, float), np.asarray(lon, float), np.asarray(h, float)) - \
        ecef(cam["anchor"]["lat"], cam["anchor"]["lon"], cam["h0"])
    rot = np.array([[-math.sin(lon0), math.cos(lon0), 0],
                    [-math.sin(lat0) * math.cos(lon0), -math.sin(lat0) * math.sin(lon0), math.cos(lat0)],
                    [math.cos(lat0) * math.cos(lon0), math.cos(lat0) * math.sin(lon0), math.sin(lat0)]])
    return d @ rot.T


def global_px(cam, level, p_enu):
    """ENU points (..., 3) -> global pixel (X, Y) at the level's ppm."""
    ppm = cam["levels"][level]["ppm"]
    return np.stack([p_enu @ cam["right"] * ppm, -(p_enu @ cam["up"]) * ppm], axis=-1)


def latlon_px(cam, level, lat, lon, h_rel=0.0):
    """h_rel is height above the anchor ground (metres)."""
    return global_px(cam, level, enu(cam, lat, lon, cam["h0"] + np.asarray(h_rel, float)))


def frame_target_enu(cam, level, r, c):
    """ENU point at the centre of frame (r, c) on the screen plane through the anchor."""
    s = cam["step_px"] / cam["levels"][level]["ppm"]
    return c * s * cam["right"] - r * s * cam["up"]


def frame_origin(cam, r, c):
    """Global pixel of the frame's top-left corner."""
    half = cam["frame_px"] // 2
    return c * cam["step_px"] - half, r * cam["step_px"] - half


def frame_name(r, c):
    return f"r{r}_c{c}"


def parse_name(name):
    r, c = name.split("_")
    return int(r[1:]), int(c[1:])


def _hull(points):
    pts = sorted(map(tuple, points))
    def half(seq):
        out = []
        for p in seq:
            while len(out) >= 2 and (out[-1][0] - out[-2][0]) * (p[1] - out[-2][1]) - \
                    (out[-1][1] - out[-2][1]) * (p[0] - out[-2][0]) <= 0:
                out.pop()
            out.append(p)
        return out
    lower, upper = half(pts), half(reversed(pts))
    return np.array(lower[:-1] + upper[:-1])


def _inside(hull, p):
    n = len(hull)
    for i in range(n):
        a, b = hull[i], hull[(i + 1) % n]
        if (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) < 0:
            return False
    return True


def plan_frames(cam, level):
    """Frames whose core touches the AOI box projected at ground and at ground+terrain margin."""
    aoi = cam["levels"][level]["aoi"]
    lons = np.linspace(aoi["west"], aoi["east"], 9)
    lats = np.linspace(aoi["south"], aoi["north"], 9)
    ring = [(aoi["south"], x) for x in lons] + [(aoi["north"], x) for x in lons] + \
           [(y, aoi["west"]) for y in lats] + [(y, aoi["east"]) for y in lats]
    la, lo = np.array(ring).T
    pts = np.concatenate([latlon_px(cam, level, la, lo, 0.0),
                          latlon_px(cam, level, la, lo, cam["terrain_margin_m"])])
    hull = _hull(pts)
    step = cam["step_px"]
    half = step / 2
    r0, r1 = int(np.floor(hull[:, 1].min() / step)) - 1, int(np.ceil(hull[:, 1].max() / step)) + 1
    c0, c1 = int(np.floor(hull[:, 0].min() / step)) - 1, int(np.ceil(hull[:, 0].max() / step)) + 1
    frames = []
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            cx, cy = c * step, r * step
            probes = [(cx + dx, cy + dy) for dx in (-half, 0, half) for dy in (-half, 0, half)]
            if any(_inside(hull, p) for p in probes) or any(
                    abs(p[0] - cx) <= half and abs(p[1] - cy) <= half for p in hull):
                frames.append((r, c))
    return frames


def wavefront(frames):
    """Paint order: anti-diagonals from the top-left so top/left neighbours are done first."""
    return sorted(frames, key=lambda rc: (rc[0] + rc[1], rc[0]))
