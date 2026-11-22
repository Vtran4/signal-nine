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
      this.raceScore = 0;
      this.driveLap = 0;      // free-drive lap counter (resets on run start)
      this.keys = {};
      this.gp = { throttle: 0, brake: 0, steer: 0, boost: false, drift: false };
      this.best = this.#loadBest();
      this.#bindInput();
      this.hud = {
        bar: document.getElementById('boostbar'),
        chain: document.getElementById('chain'),
        bl: document.getElementById('hud-bl'),
        br: document.getElementById('hud-br'),
        raceinfo: document.getElementById('raceinfo'),
        menu: document.getElementById('menu'),
        pause: document.getElementById('pause'),
        results: document.getElementById('results'),
        best: document.getElementById('menu-best'),
        // B3 corner capsules
        capPos: document.getElementById('cap-pos'),
        capScore: document.getElementById('cap-score'),
        capLap: document.getElementById('cap-lap'),
        capBoost: document.getElementById('cap-boost'),
        capSpeed: document.getElementById('cap-speed'),
        posBig: document.getElementById('pos-big'),
        posOf: document.getElementById('pos-of'),
        scoreBig: document.getElementById('score-big'),
        lapBig: document.getElementById('lap-big'),
        mult: document.getElementById('mult'),
        speedBig: document.getElementById('speed-big'),
        chipOncoming: document.getElementById('chip-oncoming'),
        chipDrift: document.getElementById('chip-drift'),
      };
      document.getElementById('carname').textContent = this.car.cfg.name;
    }

    // ---------- input ----------
    #bindInput() {
      addEventListener('keydown', (e) => {
        if (e.repeat) return;
        this.keys[e.code] = true;
        if (e.code === 'Escape') this.togglePause();
        if (e.code === 'KeyR') {
          if (this.mode === 'race') this.startRace();
          else if (this.mode === 'crash') this.startCrash(this.crash.idx);
          else this.startRun();
        }
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
      this.cleanupRace();
      this.driveLap = 0; this.drivePrevS = undefined;
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
      this.#showCapsules();
    }

    startRace() {
      this.cleanupRace();
      const car = this.car;
      car.s = 30; car.lateral = 1.8; car.speed = 0;
      car.heading = this.track.tangentYawAt(30); car.slip = 0;
      car.boost = { meter: 0, active: false, chain: 0, ease: 0 };
      car.crashed = 0; car.invuln = 0;
      car.stats = { nearMisses: 0, oncomingTime: 0, driftTime: 0, topMph: 0, burnouts: 0, crashes: 0 };
      this.traffic.cars.length = 0;
      this.traffic.spawnInitial(car.s);
      this.runTime = 0;
      this.mode = 'race';
      this.paused = false;
      this.race = new S9.Race(this, this.track.closed ? 2 : 1);  // B3 default: 2-lap circuits
      // rivals in their own glbs: first three from cars.glb, new pair from rivals.glb
      if (this.assets && this.assets.carsGltf) {
        for (let i = 0; i < this.race.rivals.length; i++) {
          const r = this.race.rivals[i];
          const spec = S9.RACE_RIVALS[i];
          const src = spec.tok === 'warhawk' || spec.tok === 'halberd' ? this.assets.rivalsGltf : this.assets.carsGltf;
          if (!src) continue;
          const old = r.mesh;
          r.swapMesh(S9.buildCarFromGltf(src, spec.tok, spec.paint));
          this.scene.remove(old);
          this.scene.add(r.mesh);
        }
      }
      this.#snapCamera();
      this.hud.menu.classList.remove('on');
      this.hud.results.classList.remove('on');
      this.hud.pause.classList.remove('on');
      this.#showCapsules();
    }

    cleanupRace() {
      if (this.bot) this.bot.crashHold = undefined;
      if (this.race) { this.race.dispose(); this.race = null; }
      if (this.crash) { this.crash.dispose(); this.crash = null; }
      if (this.crashLight) { this.scene.remove(this.crashLight, this.crashLight.target); this.crashLight = null; }
      this.takedowns = 0;
    }

    // B3 takedown: a rival crashing within 2s of player contact. Signature
    // (shoved into the wall / into traffic) pays double.
    awardTakedown(rival, signature) {
      this.takedowns = (this.takedowns || 0) + 1;
      const pts = signature ? 2000 : 1000;
      if (this.race) this.race.score += pts;
      S9.util.showEvent((signature ? 'SIGNATURE TAKEDOWN ' : 'TAKEDOWN ') + pts, true);
      this.audio.fire('crash');
    }

    toAttract() {
      this.cleanupRace();
      this.#hideCapsules();
      this.hud.results.classList.remove('on');
      this.hud.best.textContent = this.best
        ? `Best today: ${Math.round(this.best.topMph)} mph · ${this.best.burnouts} burnouts`
        : 'No run yet today';
      this.hud.menu.classList.add('on');
    }

    startCrash(idx) {
      this.cleanupRace();
      const car = this.car;
      this.traffic.cars.length = 0;   // junction stage is the only traffic
      this.runTime = 0;
      this.mode = 'crash';
      this.paused = false;
      this.crash = new S9.Crash(this, idx);
      this.#snapCamera();
      this.hud.menu.classList.remove('on');
      this.hud.results.classList.remove('on');
      this.hud.pause.classList.remove('on');
      this.#showCapsules();
      if (this.hud.raceinfo) this.hud.raceinfo.textContent = '';
    }

    showCrashResults(idx, total) {
      this.mode = 'results';
      // helicopter spotlight: downtown's dusk IBL can't light the wreck
      // field — one pooled spot over the junction is the crash-mode payoff rig
      if (this.crash && this.crash.junction && !this.crashLight) {
        const c = this.track.posAt(this.crash.junction.s, 0);
        const spot = new THREE.SpotLight(0xfff2dd, 2600, 140, 0.55, 0.55, 1.6);
        spot.position.set(c.x + 8, c.y + 14, c.z + 6);
        spot.target.position.copy(c);
        this.scene.add(spot, spot.target);
        this.crashLight = spot;
      }
      const bestKey = 's9_crash_best';
      let best = 0;
      try {
        const raw = localStorage.getItem(bestKey);
        const all = raw ? JSON.parse(raw) : {};
        best = all[idx] || 0;
        if (total > best) { all[idx] = total; localStorage.setItem(bestKey, JSON.stringify(all)); best = total; }
      } catch (e) { /* private mode */ }
      document.getElementById('res-title').textContent = 'CRASH JUNCTION ' + (idx + 1);
      document.getElementById('res-score').textContent = S9.util.fmtDollars(total);
      document.getElementById('res-detail').textContent =
        total >= best && total > 0 ? 'NEW JUNCTION RECORD' : 'junction best: ' + S9.util.fmtDollars(best);
      this.#hideCapsules();
      this.hud.results.classList.add('on');
    }

    showRaceResults(pos, medal) {
      // position + medal results, best-medal persistence per track
      const ord = ['1ST', '2ND', '3RD', '4TH'][clamp(pos - 1, 0, 3)];
      this.mode = 'results';
      const s = this.car.stats;
      document.getElementById('res-title').textContent = medal === '4TH' ? 'RACE COMPLETE' : medal + ' MEDAL';
      document.getElementById('res-score').textContent = ord;
      document.getElementById('res-detail').textContent =
        `${s.burnouts} burnout${s.burnouts === 1 ? '' : 's'} · ${s.nearMisses} near-miss${s.nearMisses === 1 ? '' : 'es'} · ${Math.round(s.oncomingTime)}s oncoming · ${s.crashes} crash${s.crashes === 1 ? '' : 'es'}`;
      const rank = clamp(pos, 1, 4);
      try {
        const raw = localStorage.getItem('s9_medals');
        const medals = raw ? JSON.parse(raw) : {};
        if (!medals[this.track.id] || rank < medals[this.track.id]) medals[this.track.id] = rank;
        localStorage.setItem('s9_medals', JSON.stringify(medals));
      } catch (e) { /* private mode */ }
      this.#hideCapsules();
      this.hud.results.classList.add('on');
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
      this.#hideCapsules();
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

      if ((this.mode === 'drive' || this.mode === 'race') && !this.paused) {
        if (this.race) this.race.update(dt);
        const frozen = this.race && this.race.state === 'countdown';
        if (!frozen) {
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
          if (this.race) {
            const rhits = this.physics.resolveRivals(this.car, this.race.rivals, dt, this.runTime);
            for (const h of rhits) if (h.type === 'graze') this.audio.fire('wall');
            for (const r of this.race.rivals) {
              this.physics.resolveRivalWorld(r, dt, this.runTime);  // rival wall/traffic crashes
              const rin = r.bot.update(r, this.track, dt);
              r.update(dt, rin);
            }
          }
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
          if (ev === 'wall') this.audio.fire('wall');
          if (ev === 'boost_start') showEvent('BOOST');
          if (ev === 'burnout') { this.audio.fire('burnout'); showEvent('BURNOUT ×' + (this.car.boost.chain + 1), true); }
          this.#updateCamera(dt);
        } else {
          this.#updateCamera(dt);
        }
      } else if (this.mode === 'crash' && !this.paused) {
        this.runTime += dt;
        // bot: locked-lane launch via its stable curvature-FF controller;
        // humans steer their own launch — that's the skill
        let input;
        if (this.bot) {
          this.bot.crashHold = this.crash.launchLat;
          input = this.bot.update(this.car, this.track, dt);
        } else {
          input = this.#humanInput();
        }
        this.car.update(dt, input);
        if (this.crash) this.crash.update(dt);
        this.#updateCamera(dt);
      } else if (this.mode === 'results' && this.crash) {
        // elevated establishing shot of the junction behind the results
        // panel — the pileup IS the payoff shot
        const ip = this.#crashCamPos();
        // street-level orbit: downtown buildings occlude any high-angle view of
              // the road corridor — 3m height looks ALONG the street where wrecks sit
              if (ip) {
                const t = performance.now() / 1000;
                this.camera.position.set(ip.x + Math.sin(t * 0.25) * 15, ip.y + 3.0, ip.z + Math.cos(t * 0.25) * 15);
                this.camera.lookAt(ip.x, ip.y + 1.1, ip.z);
              }
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

    #crashCamPos() {
      // orbit center: the MIDPOINT of the wrecked car and the junction —
      // the wreck field fans between them, so both frame together
      if (this.crash && this.crash.junction && this.car && this.car.mesh) {
        const jc = this.track.posAt(this.crash.junction.s, 0);
        return jc.add(this.car.mesh.position).multiplyScalar(0.5);
      }
      return null;
    }

    #updateCamera(dt) {
      // crash cinematic: slow orbit around the pileup
      if (this.mode === 'crash' && this.crash && this.crash.cine > 0) {
        const ip = this.#crashCamPos();
        if (!ip) return;
        const t = performance.now() / 1000;
        this.camera.position.set(ip.x + Math.sin(t * 0.55) * 13, ip.y + 5.5, ip.z + Math.cos(t * 0.55) * 13);
        this.camera.lookAt(ip.x, ip.y + 0.9, ip.z);
        return;
      }
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
      this.camera.position.set(p.x + Math.sin(t * 0.22) * 13, p.y + 5.4, p.z + Math.cos(t * 0.22) * 13);
      this.camera.lookAt(p.x, p.y + 0.6, p.z);
      if (Math.abs(this.camera.fov - S9.CFG.camera.fov) > 0.05) {
        this.camera.fov = S9.CFG.camera.fov; this.camera.updateProjectionMatrix();
      }
    }


    #showCapsules() {
      for (const id of ['capPos', 'capScore', 'capLap', 'capBoost', 'capSpeed']) this.hud[id].style.display = 'block';
    }
    #hideCapsules() {
      for (const id of ['capPos', 'capScore', 'capLap', 'capBoost', 'capSpeed']) this.hud[id].style.display = 'none';
    }
    #updateHud() {
      if (this.mode !== 'drive' && this.mode !== 'race') return;
      const inRace = this.mode === 'race' && this.race;
      const r = inRace ? this.race : null;
      // corner capsules: SPEED+BOOST always; SCORE+LAP in every driving mode
      // (B3 shows them everywhere — free drive gets a live score and lap
      // count too); POS needs a field, so it is race-only
      const showPos = !!r;
      const showLap = this.track.closed;
      this.hud.capPos.style.display = showPos ? 'block' : 'none';
      this.hud.capScore.style.display = 'block';
      this.hud.capLap.style.display = showLap ? 'block' : 'none';
      this.hud.capBoost.style.display = 'block';
      this.hud.capSpeed.style.display = 'block';
      // speed block
      this.hud.speedBig.innerHTML = fmtMph(this.car.speed) + '<small> MPH</small>';
      // boost meter + multiplier (chain +1 per burnout in the current chain)
      const b = this.car.boost;
      this.hud.bar.style.width = (b.meter * 100).toFixed(1) + '%';
      this.hud.bar.classList.toggle('burn', b.active);
      this.hud.mult.textContent = '×' + Math.max(1, b.active ? b.chain + 1 : 1);
      // earn-source chips: lit while that earn channel is paying out
      this.hud.chipOncoming.classList.toggle('on',
        this.car.lateral < (this.track.oncomingEdge !== undefined ? this.track.oncomingEdge : -1.2) && this.car.speed > 12 && !this.car.crashed);
      this.hud.chipDrift.classList.toggle('on', this.car.drifting && this.car.speed > S9.CFG.boost.driftMinSpeed);
      // score: race = full economy incl. takedowns; free drive = the same
      // near-miss/drift/oncoming economy so the capsule is never dead
      const st = this.car.stats;
      if (r) {
        this.hud.posBig.innerHTML = (r.state === 'countdown' ? '–' : r.playerPos) + '<small id="pos-of">/' + (r.rivals.length + 1) + '</small>';
        this.hud.scoreBig.textContent = Math.round(r.score || 0);
      } else {
        this.hud.scoreBig.textContent = Math.round(st.nearMisses * 150 + st.driftTime * 50 + st.oncomingTime * 25);
      }
      // lap counting: race uses the Race controller; free drive counts wraps
      if (showLap) {
        let lapNow;
        if (r) lapNow = Math.min(r.laps, r.lapCount[0] + 1);
        else {
          lapNow = this.driveLap + 1;
          if (this.drivePrevS === undefined) this.drivePrevS = this.car.s;
          const L = this.track.length;
          if (this.drivePrevS - this.car.s > L * 0.5) this.driveLap++;
          this.drivePrevS = this.car.s;
          lapNow = Math.min(2, this.driveLap + 1);
        }
        this.hud.lapBig.innerHTML = lapNow + '<small>/2</small>';
      }
      // legacy raceinfo line kept for debug probes
      if (r) {
        const lapTxt = this.track.closed ? `LAP ${Math.min(r.laps, r.lapCount[0] + 1)}/${r.laps} · ` : 'SPRINT · ';
        this.hud.raceinfo.textContent = lapTxt + (r.state === 'countdown' ? 'GRID' : `POS ${r.playerPos}/${r.rivals.length + 1}`);
      } else if (this.hud.raceinfo) this.hud.raceinfo.textContent = '';
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
      const race = this.race ? {
        state: this.race.state,
        lap: this.race.lapCount[0] + (this.track.closed ? 1 : 0),
        laps: this.race.laps,
        pos: this.race.playerPos,
      } : null;
      return JSON.stringify({
        mode: this.mode,
        speedMph: fmtMph(this.car.speed),
        boost: Math.round(this.car.boost.meter * 100) / 100,
        boostActive: this.car.boost.active,
        chain: this.car.boost.chain,
        stats: this.car.stats,
        race,
        crash: this.crash ? {
          state: this.crash.state, total: Math.round(this.crash.total),
          hits: this.crash.props.filter(p => p.hit).length,
          props: this.crash.props.length, cine: Math.round(this.crash.cine * 10) / 10,
        } : null,
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