"""Fetch OSM water for the overview AOI from Overpass and assemble polygons.

Writes data/osm_water.json: {"areas": [{"name", "outer": [[lon,lat],..], "inners": [...]}],
"lines": [{"name", "kind", "coords": [[lon,lat],..], "width_m"}]}. Data (c) OpenStreetMap contributors, ODbL.
"""
import json
import urllib.parse
import urllib.request

from geo import ROOT, load_cam

OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
LINE_WIDTH_M = {"river": 18.0, "canal": 8.0}


def query(bbox):
    s, w, n, e = bbox
    b = f"({s},{w},{n},{e})"
    return f"""[out:json][timeout:240];
(
  way["natural"="water"]{b};
  relation["natural"="water"]{b};
  way["waterway"="riverbank"]{b};
  way["landuse"="reservoir"]{b};
  relation["landuse"="reservoir"]{b};
  way["waterway"~"^(river|canal)$"]{b};
);
out geom;"""


def join_rings(segments):
    """Join open way segments (lists of (lon, lat)) into closed rings."""
    segs = [list(s) for s in segments if len(s) >= 2]
    rings = []
    while segs:
        ring = segs.pop()
        changed = True
        while ring[0] != ring[-1] and changed:
            changed = False
            for i, s in enumerate(segs):
                if s[0] == ring[-1]:
                    ring += s[1:]
                elif s[-1] == ring[-1]:
                    ring += s[-2::-1]
                elif s[-1] == ring[0]:
                    ring = s[:-1] + ring
                elif s[0] == ring[0]:
                    ring = s[:0:-1] + ring
                else:
                    continue
                segs.pop(i)
                changed = True
                break
        if ring[0] == ring[-1] and len(ring) >= 4:
            rings.append(ring)
    return rings


def main():
    cam = load_cam()
    a = cam["levels"]["overview"]["aoi"]
    q = query((a["south"], a["west"], a["north"], a["east"]))
    els = None
    for url in OVERPASS:
        req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": q}).encode(),
                                     headers={"User-Agent": "tiny-city-pipeline/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                els = json.load(r)["elements"]
            break
        except Exception as e:  # mirrors are busy at times; try the next one
            print(f"{url}: {e}")
    if els is None:
        raise SystemExit("all Overpass endpoints failed")
    areas, lines, skipped = [], [], 0
    for el in els:
        tags = el.get("tags", {})
        name = tags.get("name", "")
        if el["type"] == "way":
            pts = [(p["lon"], p["lat"]) for p in el.get("geometry", [])]
            ww = tags.get("waterway")
            if ww in LINE_WIDTH_M:
                lines.append({"name": name, "kind": ww, "coords": pts, "width_m": LINE_WIDTH_M[ww]})
            elif len(pts) >= 4 and pts[0] == pts[-1]:
                areas.append({"name": name, "outer": pts, "inners": []})
            else:
                skipped += 1
        elif el["type"] == "relation":
            members = [m for m in el.get("members", []) if m["type"] == "way" and m.get("geometry")]
            seg = lambda role: [[(p["lon"], p["lat"]) for p in m["geometry"]] for m in members if m.get("role") == role]
            outers, inners = join_rings(seg("outer")), join_rings(seg("inner"))
            for o in outers:
                areas.append({"name": name, "outer": o, "inners": inners})
            skipped += not outers
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "osm_water.json").write_text(json.dumps({"areas": areas, "lines": lines}))
    names = sorted({x["name"] for x in areas + lines if x["name"]})
    print(f"{len(areas)} water areas, {len(lines)} river/canal lines, {skipped} skipped")
    print("named:", ", ".join(names[:30]))


if __name__ == "__main__":
    main()
