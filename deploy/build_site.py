"""Copy the viewer into deploy/site/ with tile paths pointed at the /tiles/ Pages Function, and list the
painted squares in painted.json so contributors know what is done.

usage: python deploy/build_site.py     then: cd deploy && wrangler pages deploy
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
print(f"site built: {', '.join(f'{k} ({v['frames']} squares)' for k, v in cfg['layers'].items())}; "
      f"painted.json lists {len(painted)}")
