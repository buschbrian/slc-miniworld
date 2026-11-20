#!/usr/bin/env node
// Local job server + headless Chrome driver. No browser-automation dependency: Chrome loads the
// page, the page pulls its job from /job and POSTs images back here.
//
//   node render3d/server.mjs --mode render --level detail [--only r0_c0,r0_c1] [--limit 9]
//   node render3d/server.mjs --mode probe
//   node render3d/server.mjs --mode selftest
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => {
  if (a.startsWith('--')) acc.push([a.slice(2), all[i + 1] && !all[i + 1].startsWith('--') ? all[i + 1] : 'true']);
  return acc;
}, []));
const mode = args.mode || 'render';
const city = args.city || 'slc';
const level = args.level || 'detail';
const CHROME = process.env.CHROME_PATH || {
  win32: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
}[process.platform] || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const ANGLE = { darwin: 'metal', win32: 'd3d11' }[process.platform] || 'default';

function loadEnv() {
  const f = path.join(ROOT, '.env');
  if (!fs.existsSync(f)) return;
  for (const line of fs.readFileSync(f, 'utf8').split('\n')) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
    if (m && !process.env[m[1]]) process.env[m[1]] = m[2].replace(/^['"]|['"]$/g, '');
  }
}
loadEnv();
const key = process.env.GOOGLE_MAPS_API_KEY || '';
if (mode !== 'selftest' && !key) { console.error('GOOGLE_MAPS_API_KEY missing (set it in .env)'); process.exit(2); }

const cam = JSON.parse(fs.readFileSync(path.join(ROOT, 'cam', `${city}.json`), 'utf8'));
const probeFile = path.join(ROOT, 'cam', `${city}_probe.json`);
const probe = fs.existsSync(probeFile) ? JSON.parse(fs.readFileSync(probeFile, 'utf8')) : null;
const h0 = probe ? probe.h0 : cam.ground_h_guess;
const rad = (d) => d * Math.PI / 180;
const H = rad(cam.heading_deg), E = rad(cam.elevation_deg);
const dirs = {
  fwd: [Math.cos(E) * Math.sin(H), Math.cos(E) * Math.cos(H), -Math.sin(E)],
  right: [Math.cos(H), -Math.sin(H), 0],
  up: [Math.sin(E) * Math.sin(H), Math.sin(E) * Math.cos(H), Math.cos(E)],
};

const outDirs = {
  color: path.join(ROOT, 'renders', level, 'raw'),
  height: path.join(ROOT, 'heights', level, 'raw'),
  meta: path.join(ROOT, 'renders', level, 'meta'),
  probe: path.join(ROOT, 'renders', 'probe'),
};
if (mode === 'selftest') Object.assign(outDirs, { color: path.join(ROOT, 'renders', 'selftest'), height: path.join(ROOT, 'renders', 'selftest', 'h') });
for (const d of Object.values(outDirs)) fs.mkdirSync(d, { recursive: true });

let job;
if (mode === 'probe') {
  job = { points: JSON.parse(fs.readFileSync(path.join(ROOT, 'cam', `${city}_probe_points.json`), 'utf8')) };
} else if (mode === 'selftest') {
  job = JSON.parse(fs.readFileSync(path.join(ROOT, 'renders', 'selftest', 'job.json'), 'utf8'));
} else {
  const all = JSON.parse(fs.readFileSync(path.join(ROOT, 'cam', `${city}_${level}_shots.json`), 'utf8'));
  if (Math.abs(all.meta.h0 - h0) > 1e-6) { console.error('shot list h0 differs from probe h0; re-run plan_grid --force'); process.exit(2); }
  let shots = all.shots;
  if (args.only) { const want = new Set(args.only.split(',')); shots = shots.filter((s) => want.has(s.name)); }
  const done = (s) => fs.existsSync(path.join(ROOT, 'renders', level, `${s.name}.jpg`)) || fs.existsSync(path.join(outDirs.color, `${s.name}.png`));
  if (!args.redo) shots = shots.filter((s) => !done(s));
  if (args.limit) shots = shots.slice(0, Number(args.limit));
  job = { shots, ppm: cam.levels[level].ppm };
  console.log(`rendering ${shots.length} shots (${level})`);
}
Object.assign(job, {
  mode, key, anchor: cam.anchor, h0, dirs, render_px: cam.render_px, frame_px: cam.frame_px,
  ppm: job.ppm || cam.levels[level].ppm, error_target: Number(args['error-target'] || 4),
  timeout_ms: Number(args.timeout || 120000),
});

const MIME = { '.js': 'text/javascript', '.mjs': 'text/javascript', '.html': 'text/html', '.json': 'application/json', '.wasm': 'application/wasm' };
const body = (req) => new Promise((res) => { const c = []; req.on('data', (d) => c.push(d)); req.on('end', () => res(Buffer.concat(c))); });
const safe = (n) => String(n).replace(/[^A-Za-z0-9_.-]/g, '_');
let finished;
const done = new Promise((r) => { finished = r; });
let saved = 0;

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://x');
  try {
    if (url.pathname === '/') { res.writeHead(200, { 'content-type': 'text/html' }); return res.end(fs.readFileSync(path.join(ROOT, 'render3d', 'page.html'))); }
    if (url.pathname === '/job') { res.writeHead(200, { 'content-type': 'application/json' }); return res.end(JSON.stringify(job)); }
    if (req.method === 'POST') {
      const data = await body(req);
      const name = safe(url.searchParams.get('name'));
      if (url.pathname === '/log') console.log('[page]', data.toString());
      else if (url.pathname === '/save') {
        const kind = url.searchParams.get('kind');
        const dir = kind.startsWith('probe') ? outDirs.probe : outDirs[kind];
        const suffix = kind === 'probe_h' ? '_h' : '';
        fs.writeFileSync(path.join(dir, `${name}${suffix}.png`), data);
        if (kind === 'color') { saved++; console.log(`saved ${name} (${saved}/${job.shots ? job.shots.length : 1})`); }
      } else if (url.pathname === '/meta') fs.writeFileSync(path.join(outDirs.meta, `${name}.json`), data);
      else if (url.pathname === '/result') fs.writeFileSync(path.join(outDirs.probe, 'result.json'), data);
      else if (url.pathname === '/done') finished();
      res.writeHead(200); return res.end('ok');
    }
    const file = path.join(ROOT, path.normalize(url.pathname));
    if (!file.startsWith(ROOT) || !fs.existsSync(file)) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { 'content-type': MIME[path.extname(file)] || 'application/octet-stream' });
    fs.createReadStream(file).pipe(res);
  } catch (e) { console.error(e); res.writeHead(500); res.end(); }
});

server.listen(0, '127.0.0.1', () => {
  const port = server.address().port;
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'render3d-'));
  const chrome = spawn(CHROME, [
    '--headless=new', `--user-data-dir=${profile}`, '--no-first-run', '--no-default-browser-check',
    `--use-angle=${ANGLE}`, '--enable-gpu', '--ignore-gpu-blocklist', '--enable-webgl',
    '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
    '--window-size=1200,1200', `http://127.0.0.1:${port}/`,
  ], { stdio: ['ignore', 'ignore', args.verbose ? 'inherit' : 'ignore'] });
  let finishing = false;
  done.then(() => { finishing = true; chrome.kill('SIGTERM'); });
  chrome.on('exit', (code) => {
    server.close();
    try { fs.rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }); } catch { /* temp profile */ }
    if (!finishing) { console.error(`chrome exited early (${code})`); process.exit(1); }
    console.log('done');
    process.exit(0);
  });
});
