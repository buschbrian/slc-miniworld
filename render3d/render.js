// Runs inside headless Chrome. Fetches a job from server.mjs, renders each shot with one fixed
// orthographic camera, and posts colour and height images back. ENU (e, n, u) maps to three.js
// as (-x, y, z) because ReorientationPlugin puts +Y up, +Z north, +X west.
import * as THREE from 'three';
import { TilesRenderer } from '3d-tiles-renderer';
import { GoogleCloudAuthPlugin, ReorientationPlugin } from '3d-tiles-renderer/plugins';

const log = (msg) => fetch('/log', { method: 'POST', body: String(msg) });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const v3 = (p) => new THREE.Vector3(-p[0], p[2], p[1]);

const HEIGHT_BASE = -300.0; // metres relative to h0; 16-bit at 4 cm covers -300 .. +2321 m

async function main() {
  const job = await (await fetch('/job')).json();
  const size = job.render_px;
  const renderer = new THREE.WebGLRenderer({ antialias: false, preserveDrawingBuffer: true });
  renderer.setPixelRatio(1);
  renderer.setSize(size, size);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.NoToneMapping;
  document.body.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.add(new THREE.AmbientLight(0xffffff, 3));
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 1, 20000);
  const tiles = new TilesRenderer();
  if (job.mode !== 'selftest') {
    tiles.registerPlugin(new GoogleCloudAuthPlugin({ apiToken: job.key, autoRefreshToken: true }));
    tiles.registerPlugin(new ReorientationPlugin({
      lat: job.anchor.lat * Math.PI / 180, lon: job.anchor.lon * Math.PI / 180, height: job.h0, recenter: true,
    }));
    tiles.errorTarget = job.error_target;
    tiles.lruCache.maxBytesSize = 1.5e9;
    tiles.lruCache.minBytesSize = 0.8e9;
    scene.add(tiles.group);
    tiles.setCamera(camera);
    tiles.setResolutionFromRenderer(camera, renderer);
  }

  const heightMat = new THREE.ShaderMaterial({
    side: THREE.DoubleSide,
    uniforms: { base: { value: HEIGHT_BASE } },
    vertexShader: `varying float vH;
      void main(){ vec4 wp = modelMatrix * vec4(position, 1.0); vH = wp.y; gl_Position = projectionMatrix * viewMatrix * wp; }`,
    fragmentShader: `precision highp float; uniform float base; varying float vH;
      void main(){ float v = clamp(floor((vH - base) / 0.04 + 0.5), 0.0, 65535.0);
        float hi = floor(v / 256.0); float lo = v - hi * 256.0;
        gl_FragColor = vec4(hi / 255.0, lo / 255.0, 1.0, 1.0); }`,
  });

  function setView(dirs, target, widthM) {
    const f = v3(dirs.fwd), up = v3(dirs.up), right = v3(dirs.right);
    // Slide the target along the view ray to ground level: same orthographic image, but the
    // ground stays inside near/far even for squares kilometres from the anchor.
    const t = v3(target);
    if (Math.abs(f.y) > 1e-6) t.addScaledVector(f, -t.y / f.y);
    camera.position.copy(t).addScaledVector(f, -8000);
    camera.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(right, up, f.clone().negate()));
    const h = widthM / 2;
    Object.assign(camera, { left: -h, right: h, top: h, bottom: -h });
    camera.updateProjectionMatrix();
    camera.updateMatrixWorld(true);
  }

  async function settle(timeoutMs) {
    const t0 = performance.now();
    let stable = 0;
    while (performance.now() - t0 < timeoutMs) {
      tiles.update();
      renderer.render(scene, camera);
      const s = tiles.stats;
      const busy = s.queued + s.downloading + s.parsing + (tiles.isLoading ? 1 : 0);
      stable = busy === 0 && tiles.root ? stable + 1 : 0;
      if (stable >= 12) return true;
      await sleep(25);
    }
    return false;
  }

  async function post(url, blob) {
    const r = await fetch(url, { method: 'POST', body: blob });
    if (!r.ok) throw new Error(`save failed ${url}`);
  }
  const canvasBlob = (type, q) => new Promise((res) => renderer.domElement.toBlob(res, type, q));

  async function renderColor() {
    scene.overrideMaterial = null;
    renderer.setClearColor(0x000000, 1);
    renderer.render(scene, camera);
    return canvasBlob('image/png');
  }
  async function renderHeight() {
    scene.overrideMaterial = heightMat;
    renderer.setClearColor(0x000000, 1);
    renderer.render(scene, camera);
    const blob = await canvasBlob('image/png');
    scene.overrideMaterial = null;
    return blob;
  }

  function raycastDown(enuPoint) {
    const p = v3([enuPoint[0], enuPoint[1], 3000]);
    const rc = new THREE.Raycaster(p, new THREE.Vector3(0, -1, 0), 0, 10000);
    const hit = rc.intersectObject(tiles.group, true)[0];
    return hit ? hit.point.y : null;
  }

  if (job.mode === 'selftest') {
    // 10 m cubes at known ENU points; check_selftest.py compares their centroids with geo.py.
    const colors = [0xff0000, 0x00ff00, 0x0000ff, 0xffff00, 0xff00ff];
    job.points.forEach((pt, i) => {
      const m = new THREE.Mesh(new THREE.BoxGeometry(10, 10, 10), new THREE.MeshBasicMaterial({ color: colors[i % colors.length] }));
      m.position.copy(v3(pt.enu));
      scene.add(m);
    });
    const shot = job.shots[0];
    setView(job.dirs, shot.target_enu, job.frame_px / job.ppm);
    await post(`/save?kind=color&name=${shot.name}`, await renderColor());
    await post(`/save?kind=height&name=${shot.name}`, await renderHeight());
  } else if (job.mode === 'probe') {
    const results = [];
    const down = { fwd: [0, 0, -1], up: [0, 1, 0], right: [1, 0, 0] };
    for (const pt of job.points) {
      setView(down, [pt.enu[0], pt.enu[1], 0], pt.width_m);
      const ok = await settle(job.timeout_ms);
      const h = raycastDown(pt.enu);
      const attributions = tiles.getAttributions().map((a) => a.value).filter((v) => typeof v === 'string');
      await post(`/save?kind=probe&name=${encodeURIComponent(pt.name)}`, await renderColor());
      await post(`/save?kind=probe_h&name=${encodeURIComponent(pt.name)}`, await renderHeight());
      results.push({ name: pt.name, loaded: ok, hit_rel: h, attributions });
      await log(`probe ${pt.name} loaded=${ok} hit=${h}`);
    }
    await fetch('/result', { method: 'POST', body: JSON.stringify(results) });
  } else {
    const width = job.frame_px / job.ppm;
    for (const shot of job.shots) {
      setView(job.dirs, shot.target_enu, width);
      const t0 = performance.now();
      const ok = await settle(job.timeout_ms);
      if (!ok) { await log(`TIMEOUT ${shot.name}`); continue; }
      await post(`/save?kind=color&name=${shot.name}`, await renderColor());
      await post(`/save?kind=height&name=${shot.name}`, await renderHeight());
      const attributions = tiles.getAttributions().map((a) => a.value).filter((v) => typeof v === 'string');
      await fetch(`/meta?name=${shot.name}`, { method: 'POST', body: JSON.stringify({ attributions, ms: Math.round(performance.now() - t0) }) });
    }
  }
  await fetch('/done', { method: 'POST' });
}

main().catch(async (e) => { await log(`ERROR ${e && e.stack || e}`); await fetch('/done', { method: 'POST' }); });
