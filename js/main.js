// Signal Nine — main: boot, render loop, dynamic-resolution scaler, bot hooks.
window.S9 = window.S9 || {};
(function () {
  const { clamp } = S9.util;
  const P = S9.CFG.params;

  function boot() {
    const canvas = document.getElementById('c');
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
    const baseDpr = Math.min(devicePixelRatio || 1, 2);
    renderer.setPixelRatio(baseDpr);
    renderer.setSize(innerWidth, innerHeight);
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;

    const scene = new THREE.Scene();
    scene.fog = new THREE.Fog(S9.CFG.palette.fog, 260, 1700);

    const camera = new THREE.PerspectiveCamera(S9.CFG.camera.fov, innerWidth / innerHeight, 0.3, 4200);
    camera.position.set(0, 4, -10);

    // sunny West Coast lighting (bakes take over for statics later)
    scene.add(new THREE.HemisphereLight(0xbfe3ff, 0x8a7a55, 0.95));
    const sun = new THREE.DirectionalLight(S9.CFG.palette.sun, 2.2);
    sun.position.set(280, 380, 160);
    scene.add(sun);

    const track = new S9.Track(scene, P.seed);
    const carCfg = S9.CARS.find(c => c.id === P.car) || S9.CARS[0];
    const car = new S9.Car(track, carCfg);
    scene.add(car.mesh);

    const traffic = new S9.Traffic(scene, track, P.seed);
    traffic.spawnInitial(car.s);
    car.track.trafficRef = traffic; // bot lane checks

    const physics = new S9.Physics(scene);
    const speedfx = new S9.SpeedFX(renderer, scene, camera, P.fx);
    const audio = new S9.AudioSet();
    const game = new S9.Game({ scene, camera, renderer, track, car, traffic, physics, speedfx, audio });
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
      window.__state = () => game.state();
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
    function loop(now) {
      requestAnimationFrame(loop);
      const dtRaw = clamp((now - last) / 1000, 0.001, S9.CFG.physics.dtMax);
      last = now;

      game.update(dtRaw);
      speedfx.render();

      // frame timing + scaler
      const ms = performance.now() - now;
      msEma = msEma * 0.95 + ms * 0.05;
      fpsEma = fpsEma * 0.95 + (1 / dtRaw) * 0.05;
      window.__frameMs = Math.round(msEma * 10) / 10;
      window.__fps = Math.round(fpsEma);
      if (!P.lockres) {
        if (msEma > S9.CFG.fpsGate.msHigh && scale > S9.CFG.fpsGate.scaleMin) { scale = Math.max(S9.CFG.fpsGate.scaleMin, scale - 0.05); applyScale(); }
        else if (msEma < S9.CFG.fpsGate.msLow && scale < S9.CFG.fpsGate.scaleMax) { scale = Math.min(S9.CFG.fpsGate.scaleMax, scale + 0.05); applyScale(); }
      }

      frames++;
      if (!window.__ready && frames > 2) {
        window.__ready = true;
        document.getElementById('boot').style.display = 'none';
      }
    }
    window.__state = () => game.state();
    requestAnimationFrame(loop);
  }

  window.__boot = boot;
  if (document.readyState === 'loading') addEventListener('DOMContentLoaded', boot);
  else boot();
})();