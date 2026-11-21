# Tiny Salt Lake City

A painted, isometric-style tile map of Salt Lake City, following Marcelo Eduardo's
[Mini World workflow](https://marceloeduardo.com/tiny-city-workflow.html). Google Photorealistic 3D
Tiles are rendered with one fixed orthographic camera. Codex then repaints each 1,024 px square, and
the painted squares are stitched into a Leaflet tile pyramid.

**Live map:** <https://slc-miniworld.pages.dev>

## How to help

The goal is all of Salt Lake County, 20,838 squares. Each square costs one AI image generation,
and one ChatGPT plan allows about 190 a day, so the map grows faster with more people painting.

- **Paint a block.** Claim 25 squares in an issue, render and paint them on your machine with
  your own Google Maps key and ChatGPT plan, and attach the result. Steps: [CONTRIBUTING.md](CONTRIBUTING.md).
- **Paint with a coding agent.** Point Codex, Claude Code or another agent at [AGENTS.md](AGENTS.md)
  and ask it to help you paint a block. It does the commands and checks; you claim the block,
  hold the keys and attach the zip.
- **Improve the pipeline or the web page.** Issues and pull requests are welcome. AGENTS.md has the
  rules that keep the grid and the look consistent.
- **Report a problem on the map**, like a road painted as water or a visible seam, in an issue
  with a screenshot and roughly where it is.

## Camera and grid (frozen once painting starts)

| | |
|---|---|
| Anchor | Salt Lake Temple, 40.770455, −111.891907; ground height from the probe (`cam/slc_probe.json`) |
| Camera | orthographic, heading 45° (looking northeast), 30° down (2:1), no perspective |
| Squares | 1,024 px painted, 768 px step (256 px overlap), rendered at 2,048 px then downscaled |
| Detail | 3.4 px/m, all of Salt Lake County: 21,264 squares in the list, 20,838 of them inside the county boundary, about 0.1 km² of new ground each. The grid grew from downtown to Salt Lake City and Millcreek (AOI −112.105…−111.735, 40.655…40.855), then by the county's own frames; existing squares always keep their names |
| Overview | 0.425 px/m (exactly 1/8), out to the Great Salt Lake shore at Saltair. 147 squares |

Squares are `r<row>_c<col>`. Row 0, column 0 is centred on the anchor, and rows grow down the
screen. All scripts project through `pipeline/geo.py`. `pipeline/selftest.py` checks that the
browser camera and the Python projection agree (the last check passed with errors under 0.4 px).

The county squares come from `pipeline/area_frames.py`. It samples the UGRC county boundary
(`data/county_bounds.geojson`) about every 60 m and projects each point at its USGS 3DEP ground
height, because ground 2,000 m up the Wasatch lands about 8 rows higher on screen than valley
ground. `plan_grid.py --extend "Salt Lake County"` then appends those frames to the frozen list.
`data/frames_by_area.json` holds the per-area lists.

## Setup

```bash
npm install                         # three, 3d-tiles-renderer, leaflet (no browser download)
uv venv .venv && uv pip install --python .venv numpy pillow
cp .env.example .env                # add GOOGLE_MAPS_API_KEY (Map Tiles API enabled)
```

Rendering uses the installed Google Chrome in headless mode (`CHROME_PATH` overrides the path).
Painting uses the `codex` CLI logged in with a ChatGPT plan. It calls Codex's built-in image
generation through `codex exec`, with `gpt-6-luna` at low effort driving the tool call.

## Run

Use the virtualenv Python for every `python` step: `.venv/bin/python` on macOS and Linux,
`.venv\Scripts\python.exe` on Windows. Contributors start from the frozen grid and use
`pipeline/contrib.py` instead (see CONTRIBUTING.md).

```bash
python pipeline/places.py --geocode          # landmarks (Nominatim), optional refresh
python pipeline/osm.py                        # OSM water -> data/osm_water.json
python pipeline/selftest.py prepare && node render3d/server.mjs --mode selftest && python pipeline/selftest.py check

# 1. coverage probe: freezes the ground height h0
python pipeline/probe.py prepare
node render3d/server.mjs --mode probe
python pipeline/probe.py finish

# 2. frozen shot lists
python pipeline/plan_grid.py --level detail
python pipeline/plan_grid.py --level overview

# 3. render (resumable; skips finished squares), then downscale + QA flags
node render3d/server.mjs --mode render --level detail [--only r0_c0,r0_c1] [--limit 50]
python pipeline/prep_renders.py --level detail

# 4. water masks from OSM + height renders
python pipeline/water.py masks --level detail

# 5. paint: bootstrap one square, review the style, then paint the rest
python pipeline/paint.py --level detail --block=-1:1,-1:1 --bootstrap
cp style/candidate.png style/ref.png          # human gate: approve the style
python pipeline/paint.py --level detail --block=-1:1,-1:1 --workers 3

# 6. water/defect pass, stitch, pyramid, viewer
python pipeline/water.py fix --level detail
python pipeline/stitch.py --level detail
python -m http.server 8000                    # then open http://localhost:8000/viewer/
```

`stitch.py --source renders` builds the same pyramid from the unpainted renders. Use it to
check coverage before spending painting quota.

## What each step guards

- **Probe**: the anchor's ground height is the 5th-percentile surface height around the temple,
  so the spire does not lift the ground plane. Each landmark and AOI corner gets a
  yes/partial/no status from load success, coverage and relief.
- **Render**: a square is saved only after the tile queue has been empty for 12 consecutive
  frames. Timeouts are logged and skipped (Google's quota limit shows up as a stalled queue).
  The 2,048 px raw renders are deleted after downscaling.
- **QA flags** (`renders/<level>/qa.json`): black or missing geometry above 2%, and possible
  blurring (Laplacian variance under 15% of the median).
- **Paint**: wavefront order with painted top, left and top-left neighbours pasted into the
  overlap band. Each result is registered back onto the render (scale 0.94–1.06, shift) and
  retried if it moves more than 48 px. A run stops on a Codex quota or auth message, or when
  more than 20% of squares fail. Squares at least 92% water get procedural water instead of a
  model call.
- **Water fix**: OSM water, limited to the height render's water surface (+1.5 m). Piers,
  bridges and boats keep their paint, and bright exposed lakebed stays land. Masked pixels
  painted as non-water are filled with the square's water colour.
- **Stitch**: least-squares RGB offsets over overlaps, with squares at least 60% water pinned
  to 0, then linear blending across the 256 px overlap.

## Estimated time and cost

| Step | Per square | 869 detail + 147 overview |
|---|---|---|
| Render (M4, 1 Chrome) | ~10–30 s, depending on tile cache | ~3–8 h |
| Paint (Codex, 3 parallel) | ~25–90 s wall, ~1 image-generation unit | ~3–9 h; about $65 at MiniDF's measured $0.065/square on a ChatGPT plan, counted against plan quota |
| Water, stitch, pyramid | seconds | < 30 min |

Google bills Photorealistic 3D Tiles per root-tileset request (one per render session, here one
per Chrome launch). Tile fetches within a session are covered by daily quotas, so check the
Map Tiles API quota page before a full run.

## Terms and attribution

Google's Map Tiles API terms restrict caching and storing Google content and making derivative
works from it. Renders, heights and painted output are gitignored and never committed; the
painted map is served from the live site. Read the current Map Tiles API policies before
publishing anything. The viewer always shows the Google and OpenStreetMap attribution.

The code is MIT licensed (see LICENSE). That covers the scripts and viewer only, not imagery.
Bundled data keeps its own terms:

- Leaflet (`viewer/vendor/`), BSD 2-Clause, © Vladimir Agafonkin and contributors.
- `data/osm_water.json` and the place list are derived from OpenStreetMap, © OpenStreetMap
  contributors, available under the Open Database License (ODbL).
- `data/city_bounds.geojson` and `data/county_bounds.geojson` come from the Utah Geospatial
  Resource Center (UGRC) municipal and county boundaries.
- The county frame list used USGS 3D Elevation Program (3DEP) heights, which are public domain.
  The DEM itself is not in the repo.
