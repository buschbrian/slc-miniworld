"""Copy the viewer into deploy/site/ with tile paths pointed at the /tiles/ Pages Function, and write the
lists contributors work from: painted.json (squares already painted) and renders.json (squares rendered
here, open to contributors and clean in QA, whose renders sync_tiles.ps1 shares so contributors need no
Google key).

usage: python deploy/build_site.py, then pwsh deploy/sync_tiles.ps1, then: cd deploy && wrangler pages deploy
"""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "deploy" / "site"

shutil.rmtree(SITE, ignore_errors=True)
shutil.copytree(ROOT / "viewer", SITE, ignore=shutil.ignore_patterns("config.json"))
cfg = json.loads((ROOT / "viewer" / "config.json").read_text(encoding="utf-8"))
for tag, layer in cfg["layers"].items():
    layer["path"] = f"/tiles/{tag}/{{z}}/{{x}}/{{y}}.jpg"
(SITE / "config.json").write_text(json.dumps(cfg, indent=1), encoding="utf-8")
painted = sorted(p.stem for p in (ROOT / "painted" / "detail").glob("r*_c*.png"))
(SITE / "painted.json").write_text(json.dumps({"detail": painted}), encoding="utf-8")

areas = json.loads((ROOT / "data" / "frames_by_area.json").read_text(encoding="utf-8"))
open_sq = (set(areas["Salt Lake County"]) | set(areas["Salt Lake City"])) - set(areas["reserved"]) - set(painted)
qa_path = ROOT / "renders" / "detail" / "qa.json"
qa = json.loads(qa_path.read_text()) if qa_path.exists() else {}
shared = sorted(n for n in open_sq if (ROOT / "renders" / "detail" / f"{n}.jpg").exists()
                and n in qa and "black_or_missing" not in qa[n]["flags"])
(SITE / "renders.json").write_text(json.dumps({"detail": shared}), encoding="utf-8")
print(f"site built: {', '.join(f'{k} ({v['frames']} squares)' for k, v in cfg['layers'].items())}; "
      f"painted.json lists {len(painted)}, renders.json {len(shared)}")
