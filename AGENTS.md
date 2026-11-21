# AGENTS.md

Tiny Salt Lake City: Google Photorealistic 3D Tiles rendered through one fixed isometric camera,
repainted one 1,024 px square at a time by Codex, stitched into a Leaflet map at
<https://slc-miniworld.pages.dev>. `README.md` walks through the pipeline; `CONTRIBUTING.md`
covers painting a block. This file is for agents changing the code, the docs or the web page.

## Invariants

- **The grid is frozen.** Squares are `r<row>_c<col>`, and a name always means the same camera
  target. The grid only grows: `pipeline/area_frames.py` lists an area's squares, then
  `plan_grid.py --extend AREA` appends them. The camera fields, `h0`, `ppm` and `step_px` in
  `cam/` stay as they are; changing them would orphan every render and painting.
- **One projection.** `pipeline/geo.py` and `render3d/render.js` must agree. After touching
  either, run the self-test from the README (it needs a Google key).
- **The look is shared.** Thousands of squares come from different people's machines, so the
  prompts in `pipeline/paint.py` and the style reference stay fixed. A prompt change is the
  maintainer's call, backed by a side-by-side bake-off of the same squares.
- **Imagery lives outside git.** Renders, heights, masks, paintings, stitches, tiles, the style
  reference and submissions are gitignored by root-anchored rules (`/painted/`, not
  `painted/`). Give any new output folder an anchored rule too: an unanchored `tiles/` once
  hid `deploy/functions/tiles/` from git.
- **Raw renders stay on the machine that rendered them.** Google's Maps Platform terms forbid
  storing, resharing or rehosting their content, so renders and heights are never uploaded,
  served or attached anywhere. Each person renders with their own Google key.
- **Keys stay in `.env`.** Read them with `painters.env_value`; keep them out of logs and output.
- **The maintainer deploys.** Pull requests change code; `deploy/sync_tiles.ps1` and
  `wrangler pages deploy` run on the maintainer's machine after merge.
- **`data/frames_by_area.json` decides membership**: which squares are in the county, the
  cities, and `reserved` (the maintainer's own Codex run, tracked in the pinned claim issue).

## Web page (`viewer/`)

- Plain HTML plus Leaflet 1.9, vendored in `viewer/vendor/`. No build step and no framework;
  keep it a single page that works from a static file server.
- To work on it without any local data:

  ```bash
  python scripts/live_config.py        # viewer/config.json pointing at the live tiles
  python -m http.server 8000           # open http://localhost:8000/viewer/
  ```

- `viewer/config.json` is generated (by `stitch.py` locally, by `deploy/build_site.py` for the
  site) and gitignored.
- The map uses `L.CRS.Simple` in global pixels, not latitude and longitude. Place pins carry
  pixel positions from `pipeline/places.py`.
- Unpainted parts of detail tiles are `stitch.py`'s background colour (24, 26, 31), and the
  viewer's `Keyed` layer makes that colour transparent so the overview shows through. The two
  values change together.
- The Google, OpenStreetMap and Codex attribution stays visible at every size.
- Check changes at desktop width and at 375 px; the panel collapses under 600 px.

## Pipeline code

- Python 3.11+ with NumPy and Pillow; Node only for `render3d/`. Ask in the issue before adding
  a dependency.
- Windows and macOS both run the pipeline. Gotchas that already bit once:
  - The venv Python is `.venv\Scripts\python.exe` on Windows and `.venv/bin/python` elsewhere.
  - Codex gets its prompt on stdin, because Windows runs it through an npm `.cmd` shim that
    mangles quoted arguments.
  - Chrome's path comes from `CHROME_PATH`, with per-platform defaults in
    `render3d/server.mjs`.
- Contributor zips are untrusted input and go through `pipeline/intake.py` only. It reads
  members in memory, re-encodes through Pillow and never overwrites a painted square.

## Checks before a pull request

- `python -m py_compile pipeline/*.py deploy/*.py scripts/*.py`
- `python pipeline/contrib.py open --limit 3` runs against the live `painted.json`.
- Camera or projection changes: the README self-test passes (worst error under 2 px).
- Viewer changes: the local viewer above, looked at in a browser at both widths.

In the pull request, say what you ran and what you saw. Keep one topic per pull request and
leave generated images out of it. `STATUS.md` is an early progress log: history, not
instructions.
