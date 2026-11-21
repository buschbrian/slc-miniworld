"""Point a local viewer at the live map's tiles, for working on viewer/ without rendering anything.

  python scripts/live_config.py           # writes viewer/config.json from the live site
  python -m http.server 8000              # then open http://localhost:8000/viewer/

viewer/config.json is normally written by pipeline/stitch.py; this refuses to replace one unless --force.
"""
import argparse
import json
import urllib.request
from pathlib import Path

SITE = "https://slc-miniworld.pages.dev"
OUT = Path(__file__).resolve().parents[1] / "viewer" / "config.json"

ap = argparse.ArgumentParser()
ap.add_argument("--force", action="store_true", help="replace an existing viewer/config.json")
a = ap.parse_args()
if OUT.exists() and not a.force:
    raise SystemExit(f"{OUT} exists (probably from stitch.py); pass --force to replace it")
req = urllib.request.Request(f"{SITE}/config.json", headers={"User-Agent": "slc-miniworld-dev"})
with urllib.request.urlopen(req, timeout=30) as r:
    cfg = json.load(r)
for layer in cfg["layers"].values():
    layer["path"] = SITE + layer["path"]
OUT.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
print(f"wrote {OUT.name}: " + ", ".join(f"{k} ({v['frames']} squares)" for k, v in cfg["layers"].items()))
