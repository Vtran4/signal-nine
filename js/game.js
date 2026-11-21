// Signal Nine — game: orchestration. Input (keyboard + gamepad), boost events,
// chase camera with pull-back + FOV kick, HUD, persistence, bot hook, __state.
window.S9 = window.S9 || {};
(function () {
  const { clamp, lerp, showEvent, fmtMph } = S9.util;
  const TRACK_DOWN = new THREE.Vector3(0, -1, 0);

  class Game {
    constructor(deps) {
      Object.assign(this, deps); // scene, camera, renderer, track, car, traffic, physics, speedfx, audio
      this.modes = new S9.Modes(this);
      this.mode = 'attract';
      this.paused = false;
      this.bot = null;
      this.boostEase = 0;
      this.keys = {};
      this.gp = { throttle: 0, brake: 0, steer: 0, boost: false, drift: false };
      this.best = this.#loadBest();
      this.#bindInput();
      this.hud = {
        speed: document.getElementById('speed'),
        bar: document.getElementById('boostbar'),
        chain: document.getElementById('chain'),
        bl: document.getElementById('hud-bl'),
        br: document.getElementById('hud-br'),
        menu: document.getElementById('menu'),
        pause: document.getElementById('pause'),
        results: document.getElementById('results'),
        best: document.getElementById('menu-best'),
      };
      document.getElementById('carname').textContent = this.car.cfg.name;
    }

    // ---------- input ----------
    #bindInput() {
      addEventListener('keydown', (e) => {
        if (e.repeat) return;
        this.keys[e.code] = true;
        if (e.code === 'Escape') this.togglePause();
        if (e.code === 'KeyR' && this.mode === 'drive') this.startRun();
      });
      addEventListener('keyup', (e) => { this.keys[e.code] = false; });
      const b = (id, fn) => document.getElementById(id).addEventListener('click', fn);
      b('btn-play', () => this.startRun());
      b('btn-resume', () => this.togglePause());
      b('btn-restart', () => { this.togglePause(); this.startRun(); });
      b('btn-quit', () => { this.togglePause(); this.toAttract(); });
      b('snd', () => {
        const snd = document.getElementById('snd');
        if (!this.audio.on) { this.audio.enable(); snd.textContent = 'Disable sound'; }
        else { this.audio.disable(); snd.textContent = 'Enable sound'; }
      });
      document.getElementById('results').addEventListener('click', () => this.toAttract());
    }

    #pollGamepad() {
      const gps = navigator.getGamepads ? navigator.getGamepads() : [];
      const gp = gps && gps[0];
      this.gp = { throttle: 0, brake: 0, steer: 0, boost: false, drift: false };
      if (!gp) return;
      const dz = (v) => Math.abs(v) > 0.12 ? v : 0;
      this.gp.throttle = gp.buttons[7] ? gp.buttons[7].value : 0;           // RT
      this.gp.brake = gp.buttons[6] ? gp.buttons[6].value : 0;              // LT
      this.gp.steer = dz(gp.axes[0] || 0);
      this.gp.boost = !!(gp.buttons[0] && gp.buttons[0].pressed);           // A
      this.gp.drift = !!(gp.buttons[1] && gp.buttons[1].pressed);           // B
      if (gp.buttons[9] && gp.buttons[9].pressed) this.togglePause();       // Start
    }

    #humanInput() {
      const k = this.keys;
      const throttle = (k['KeyW'] || k['ArrowUp'] ? 1 : 0) || this.gp.throttle;
      const brake = (k['KeyS'] || k['ArrowDown'] ? 1 : 0) || this.gp.brake;
      let steer = 0;
      if (k['KeyA'] || k['ArrowLeft']) steer += 1;
      if (k['KeyD'] || k['ArrowRight']) steer -= 1;
      if (Math.abs(this.gp.steer) > 0.01) steer = -this.gp.steer; // stick right = steer right(-)
      return {
        throttle: clamp(throttle, 0, 1), brake: clamp(brake, 0, 1),
        steer: clamp(steer, -1, 1),
        boost: !!(k['ShiftLeft'] || k['ShiftRight']) || this.gp.boost,
        drift: !!(k['Space']) || this.gp.drift,
      };
    }

    // ---------- flow ----------
    startRun() {
      const car = this.car;
      car.s = 30; car.lateral = this.track.laneOffset; car.speed = 0;
      car.heading = this.track.tangentYawAt(30); car.slip = 0;
      car.boost = { meter: 0, active: false, chain: 0, ease: 0 };
      car.crashed = 0; car.invuln = 0;
      car.stats = { nearMisses: 0, oncomingTime: 0, driftTime: 0, topMph: 0, burnouts: 0, crashes: 0 };
      this.traffic.cars.length = 0;
      this.traffic.spawnInitial(car.s);
      this.runTime = 0;
      this.mode = 'drive';
      this.paused = false;
      this.#snapCamera();
      this.hud.menu.classList.remove('on');
      this.hud.results.classList.remove('on');
      this.hud.pause.classList.remove('on');
      this.hud.bl.style.display = 'block';
      this.hud.br.style.display = 'block';
    }

    toAttract() {
      this.mode = 'attract';
      this.hud.bl.style.display = 'none';
      this.hud.br.style.display = 'none';
      this.hud.results.classList.remove('on');
      this.hud.best.textContent = this.best
        ? `Best today: ${Math.round(this.best.topMph)} mph · ${this.best.burnouts} burnouts`
        : 'No run yet today';
      this.hud.menu.classList.add('on');
    }

    showResults() {
      this.mode = 'results';
      const s = this.car.stats;
      document.getElementById('res-score').textContent = fmtMph(this.car.stats.topMph) + ' MPH';
      document.getElementById('res-detail').textContent =
        `${s.burnouts} burnout${s.burnouts === 1 ? '' : 's'} · ${s.nearMisses} near-miss${s.nearMisses === 1 ? '' : 'es'} · ${Math.round(s.oncomingTime)}s oncoming · ${s.crashes} crash${s.crashes === 1 ? '' : 'es'}`;
      // best-of-day persistence
      const today = new Date().toDateString();
      if (!this.best || this.best.day !== today || s.topMph > this.best.topMph) {
        this.best = { day: today, topMph: s.topMph, burnouts: s.burnouts, nearMisses: s.nearMisses };
        try { localStorage.setItem('s9_best_day', JSON.stringify(this.best)); } catch (e) { /* private mode */ }
      }
      this.hud.bl.style.display = 'none';
      this.hud.br.style.display = 'none';
      this.hud.results.classList.add('on');
    }

    onModeChange(from, to) { this.mode = to; }

    togglePause() {
      if (this.mode !== 'drive') return;
      this.paused = !this.paused;
      this.hud.pause.classList.toggle('on', this.paused);
    }

    // ---------- per-frame ----------
    update(dtRaw) {
      this.#pollGamepad();
      const timeScale = this.physics.tickScale(dtRaw);
      const dt = dtRaw * timeScale;

      if (this.mode === 'drive' && !this.paused) {
        this.runTime += dt;
        const input = this.bot ? this.bot.update(this.car, this.track, dt) : this.#humanInput();
        this.lastInput = { throttle: Math.round(input.throttle * 100) / 100, brake: input.brake, steer: Math.round(input.steer * 100) / 100, boost: input.boost };
        this.lastTarget = this.bot ? this.bot.lastTarget : null;
        if (!this.traffic.onNearMiss) {
          this.traffic.onNearMiss = (rel, heavy) => {
            this.car.nmCalls = (this.car.nmCalls || 0) + 1;
            (this.traffic.closeLog = this.traffic.closeLog || []).push({
              HOOK: 1, carId: this.car._id, crashed: Math.round(this.car.crashed * 100) / 100,
              mph: Math.round(this.car.speed * 2.23694),
            });
            this.car.addNearMiss(heavy);
            this.audio.fire('nearmiss');
            this.physics.slowMo(0.22, 0.4);
            showEvent(heavy ? 'NEAR MISS — HEAVY' : 'NEAR MISS');
          };
        }
        const ev = this.car.update(dt, input);
        this.traffic.update(dt, this.car);
        const hits = this.physics.resolve(this.car, this.traffic, dt);
        for (const h of hits) {
          if (h.type === 'crash') {
            if (this.car.crash()) {
              this.audio.fire('crash');
              this.physics.slowMo(0.7, 0.3);
              showEvent('CRASHED', true);
            }
          } else if (h.type === 'graze') {
            this.audio.fire('wall');
          }
        }
        if (ev === 'nearmiss' || this.traffic.events.some(e => e.type === 'nearmiss')) {
          for (const e of this.traffic.events) if (e.type === 'nearmiss') {
            this.car.addNearMiss(e.heavy);
            this.audio.fire('nearmiss');
            this.physics.slowMo(0.22, 0.4);
            showEvent(e.heavy ? 'NEAR MISS — HEAVY' : 'NEAR MISS');
          }
        }
        if (ev === 'wall') this.audio.fire('wall');
        if (ev === 'boost_start') showEvent('BOOST');
        if (ev === 'burnout') { this.audio.fire('burnout'); showEvent('BURNOUT ×' + (this.car.boost.chain + 1), true); }
        this.#updateCamera(dt);
      } else if (this.mode === 'attract') {
        this.#attractCamera(dtRaw);
      }

      // eased boost intensity drives FOV kick + post + audio
      const bk = this.car.boost.active ? 1 : 0;
      this.boostEase += (bk - this.boostEase) * (bk > this.boostEase ? clamp(dtRaw * 7, 0, 1) : clamp(dtRaw * 2.4, 0, 1));
      const speedNorm = this.car.speed / this.car.cfg.boostTop;
      this.speedfx.update(dtRaw, speedNorm, bk, performance.now() / 1000);
      this.audio.update(dtRaw, {
        speedNorm, throttle: this.mode === 'drive' && !this.paused ? (this.bot ? 1 : this.#humanInput().throttle) : 0,
        boostK: bk, drifting: this.car.drifting,
      });
      this.#updateHud();
    }

    // camera placed instantly (no fly-in) on run start / state jumps
    #snapCamera() {
      const car = this.car, C = S9.CFG.camera;
      const p = car.mesh.position;
      const fwd = new THREE.Vector3(Math.sin(car.heading), 0, Math.cos(car.heading));
      this.camera.position.copy(p).add(fwd.clone().multiplyScalar(-C.chaseDist)).add(new THREE.Vector3(0, C.chaseHeight, 0));
      this.camera.lookAt(p.clone().add(fwd.clone().multiplyScalar(C.lookAhead)).add(new THREE.Vector3(0, 0.8, 0)));
    }

    #updateCamera(dt) {
      const car = this.car, C = S9.CFG.camera;
      const p = car.mesh.position;
      const fwd = new THREE.Vector3(Math.sin(car.heading), 0, Math.cos(car.heading));
      const speedNorm = clamp(car.speed / car.cfg.boostTop, 0, 1);
      const view = S9.CFG.params.view;
      let camPos, look;
      if (view === 'hood' || view === 'bumper') {
        // hood cam rides ABOVE the roof deck (1.22m) — the hood/roof strip
        // ahead fills the frame bottom as a real-geometry mount anchor
        camPos = p.clone().add(fwd.clone().multiplyScalar(view === 'hood' ? 0.3 : 1.1)).add(new THREE.Vector3(0, view === 'hood' ? 1.38 : 0.65, 0));
        look = p.clone().add(fwd.clone().multiplyScalar(view === 'hood' ? 26 : 30)).add(new THREE.Vector3(0, view === 'hood' ? 0.55 : 0.25, 0));
      } else if (view === 'track') {
        // elevated perch ahead of the car — downtown blocks rise above the
        // route, so cast DOWN from above the world and clear the tallest
        // local surface (an up-ray from inside a block can't see that block)
        const perch = this.track.posAt(car.s + 50, 0);
        let py = perch.y + 14; // low perch: city blocks in frame beat ground plane
        if (this.track.staticRoot) {
          this._downRay = this._downRay || new THREE.Raycaster();
          this._downRay.set(new THREE.Vector3(perch.x, 300, perch.z), TRACK_DOWN);
          this._downRay.far = 300;
          const hits = this._downRay.intersectObject(this.track.staticRoot, true);
          if (hits.length) py = Math.max(py, hits[0].point.y + 6);
        }
        camPos = perch.clone();
        camPos.y = py;
        // sight-line guarantee: blocks line every route point, so on curves the
        // straight chord perch->car clips a building — cast car->perch and pull
        // the camera in front of any blocker
        if (this.track.staticRoot) {
          const dir = camPos.clone().sub(p);
          const dist = dir.length();
          dir.normalize();
          this._sightRay = this._sightRay || new THREE.Raycaster();
          this._sightRay.set(p, dir);
          this._sightRay.far = dist;
          const block = this._sightRay.intersectObject(this.track.staticRoot, true);
          if (block.length && block[0].distance < dist) {
            camPos = p.clone().add(dir.multiplyScalar(Math.max(8, block[0].distance - 2)));
          }
        }
        look = p.clone();
      } else { // chase — pull-back with speed
        const dist = C.chaseDist + speedNorm * C.chaseDistSpeed;
        camPos = p.clone().add(fwd.clone().multiplyScalar(-dist)).add(new THREE.Vector3(0, C.chaseHeight, 0));
        look = p.clone().add(fwd.clone().multiplyScalar(C.lookAhead)).add(new THREE.Vector3(0, 0.8, 0));
        if (speedNorm > 0.6) {
          const sh = C.shake * (speedNorm - 0.6) * 3;
          camPos.x += (Math.random() - 0.5) * sh; camPos.y += (Math.random() - 0.5) * sh;
        }
      }
      this.camera.position.lerp(camPos, clamp(dt * 8, 0, 1));
      // rigid mounts (hood/bumper/track) must COPY — lerping a moving mount
      // trails v/8 meters behind and silently becomes a chase view
      if (view !== 'chase') this.camera.position.copy(camPos);
      this.camera.lookAt(look);
      const fov = C.fov + C.fovBoostKick * this.boostEase + speedNorm * 5;
      if (Math.abs(this.camera.fov - fov) > 0.05) { this.camera.fov = fov; this.camera.updateProjectionMatrix(); }
    }

    #attractCamera(dt) {
      const t = performance.now() / 1000;
      const p = this.car.mesh.position;
      this.camera.position.set(p.x + Math.sin(t * 0.22) * 11, p.y + 4.2, p.z + Math.cos(t * 0.22) * 11);
      this.camera.lookAt(p.x, p.y + 0.6, p.z);
      if (Math.abs(this.camera.fov - S9.CFG.camera.fov) > 0.05) {
        this.camera.fov = S9.CFG.camera.fov; this.camera.updateProjectionMatrix();
      }
    }

    #updateHud() {
      if (this.mode !== 'drive') return;
      this.hud.speed.innerHTML = fmtMph(this.car.speed) + '<small>MPH</small>';
      const b = this.car.boost;
      this.hud.bar.style.width = (b.meter * 100).toFixed(1) + '%';
      this.hud.bar.classList.toggle('burn', b.active);
      if (b.chain > 0 && b.active) { this.hud.chain.style.display = 'block'; this.hud.chain.textContent = 'BURNOUT ×' + (b.chain + 1); }
      else this.hud.chain.style.display = 'none';
    }

    // diagnostics: traffic table relative to the player (pw_run debugging)
    dumpTraffic() {
      const L = this.track.length;
      const wrap = (d) => {
        if (!this.track.closed) return d;
        d = d % L; if (d > L / 2) d -= L; if (d < -L / 2) d += L; return d;
      };
      return this.traffic.cars.map(c => ({
        ds: Math.round(wrap(c.s - this.car.s)), lane: c.lane, dir: c.dir,
        mph: Math.round(c.speed * 2.23694), passed: !!c.passed,
      })).sort((a, b) => a.ds - b.ds);
    }

    #loadBest() {
      try {
        const raw = localStorage.getItem('s9_best_day');
        return raw ? JSON.parse(raw) : null;
      } catch (e) { return null; }
    }

    state() {
      return JSON.stringify({
        mode: this.mode,
        speedMph: fmtMph(this.car.speed),
        boost: Math.round(this.car.boost.meter * 100) / 100,
        boostActive: this.car.boost.active,
        chain: this.car.boost.chain,
        stats: this.car.stats,
        dbg: {
          s: Math.round(this.car.s), lateral: Math.round(this.car.lateral * 10) / 10,
          slip: Math.round(this.car.slip * 100) / 100,
          input: this.lastInput, target: this.lastTarget,
          traffic: this.traffic.cars.length,
          fires: this.traffic.fireCount || 0,
          carId: this.car._id, boots: window.__boots || 0,
          nmCalls: this.car.nmCalls || 0, nmSwallowed: this.car.nmSwallowed || 0,
          crashed: Math.round(this.car.crashed * 100) / 100,
          lastReject: this.traffic.lastReject || null,
        },
      });
    }
  }

  S9.Game = Game;
})();