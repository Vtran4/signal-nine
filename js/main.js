// Signal Nine — main: boot, render loop, dynamic-resolution scaler, bot hooks.
window.S9 = window.S9 || {};
(function () {
  const { clamp } = S9.util;
  const P = S9.CFG.params;

  function boot() {
    window.__boots = (window.__boots || 0) + 1;
    bootAsync().catch((e) => {
      window.__errors.push({ m: 'boot: ' + (e && e.message || e), s: 'main.js', l: 0, c: 0, st: e && e.stack ? String(e.stack).slice(0, 200) : '' });
      document.getElementById('boot').textContent = 'BOOT FAILED — see console';
    });
  }

  function fromB64(name) {
    const A = window.__S9_ASSETS;
    if (!A || !A[name]) return null;
    const bin = atob(A[name].split(',')[1]);
    const buf = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    return buf;
  }

  async function loadTrackData() {
    const buf = fromB64('tracks_data.json');
    if (buf) return JSON.parse(new TextDecoder().decode(buf));
    try {
      const r = await fetch('assets/tracks_data.json');
      if (r.ok) return await r.json();
    } catch (e) { /* file:// without embed — fall back to procedural */ }
    return null;
  }

  function loadGltf(name) {
    return new Promise((res) => {
      const buf = fromB64(name);
      const loader = new THREE.GLTFLoader();
      const done = (g) => res(g || null);
      if (buf) loader.parse(buf.buffer, '', done, () => res(null));
      else loader.load('assets/' + name, done, undefined, () => res(null));
    });
  }

  async function loadEnv() {
    const A = window.__S9_ASSETS;
    const src = (A && A['env_coast.jpg']) ? A['env_coast.jpg'] : 'assets/env_coast.jpg';
    try {
      const tex = await new THREE.TextureLoader().loadAsync(src);
      tex.mapping = THREE.EquirectangularReflectionMapping;
      tex.colorSpace = THREE.SRGBColorSpace;
      return tex;
    } catch (e) { return null; }
  }

  // atlas textures: embedded data URIs (file://) or fetch (localhost).
  // texCounts: bundle hits vs relative-path fallbacks. A fallback hit while
  // the embed bundle exists = bundle/manifest drift — the exact class of bug
  // that white-screened file:// (localhost masked it via the png fallback).
  function makeTexLoader() {
    return (name, srgb) => new Promise((res, rej) => {
      const A = window.__S9_ASSETS;
      const embedded = A && !!A[name];
      const src = embedded ? A[name] : 'assets/' + name;
      const tc = (window.__texCounts = window.__texCounts || { bundle: 0, fallback: 0 });
      if (embedded) tc.bundle++; else tc.fallback++;
      new THREE.TextureLoader().load(src, (t) => {
        if (srgb) t.colorSpace = THREE.SRGBColorSpace;
        t.anisotropy = 8;
        res(t);
      }, undefined, rej);
    });
  }

  async function loadManifest() {
    if (window.__S9_MANIFEST && window.__S9_MANIFEST.atlas_groups) return window.__S9_MANIFEST;
    try {
      const r = await fetch('assets/manifest.json');
      if (r.ok) return await r.json();
    } catch (e) { /* not baked yet */ }
    return null;
  }

  async function bootAsync() {
    const canvas = document.getElementById('c');
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
    const baseDpr = Math.min(devicePixelRatio || 1, 2);
    renderer.setPixelRatio(baseDpr);
    renderer.setSize(innerWidth, innerHeight);
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;

    const scene = new THREE.Scene();
    scene.fog = new THREE.Fog(S9.CFG.palette.fog, 420, 1900);

    const camera = new THREE.PerspectiveCamera(S9.CFG.camera.fov, innerWidth / innerHeight, 0.3, 4200);
    camera.position.set(0, 4, -10);
    scene.add(camera); // camera children (hood anchor) render only if attached

    // sunny West Coast lighting (bakes take over for statics later)
    scene.add(new THREE.HemisphereLight(0xbfe3ff, 0x8a7a55, 0.95));
    const sun = new THREE.DirectionalLight(S9.CFG.palette.sun, 2.2);
    sun.position.set(280, 380, 160);
    scene.add(sun);

    const trackData = await loadTrackData();
    const [tracksGltf, carsGltf, trafficGltf, policeGltf, rivalsGltf, envTex, manifest] = await Promise.all([
      loadGltf('tracks.glb'), loadGltf('cars.glb'), loadGltf('traffic.glb'), loadGltf('police.glb'), loadGltf('rivals.glb'), loadEnv(), loadManifest()]);
    // slot tints for the dressing props (wood crates, metal racks/stacks) —
    // the glb ships them unlit-flat; warm wood + steel reads weathered
    for (const node of trafficGltf.scene.children) node.traverse((o) => {
      const m = o.isMesh && o.material;
      if (!m || !m.name) return;
      if (m.name === 'wood') { m.color.set(0x8a6a42); m.roughness = 0.82; m.metalness = 0.0; }
      if (m.name === 'metal') { m.color.set(0x9aa0a6); m.roughness = 0.38; m.metalness = 0.65; }
    });
    const entry = trackData && trackData.tracks && (trackData.tracks.find(t => t.id === P.track) || trackData.tracks[0]);

    const track = new S9.Track(scene, P.seed, entry || null);
    if (entry && tracksGltf) {
      track.hasGlbStatics = true;
      track.staticRoot = tracksGltf.scene;
      scene.add(tracksGltf.scene);
      track.oncomingEdge = track.laneDodge + 0.3;
      // baked atlases: unlit compose materials per manifest node lists
      if (manifest) {
        S9.applyBakedStatics(tracksGltf.scene, manifest, makeTexLoader())
          .then((n) => { window.__bakeSwap = n; })
          .catch((e) => {
            // TextureLoader rejects with the raw error Event (no .message) —
            // '[object Event]' hid the failed URL; surface the real cause.
            const why = e && e.message ? e.message : (e && e.target && (e.target.src || e.target.url)) || String(e);
            window.__errors.push({ m: 'bake swap: ' + why, s: 'main.js', l: 0, c: 0, st: '' });
          });
        track.collectLodGroups();
        window.__lodGroups = track.lodGroups ? track.lodGroups.length : 0;
      }
    } else if (entry) {
      track.oncomingEdge = track.laneDodge + 0.3;
      track.buildProceduralMeshes(P.seed); // glb missing — greybox under-layer
    } else {
      track.oncomingEdge = -1.2;
    }
    if (envTex) {
      const pmrem = new THREE.PMREMGenerator(renderer);
      scene.environment = pmrem.fromEquirectangular(envTex).texture;
      scene.background = envTex;
      // HDRI pano (kloofendal) is properly exposed — stopgap lift retired
      scene.backgroundIntensity = 1.0;
      if (track.sky) track.sky.visible = false; // pano replaces the gradient dome
    }

    const carCfg = S9.CARS.find(c => c.id === P.car) || S9.CARS[0];
    const car = new S9.Car(track, carCfg);
    scene.add(car.mesh);
    if (car.shadowMesh) scene.add(car.shadowMesh);
    if (carsGltf && carCfg.id !== 'police') {
      const old = car.mesh;
      car.swapMesh(S9.buildCarFromGltf(carsGltf, carCfg.id));
      scene.remove(old);
      scene.add(car.mesh);
      car.isGlb = true;
    } else if (policeGltf && carCfg.id === 'police') {
      const old = car.mesh;
      car.swapMesh(S9.buildCarFromGltf(policeGltf, 'police'));
      scene.remove(old);
      scene.add(car.mesh);
      car.isGlb = true;
    }
    window.__assetFlags = { glbCar: !!car.isGlb, glbTrack: !!track.hasGlbStatics, pano: !!envTex, data: !!entry };

    const traffic = new S9.Traffic(scene, track, P.seed, trafficGltf);
    traffic.debrisRef = null; // set on the game below once the shared list exists
    traffic.spawnInitial(car.s);
    car.track.trafficRef = traffic; // bot lane checks

    const physics = new S9.Physics(scene);
    const speedfx = new S9.SpeedFX(renderer, scene, camera, P.fx);
    const audio = new S9.AudioSet();
    const game = new S9.Game({ scene, camera, renderer, track, car, traffic, physics, speedfx, audio, assets: { carsGltf, trafficGltf, rivalsGltf } });
    traffic.debrisRef = game.debris;   // traffic shatters feed the shared debris engine
    if (P.auto) game.bot = new S9.Bot();

    // state jump from URL (?state=)
    if (P.state) game.modes.jump(P.state);
    else if (!P.auto) game.toAttract();
    else game.startRun();

    // --- ?t=<seconds>: simulate to that time, freeze the frame (verification shots) ---
    if (P.t > 0) {
      const step = 1 / 60;
      for (let sim = 0; sim < P.t; sim += step) game.update(step);
      speedfx.render();
      document.getElementById('boot').style.display = 'none';
      window.__ready = true;
      window.__g = game;   // debug handle: props, scene graph, camera
      window.__state = () => game.state();
      window.__dump = () => game.dumpTraffic();
      window.__closelog = () => game.traffic.closeLog || [];
      return; // frozen — no RAF loop
    }

    // --- dynamic-resolution scaler (pinned by ?lockres for verification shots) ---
    let scale = 1, msEma = 16.6, frames = 0, fpsEma = 60;
    function applyScale() {
      const pr = baseDpr * scale;
      renderer.setPixelRatio(pr);
      renderer.setSize(innerWidth, innerHeight, false);
      speedfx.resize(innerWidth, innerHeight);
    }

    addEventListener('resize', () => {
      camera.aspect = innerWidth / innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(innerWidth, innerHeight);
      speedfx.resize(innerWidth, innerHeight);
    });

    let last = performance.now();
    let lodTick = 0;
    function loop(now) {
      requestAnimationFrame(loop);
      const dtRaw = clamp((now - last) / 1000, 0.001, S9.CFG.physics.dtMax);
      last = now;

      game.update(dtRaw);
      game.updateDebris(dtRaw);
      S9.tickBeacons(dtRaw);            // shared lightbar/flasher clock
      if (track.lodGroups && (++lodTick % 12 === 0)) track.applyLod(camera.position);
      speedfx.render();

      // frame timing + scaler
      const ms = performance.now() - now;
      msEma = msEma * 0.95 + ms * 0.05;
      fpsEma = fpsEma * 0.95 + (1 / dtRaw) * 0.05;
      window.__frameMs = Math.round(msEma * 10) / 10;
      window.__fps = Math.round(fpsEma);
      window.__resScale = Math.round(scale * 100) / 100;  // fps-gate: scaler state
      if (!P.lockres) {
        if (msEma > S9.CFG.fpsGate.msHigh && scale > S9.CFG.fpsGate.scaleMin) { scale = Math.max(S9.CFG.fpsGate.scaleMin, scale - 0.05); applyScale(); }
        else if (msEma < S9.CFG.fpsGate.msLow && scale < S9.CFG.fpsGate.scaleMax) { scale = Math.min(S9.CFG.fpsGate.scaleMax, scale + 0.05); applyScale(); }
      }

      frames++;
      if (!window.__ready && frames > 2) {
        window.__ready = true;
        window.__g = game;   // debug handle: props, scene graph, camera
        document.getElementById('boot').style.display = 'none';
      }
    }
    window.__state = () => game.state();
    window.__dump = () => game.dumpTraffic();
    window.__closelog = () => game.traffic.closeLog || [];
    requestAnimationFrame(loop);
  }

  window.__boot = boot;
  if (document.readyState === 'loading') addEventListener('DOMContentLoaded', boot);
  else boot();
})();