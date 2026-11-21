# AGENTS.md

Tiny Salt Lake City: Google Photorealistic 3D Tiles rendered through one fixed isometric camera,
repainted one 1,024 px square at a time by Codex, stitched into a Leaflet map at
<https://slc-miniworld.pages.dev>. The goal is all of Salt Lake County (20,838 squares).

You are probably here for one of three jobs. Find yours, then read **Invariants**, which apply to
all of them.

| Asked to… | Read |
|---|---|
| help someone paint a block of the map | [Painting a block](#painting-a-block) |
| change the web page | [Web page](#web-page-viewer) |
| fix or extend the pipeline | [Pipeline code](#pipeline-code), then [Checks](#checks-before-a-pull-request) |

`README.md` explains the whole pipeline; `CONTRIBUTING.md` is the human version of the painting
steps below.

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
- **Raw renders stay on the machine that rendered them.** Google's Maps Platform terms forbid
  storing, resharing or rehosting their content, so renders and heights are never uploaded,
  served or attached anywhere. Each person renders with their own Google key. Only paintings
  leave a contributor's machine, packed by `contrib.py pack`.
- **Imagery lives outside git.** Renders, heights, masks, paintings, stitches, tiles, the style
  reference and submissions are gitignored by root-anchored rules (`/painted/`, not
  `painted/`). Give any new output folder an anchored rule too: an unanchored `tiles/` once
  hid `deploy/functions/tiles/` from git.
- **Keys stay in `.env`.** Read them with `painters.env_value`; keep them out of logs and output.
- **The maintainer deploys.** Pull requests change code; `deploy/build_site.py`,
  `deploy/sync_tiles.ps1` and `wrangler pages deploy` run on the maintainer's machine after merge.
- **`data/frames_by_area.json` decides membership**: which squares are in the county, the
  cities, and `reserved` (the maintainer's own Codex run). Claims live in GitHub issues labelled
  `claim`; the pinned ones are standing claims.

## Painting a block

Some steps belong to the person you are helping, because they involve their accounts. Ask them
to do those and wait; do the rest yourself. Use the virtualenv Python for every `python` below
(`.venv\Scripts\python.exe` on Windows, `.venv/bin/python` elsewhere).

1. **Setup.** Done when `python pipeline/contrib.py open --limit 3` prints blocks.
   - You: `npm install`, `uv venv .venv`, `uv pip install --python .venv numpy pillow`,
     `cp .env.example .env`.
   - The person: creates a Google Maps Platform key with the Map Tiles API enabled and pastes it
     into `.env` as `GOOGLE_MAPS_API_KEY`, or runs `bash scripts/set_key.sh`. Never ask them to
     paste the key into the chat. They also sign in to the Codex CLI with a ChatGPT plan that
     includes image generation (`codex login`).
2. **Block.** Done when the person has opened a **Claim a block** issue and the claim is
   acknowledged. Suggest a block from `contrib.py open` (`--area Millcreek` and similar filter
   by area) that no open `claim` issue mentions. `contrib.py show <block>` lists its squares.
3. **Prepare.** Done when `contrib.py prepare <block>` ends with every square rendered. It
   downloads the style reference and the painted neighbours (for seam context), renders, runs
   QA and builds water masks. Run it again if squares are missing; it resumes.
4. **Paint.** Done when `contrib.py show <block>` reports every square painted here. Each square
   is one image generation. When the plan's daily image limit stops `contrib.py paint`, tell the
   person when it resets and run the same command after; finished squares are skipped.
5. **Look.** Done when you have compared every painting in `painted/detail/` with its render in
   `renders/detail/` and found it is the same place: same streets, buildings, parks and water,
   in the shared style. Set aside any square with invented or missing streets or buildings,
   water where the render has land, or black holes, by moving it out of `painted/detail/`, and
   paint it again. Added or missing single trees are fine.
6. **Pack.** Done when `contrib.py pack <block> --github <their-name>` has written the zip(s)
   in `submissions/`. The person attaches them to the claim issue.

The paintings are the only thing that leaves the machine. Renders, heights and the `.env` stay.

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
  - Codex gets its prompt on stdin, because Windows runs it through an npm `.cmd` shim that
    mangles quoted arguments.
  - Chrome's path comes from `CHROME_PATH`, with per-platform defaults in
    `render3d/server.mjs`.
  - `water.py fix` repaints only large water bodies (mask value 255). OSM draws canals through
    culverts under streets, and repainting those once put blue stripes across roads.
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
