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

  // gt3 livery config (Phase 2.0 WS-A): bundle-first, NEVER a bare relative
  // fetch — file:// has no fetch and the relative-fetch failure class cost us
  // the white-texture round (pm-s9 ruling: consumer + embed land together)
  function loadLiveries() {
    const A = window.__S9_ASSETS;
    if (A && A['gt3_liveries.json']) {
      try { return JSON.parse(new TextDecoder().decode(fromB64('gt3_liveries.json'))); }
      catch (e) { window.__errors.push({ m: 'livery json: ' + (e && e.message || e), s: 'main.js', l: 0, c: 0, st: '' }); return null; }
    }
    try {
      const r = fetch('assets/gt3_liveries.json').then(x => x.ok ? x.json() : null);
      return r;
    } catch (e) { return null; }
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
    // Victor's golden-hour pick (routed via pm-s9): ?env=goldenhour swaps the pano/
    // IBL to the graded candidate; default stays the certified daytime pano.
    const envParam = new URLSearchParams(location.search).get('env');
    const envName = envParam === 'goldenhour' ? 'env_coast_goldenhour.jpg' : 'env_coast.jpg';
    const A = window.__S9_ASSETS;
    const src = (A && A[envName]) ? A[envName] : 'assets/' + envName;
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
        t.flipY = false;   // atlas UVs are glTF-convention (top-left origin);
                           // TextureLoader's default flipY=true mirrored every
                           // atlas row — latent since the first atlas because
                           // pre-repair islands were flip-invariant (black
                           // roads / blown facades / uniform ocean read the
                           // same under either convention). Diagnosed by the
                           // bake-repair round's region fingerprints.
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
    // WS-B1b: per-track rig under ?lit=1 — retune the existing lights + fog +
    // pano intensity (never under the certified compose path)
    const hemi = scene.children.find((o) => o.isHemisphereLight);
    if (P.lit && S9.CFG.lightRigs && S9.CFG.lightRigs[P.track]) {
      const rig = S9.CFG.lightRigs[P.track];
      if (rig) {
        // every field guarded — partial rigs (e.g. coastal fog-trim-only) must
        // leave the certified values for anything they don't set. An unguarded
        // set(undefined) makes the light NaN and NaNs the whole lit frame.
        if (rig.hemiSky !== undefined) hemi.color.set(rig.hemiSky);
        if (rig.hemiGround !== undefined) hemi.groundColor.set(rig.hemiGround);
        if (rig.hemiI !== undefined) hemi.intensity = rig.hemiI;
        if (rig.sunI !== undefined) sun.intensity = rig.sunI;
        if (rig.sunColor !== undefined) sun.color.set(rig.sunColor);
        if (rig.sunPos) sun.position.set(...rig.sunPos);
        if (rig.fog !== undefined) scene.fog.color.set(rig.fog);
        if (rig.fogNear !== undefined) scene.fog.near = rig.fogNear;
        if (rig.fogFar !== undefined) scene.fog.far = rig.fogFar;
        // backgroundIntensity applied after the env loads (below)
        window.__rigBg = rig.bgIntensity;
        if (rig.envIntensity !== undefined) scene.environmentIntensity = rig.envIntensity;
        if (rig.bloomThreshold !== undefined && window.__speedfx && window.__speedfx.bloom)
          window.__speedfx.bloom.threshold = rig.bloomThreshold;
        // B1b2: rig-driven procedural sky swap — the near-white pano dome
        // dominates luminance at any intensity, so night/golden-hour rigs
        // drop the pano background + IBL and re-show the gradient dome
        // (dome sits at the track centroid, rider from the layout round)
        if (rig.useProceduralSky) {
          window.__rigSky = { top: rig.skyTop, low: rig.skyLow, envI: rig.envI };
        }
        if (rig.emissiveI !== undefined) window.__rigEmissive = rig.emissiveI;  // WS-B1c
        if (rig.neonI !== undefined) window.__rigNeon = rig.neonI;  // WS-B2 neon signs
      }
    }

    const trackData = await loadTrackData();
    const [tracksGltf, carsGltf, trafficGltf, policeGltf, rivalsGltf, envTex, manifest, gt3Gltf, liveries] = await Promise.all([
      loadGltf('tracks.glb'), loadGltf('cars.glb'), loadGltf('traffic.glb'), loadGltf('police.glb'), loadGltf('rivals.glb'), loadEnv(), loadManifest(), loadGltf('gt3.glb'), loadLiveries()]);
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
      // (?lit=1 flips to the Phase 2.0 lit PBR + AO-overlay path)
      // Golden-hour light pairing (Victor's pick): ?env=goldenhour swaps each group's
      // LIGHT atlas to the warm-baked set via manifest_golden.json (bundle-embedded).
      // Extension-agnostic off the manifest: the loader resolves whatever filename the
      // golden manifest states (png masters / modeler's jpg converts) bundle-first.
      if (manifest && new URLSearchParams(location.search).get('env') === 'goldenhour'
          && window.__S9_ASSETS && window.__S9_ASSETS['manifest_golden.json']) {
        window.__certifiedLights = {};
        window.__certifiedAlbedos = {};
        for (const g in manifest.atlas_groups || {}) {
          window.__certifiedLights[g] = manifest.atlas_groups[g].light;
          window.__certifiedAlbedos[g] = manifest.atlas_groups[g].albedo;
        }
        try {
          const gj = JSON.parse(atob(window.__S9_ASSETS['manifest_golden.json'].split(',')[1] || '')
            .split('').map(c => String.fromCharCode(c.charCodeAt(0))).join(''));
          for (const g in gj.atlas_groups || {}) {
            if (manifest.atlas_groups[g] && gj.atlas_groups[g].light)
              manifest.atlas_groups[g].light = gj.atlas_groups[g].light;
            // round-2 warm grade: the golden ALBEDO rides the same overlay (cool
            // daytime albedo cancels the warm baked light on road/ocean — pm's
            // re-look diagnosis; modeler's manifest carries both keys)
            if (manifest.atlas_groups[g] && gj.atlas_groups[g].albedo)
              manifest.atlas_groups[g].albedo = gj.atlas_groups[g].albedo;
          }
          window.__lightSet = 'golden';
        } catch (e) { window.__errors.push({ m: 'golden manifest: ' + (e && e.message || e), s: 'main.js', l: 0, c: 0, st: '' }); }
      }
      if (manifest) {
        S9.applyBakedStatics(tracksGltf.scene, manifest, makeTexLoader(), !!P.lit)
          .then((n) => {
            window.__bakeSwap = n;
            // WS-B1d: downtown wet-road mirror — clone the road's material with
            // the reflection injection, build the MirrorPass on the road plane,
            // and let speedfx render it each frame before the composer.
            if (P.lit && P.track === 'downtown' && S9.MirrorPass) {
              let road = null;
              tracksGltf.scene.traverse((o) => {
                if (o.isMesh && o.name === 'downtown_road') road = o;
              });
              if (road) {
                const box = new THREE.Box3().setFromObject(road);
                const planeY = box.min.y + 0.02;         // road surface plane
                const mirror = new S9.MirrorPass(renderer, scene, camera, road, planeY);
                const roadMat = road.material.clone();
                roadMat.onBeforeCompile = (shader) => {
                  shader.uniforms.tMirror = { value: mirror.rt.texture };
                  shader.uniforms.uMirrorMat = { value: mirror.textureMatrix };
                  shader.uniforms.uWet = { value: 0.55 };  // B1f: 0.42 read weak in chase framing
                  shader.vertexShader = shader.vertexShader
                    .replace('#include <common>',
                      '#include <common>\nvarying vec4 vMirrorUv;\nuniform mat4 uMirrorMat;')
                    .replace('#include <fog_vertex>',
                      '#include <fog_vertex>\nvec4 mwp = modelMatrix * vec4(transformed, 1.0);\nvMirrorUv = uMirrorMat * mwp;');
                  shader.fragmentShader = shader.fragmentShader
                    .replace('#include <common>',
                      '#include <common>\nvarying vec4 vMirrorUv;\nuniform sampler2D tMirror;\nuniform float uWet;')
                    .replace('#include <fog_fragment>',
                      // B1f: 2-tap vertical smear — wet asphalt, not a perfect mirror
                      'vec4 mreflUv2 = vMirrorUv + vec4(0.0, 0.012, 0.0, 0.0);\n' +
                      'vec3 mrefl = texture2DProj(tMirror, vMirrorUv).rgb * 0.6 +\n' +
                      '            texture2DProj(tMirror, mreflUv2).rgb * 0.4;\n' +
                      'gl_FragColor.rgb = mix(gl_FragColor.rgb, mrefl, uWet);\n' +
                      '#include <fog_fragment>');
                };
                roadMat.needsUpdate = true;
                road.material = roadMat;
                roadMirror = mirror;
                speedfx.mirror = mirror;
                window.__mirror = true;
              } else {
                window.__errors.push({ m: 'B1d: downtown_road mesh not found for mirror', s: 'main.js', l: 0, c: 0, st: '' });
              }
            }
          })
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
      if (window.__rigBg !== undefined) scene.backgroundIntensity = window.__rigBg;  // WS-B1b rig
      if (track.sky) track.sky.visible = false; // pano replaces the gradient dome
      // B1b2: night/golden-hour rigs re-show the procedural gradient dome with
      // rig colors and drop the pano background + daytime IBL (the dome rides
      // at the track centroid; fog color already carries the rig mood)
      if (window.__rigSky && track.sky) {
        scene.background = null;
        const uni = track.sky.material.uniforms;
        uni.top.value.set(window.__rigSky.top);
        uni.low.value.set(window.__rigSky.low);
        track.sky.visible = true;
        scene.environmentIntensity = window.__rigSky.envI;   // night: ~no daylight bounce
      }
    }

    const carCfg = S9.CARS.find(c => c.id === P.car) || S9.CARS[0];
    const car = new S9.Car(track, carCfg);
    scene.add(car.mesh);
    if (car.shadowMesh) scene.add(car.shadowMesh);
    if (gt3Gltf && carCfg.id === 'gt3') {
      const old = car.mesh;
      car.swapMesh(S9.buildCarFromGltf(gt3Gltf, 'gt3'));
      // P1 respawn fix: remember the build source — the shatter-rebuild closure
      // defaulted to carsGltf, which has NO gt3 body, so respawn swapped the
      // full gt3 mesh for an empty shell (children 45 -> 0, blob shadow only).
      car.buildSource = { gltf: gt3Gltf, tok: 'gt3' };
      scene.remove(old);
      scene.add(car.mesh);
      car.isGlb = true;
      // WS-Q hi-res wiring: the 2048^2 gt3 albedo + AO ride the bundle; paint regions
      // bake NEUTRAL WHITE so the per-variant color multiplies on top (modeler's
      // albedo contract). aoMap rides the shared UV set (channel 0).
      const gt3Maps = window.__S9_ASSETS || {};
      if (gt3Maps['alb_gt3.png'] && gt3Maps['ao_gt3.png']) {
        const mkTex = (key, srgb) => {
          const t = new THREE.TextureLoader().load(gt3Maps[key]);
          t.flipY = false;              // glTF UV convention (the atlas rule)
          if (srgb) t.colorSpace = THREE.SRGBColorSpace;
          return t;
        };
        const alb = mkTex('alb_gt3.png', true);
        const ao = mkTex('ao_gt3.png', false);
        ao.channel = 0;
        car.mesh.traverse((o) => {
          if (o.isMesh && o.material && (o.material.name === 'paint_gt3' ||
              /carbon|tire|rim|glass_gt3/.test(o.material.name || ''))) {
            if (!o.material.map) o.material.map = alb;          // true-color accents + white paint regions
            if (!o.material.aoMap) { o.material.aoMap = ao; o.material.aoMapIntensity = 0.9; }
            o.material.needsUpdate = true;   // map slot added pre-first-render? assign before add — needsUpdate safe
          }
        });
      }
      // WS-A livery consumer: swap paint_gt3 parameters off the visual-only
      // livery JSON (schema 1: paint base/flake per variant; defaults carry
      // metallic/roughness/clearcoat). Variant = ?livery=<id> or default v1.
      if (liveries && liveries.variants) {
        const q = new URLSearchParams(location.search);
        const want = q.get('livery');
        const v = liveries.variants.find(x => x.id === want) || liveries.variants[0];
        const d = liveries.defaults || {};
        car.mesh.traverse((o) => {
          if (o.isMesh && o.material && o.material.name === 'paint_gt3') {
            const p = Object.assign({}, d, v.paint || {});
            if (p.base) o.material.color = new THREE.Color(p.base);
            if (p.flake !== undefined) o.material.metalness = 0.45 + (p.flake - 0.35) * 0.5;
            if (p.roughness !== undefined) o.material.roughness = p.roughness;
            o.material.name = 'paint_gt3';
          }
        });
        window.__livery = v.id;
        window.__liveryName = v.name;    // WS-Q stat flavor: results/menu surface
        window.__liveryUi = v.ui;        // the variant's display name + UI color
      }
    } else if (carsGltf && carCfg.id !== 'police') {
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

    // WS-B1d: downtown wet-road planar mirror — ?lit=1 + downtown only. The
    // road material gets the reflection injected via onBeforeCompile AFTER the
    // bake swap resolves (the swap replaces materials), and the mirror render
    // hooks the per-frame loop through speedfx.mirror.
    let roadMirror = null;
    if (P.lit && P.track === 'downtown' && tracksGltf) {
      const bakeSwapDone = window.__bakeSwap > 0 || true;   // swap is async; inject in its .then below
      S9._mirrorHook = { scene, renderer, camera };
    }

    const traffic = new S9.Traffic(scene, track, P.seed, trafficGltf);
    traffic.debrisRef = null; // set on the game below once the shared list exists
    traffic.spawnInitial(car.s);
    car.track.trafficRef = traffic; // bot lane checks

    const physics = new S9.Physics(scene);
    const speedfx = new S9.SpeedFX(renderer, scene, camera, P.fx, P.lit);
    window.__speedfx = speedfx;  // rig access (bloomThreshold)
    // the rig block runs before this construction — apply the rig's bloom threshold here
    const rigNow = S9.CFG.lightRigs && S9.CFG.lightRigs[P.track];
    if (P.lit && speedfx.bloom && rigNow && rigNow.bloomThreshold !== undefined)
      speedfx.bloom.threshold = rigNow.bloomThreshold;
    if (P.lit && speedfx.bloom && rigNow && rigNow.bloomStrength !== undefined)
      speedfx.bloom.strength = rigNow.bloomStrength;
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
      if (speedfx.mirror) speedfx.mirror.resize(innerWidth, innerHeight);  // WS-B1d
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
      if (speedfx.mirror) speedfx.mirror.render();   // WS-B1d: reflection RT first
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