// Signal Nine — modes: state machine + the Race event controller.
// Race: staggered grid start, countdown, 2-lap circuits / point-to-point
// sprints vs 5 AI rivals (6-car grid), live position, race score (near-miss,
// oncoming, drift, takedowns), medals by finishing position, best-medal
// persistence per track.
window.S9 = window.S9 || {};
(function () {
  const { clamp } = S9.util;

  const SKILL = [0.97, 0.94, 0.92, 0.9, 0.87];    // rival throttle scales — gold is earnable clean
  const RIVALS = [
    { cfg: 'perf', name: 'KESTREL MR', paint: 0x2fb7a9, tok: 'perf' },
    { cfg: 'super', name: 'APEX GT1', paint: 0xf2f0e6, tok: 'super' },
    { cfg: 'street', name: 'VANDAL GT', paint: 0x3a6fd8, tok: 'street' },
    { cfg: 'street', name: 'WARHAWK 500', paint: 0x2456c8, tok: 'warhawk' },   // muscle coupe — heavier
    { cfg: 'super', name: 'HALBERD F12', paint: 0x8a7a5a, tok: 'halberd' },    // flat-12 wedge — widest
  ];
  const MEDALS = ['GOLD', 'SILVER', 'BRONZE', '4TH', '5TH'];
  const RIVAL_CFG_TWEAK = { 'WARHAWK 500': { mass: 1420, steerRate: 1.7, grip: 6.2 }, 'HALBERD F12': { mass: 1060, steerRate: 2.5, grip: 7.6, topSpeed: 88 } };

  class Modes {
    constructor(game) {
      this.game = game;
      this.mode = 'attract';
    }

    set(mode) {
      if (this.mode === mode) return;
      this.mode = mode;
      this.game.mode = mode;
    }

    // URL ?state= jumps — hard-to-reach states for verification
    jump(name) {
      const g = this.game;
      if (name === 'drive') { g.startRun(); return true; }
      if (name === 'race') { g.startRace(); return true; }
      if (name.startsWith('crash')) {
        const idx = parseInt(name.replace('crash', ''), 10);
        g.startCrash(Number.isFinite(idx) ? clamp(idx - 1, 0, 3) : 0);
        return true;
      }
      if (name === 'boost') {
        g.startRun();
        g.car.boost.meter = 1;
        g.car.boost.active = true;   // forced activation for streak screenshots
        return true;
      }
      if (name === 'results') { g.showResults(); return true; }
      if (name.startsWith('crash')) { g.startRun(); return true; } // Phase 3: crash junction state
      return false;
    }
  }

  class Race {
    constructor(game, laps) {
      this.game = game;
      this.laps = laps;                 // circuits: 3; sprints: 1
      this.state = 'countdown';
      this.timer = -2.4;                // countdown seconds (negative = pre-GO)
      this.track = game.track;
      this.player = game.car;
      this.finishOrder = [];            // car indexes (0 = player) in finishing order
      this.playerPos = 1;

      // rivals — staggered grid behind the player, bot-driven
      this.rivals = RIVALS.map((spec, i) => {
        const base = S9.CARS.find(c => c.id === spec.cfg) || S9.CARS[0];
        const cfg = Object.assign({}, base, {
          name: spec.name,
          accel: base.accel * SKILL[i],
          topSpeed: base.topSpeed * (0.97 + i * 0.015),
          boostTop: base.boostTop * (0.97 + i * 0.015),
        }, RIVAL_CFG_TWEAK[spec.name] || {});
        const rival = new S9.Car(this.track, cfg);
        const L = this.track.length;
        rival.s = this.track.closed ? ((30 - 9 - i * 9) + L) % L : clamp(30 - 9 - i * 9, 2, L - 2);
        rival.lateral = (i % 2 === 0 ? -1.8 : 1.8); // two-column grid, clear of the pole lane
        rival.heading = this.track.tangentYawAt(rival.s);
        rival.place();
        rival.bot = new S9.Bot();
        rival.takedownInfo = { lastPlayerHit: -99, signature: false }; // takedown attribution
        if (rival.shadowMesh) game.scene.add(rival.shadowMesh);
        game.scene.add(rival.mesh);
        return rival;
      });
      this.prevS = [this.player.s, ...this.rivals.map(r => r.s)];
      this.lapCount = [0, 0, 0, 0, 0, 0];     // wraps on circuits
      this.done = [false, false, false, false, false, false];
      this.score = 0;
    }

    progress(i) {
      const L = this.track.length;
      const s = i === 0 ? this.player.s : this.rivals[i - 1].s;
      return this.lapCount[i] * L + s;
    }

    dispose() {
      for (const r of this.rivals) {
        this.game.scene.remove(r.mesh);
        if (r.shadowMesh) this.game.scene.remove(r.shadowMesh);
      }
    }

    update(dt) {
      if (this.state === 'countdown') {
        this.timer += dt;
        if (this.timer >= 0) {
          this.state = 'racing';
          S9.util.showEvent('GO!', true);
        }
        return;
      }
      if (this.state === 'finished') {
        this.resultsTimer -= dt;
        if (this.resultsTimer <= 0 && !this.resultsShown) {
          this.resultsShown = true;
          this.game.showRaceResults(this.playerPos, this.medal);
        }
        return;
      }

      const L = this.track.length;
      const cars = [this.player, ...this.rivals];
      for (let i = 0; i < cars.length; i++) {
        const s = cars[i].s;
        if (this.track.closed && this.prevS[i] - s > L * 0.5) this.lapCount[i]++;
        this.prevS[i] = s;
        const finished = this.track.closed
          ? this.lapCount[i] >= this.laps
          : s >= L - 12;
        if (finished && !this.done[i]) {
          this.done[i] = true;
          this.finishOrder.push(i);
          if (i === 0) {
            this.playerPos = this.finishOrder.length;
            this.medal = MEDALS[clamp(this.playerPos - 1, 0, 4)];
            this.state = 'finished';
            this.resultsTimer = 1.4;
            S9.util.showEvent(this.medal === '4TH' || this.medal === '5TH' ? 'FINISHED ' + this.playerPos : this.medal + ' MEDAL', true);
          }
        }
      }
      // takedown attribution: a rival crashing within 2s of player contact is
      // the player's takedown — signature if the rival was airborne or slammed
      // a traffic car (heavier payout handled by the game layer)
      const now = this.game.runTime;
      for (let k = 0; k < this.rivals.length; k++) {
        const rv = this.rivals[k];
        if (rv.crashed > 0 && !rv.takedownInfo.counted) {
          rv.takedownInfo.counted = true;
          if (now - rv.takedownInfo.lastPlayerHit < 2.0) {
            const signature = rv.takedownInfo.signature;
            this.game.awardTakedown(rv, signature);
          }
        } else if (rv.crashed <= 0) {
          rv.takedownInfo.counted = false;
        }
      }
      if (!this.done[0]) {
        this.playerPos = 1 + this.rivals.filter((_, k) => !this.done[k + 1] && this.progress(k + 1) > this.progress(0)).length;
      }
      // race score — B3 economy: drift 50/s, oncoming 25/s, near-miss 150,
      // takedowns 1000 (awarded by the game on rival crash attribution)
      const st = this.game.car.stats;
      this.score = Math.round(
        st.nearMisses * 150 + st.driftTime * 50 + st.oncomingTime * 25 + this.game.takedowns * 1000);
    }
  }

  // ---------------- Crash junction mode ----------------
  // Fixed, non-randomized vehicle layouts per junction (trial-and-error
  // puzzles). Launch straight down the runway; every staged vehicle hit adds
  // cash, combos multiply; the attempt ends when everything settles.
  const CRASH_TYPES = {
    sedan: { len: 4.80, wid: 1.85, hei: 1.42, mass: 1.0 },
    hatch: { len: 4.10, wid: 1.75, hei: 1.46, mass: 0.9 },
    pickup: { len: 5.40, wid: 1.95, hei: 1.72, mass: 1.2 },
    boxvan: { len: 5.80, wid: 2.05, hei: 2.45, mass: 1.6 },
    bus: { len: 11.0, wid: 2.50, hei: 2.85, mass: 2.4 },
    semi: { len: 16.0, wid: 2.45, hei: 3.60, mass: 3.2 },
  };
  // ds = along the main road from the junction center; cross = along the arm
  const CRASH_LAYOUTS = [
    [ // J1 — warm-up: two queued sedans, a crossing boxvan, one bus arm
      { type: 'sedan', ds: 26, lateral: 3.6, onMain: true },
      { type: 'sedan', ds: 38, lateral: 3.6, onMain: true },
      { type: 'boxvan', cross: 9, onMain: false },
      { type: 'bus', cross: 15, onMain: false },
    ],
    [ // J2 — the semi comes in
      { type: 'semi', cross: 14, onMain: false },
      { type: 'sedan', ds: 24, lateral: 1.2, onMain: true },
      { type: 'sedan', ds: 34, lateral: 3.6, onMain: true },
      { type: 'hatch', ds: 44, lateral: 1.2, onMain: true },
      { type: 'boxvan', cross: -16, onMain: false },
    ],
    [ // J3 — two heavies crossing
      { type: 'bus', cross: -12, onMain: false },
      { type: 'semi', cross: 18, onMain: false },
      { type: 'pickup', ds: 22, lateral: 3.6, onMain: true },
      { type: 'sedan', ds: 30, lateral: 1.2, onMain: true },
      { type: 'hatch', ds: 40, lateral: 3.6, onMain: true },
      { type: 'boxvan', cross: -22, onMain: false },
    ],
    [ // J4 — the jackpot: dense center, everything within reach
      { type: 'semi', cross: 10, onMain: false },
      { type: 'bus', cross: -14, onMain: false },
      { type: 'boxvan', cross: 2, onMain: false },
      { type: 'pickup', ds: 20, lateral: 1.2, onMain: true },
      { type: 'sedan', ds: 28, lateral: 3.6, onMain: true },
      { type: 'hatch', ds: 36, lateral: 1.2, onMain: true },
      { type: 'sedan', ds: 46, lateral: 3.6, onMain: true },
    ],
  ];

  // hazard halo: additive sprite per hit prop — emissive dots are sub-pixel
  // at payoff distance; a screen-space halo is what actually reads
  let HALO_TEX = null;
  function beaconHalo() {
    if (!HALO_TEX) {
      const cv = document.createElement('canvas'); cv.width = cv.height = 64;
      const cx = cv.getContext('2d');
      const g = cx.createRadialGradient(32, 32, 2, 32, 32, 30);
      g.addColorStop(0, 'rgba(255,70,35,1)'); g.addColorStop(0.4, 'rgba(255,70,35,0.5)'); g.addColorStop(1, 'rgba(255,70,35,0)');
      cx.fillStyle = g; cx.fillRect(0, 0, 64, 64);
      HALO_TEX = new THREE.CanvasTexture(cv);
    }
    const spr = new THREE.Sprite(new THREE.SpriteMaterial({
      map: HALO_TEX, blending: THREE.AdditiveBlending, depthWrite: false, transparent: true, opacity: 0.9 }));
    spr.scale.set(3.6, 3.6, 1);
    return spr;
  }

  class Crash {
    constructor(game, junctionIdx) {
      this.game = game;
      this.idx = junctionIdx;
      this.track = game.track;
      this.player = game.car;
      this.junction = this.track.junctions[junctionIdx];
      this.state = 'countdown';
      this.timer = -2.2;
      this.total = 0;
      this.combo = 0;
      this.comboT = 0;
      this.impactPoint = null;
      this.cine = 0;
      this.settleT = 0;
      this.impacted = false;
      this.props = [];
      this.launchLat = this.track.laneOffset;

      const L = this.track.length;
      this.player.s = clamp(this.junction.s - 130, 10, L - 10);
      this.player.lateral = this.track.laneOffset;
      this.player.speed = 0;
      this.player.heading = this.track.tangentYawAt(this.player.s);
      this.player.slip = 0;
      this.player.boost = { meter: 0, active: false, chain: 0, ease: 0 };
      this.player.crashed = 0; this.player.invuln = 0;
      this.player.place();

      // staged vehicles from the fixed layout
      const g = this.junction ? this.junction.s : 0;
      const armHalf = (this.junction ? this.junction.arm : 40) / 2;
      const cy = this.track.posAt(g, 0).y;
      for (const spec of CRASH_LAYOUTS[junctionIdx] || []) {
        const t = CRASH_TYPES[spec.type];
        let pos, yaw;
        if (spec.onMain) {
          const s = clamp(g + spec.ds, 2, L - 2);
          pos = this.track.posAt(s, spec.lateral);
          yaw = this.track.tangentYawAt(s);
        } else {
          const c = this.track.posAt(g, 0);
          const yawv = this.track.tangentYawAt(g);
          // cross direction = perpendicular to the main road (arm spans both sides)
          const rx = -Math.cos(yawv), rz = Math.sin(yawv);
          pos = new THREE.Vector3(c.x + rx * spec.cross, c.y, c.z + rz * spec.cross);
          yaw = yawv + Math.PI / 2;
        }
        const mesh = this.buildPropMesh(spec.type, t);
        mesh.position.copy(pos);
        mesh.rotation.y = yaw;
        game.scene.add(mesh);
        this.props.push({ type: spec.type, t, mesh, vel: new THREE.Vector3(), spin: 0, hit: false, cool: 0 });
      }
      S9.util.showEvent('CRASH JUNCTION ' + (junctionIdx + 1), true);
    }

    buildPropMesh(type, t) {
      // dressed glb if game has traffic asset; else blockout box
      const A = this.game.assets;
      if (A && A.trafficGltf) {
        const g = new THREE.Group();
        for (const node of A.trafficGltf.scene.children) {
          if (node.name && node.name.startsWith(type + '_')) g.add(node.clone(true));
        }
        if (g.children.length) return g;
      }
      const body = new THREE.Mesh(
        new THREE.BoxGeometry(t.wid, t.hei, t.len),
        new THREE.MeshLambertMaterial({ color: 0x8a8578 }));
      body.position.y = t.hei / 2 + 0.3;
      const grp = new THREE.Group();
      grp.add(body);
      return grp;
    }

    addCash(n, label) {
      this.total += n;
      S9.util.showEvent(label || '$' + Math.round(n / 1000) + ',' + String(Math.round(n % 1000 / 100)) + 'K', false);
    }

    update(dt) {
      if (this.state === 'countdown') {
        this.timer += dt;
        if (this.timer >= 0) { this.state = 'launch'; S9.util.showEvent('LAUNCH!', true); }
        return;
      }
      if (this.state === 'done') return;

      // prop integration: drift, spin, decay + sanity clamp (an ungated impulse
      // chain once flung props 300m off the junction)
      const pulse = Math.sin(performance.now() / 1000 * 9);
      const blink = pulse > 0 ? 4.5 : 1.2; // bright pulse, 1.2 dull-glow floor
      for (const p of this.props) {
        p.cool = Math.max(0, p.cool - dt);
        if (p.lights) for (const m of p.lights) m.emissiveIntensity = m.emissiveIntensity > 0 ? blink : 0;
        if (p.halo) { p.halo.material.opacity = pulse > 0 ? 0.95 : 0.32; p.halo.scale.setScalar(pulse > 0 ? 4.6 : 3.4); }
        if (p.vel.lengthSq() > 0.01) {
          if (p.vel.length() > 18) p.vel.setLength(18);
          p.mesh.position.addScaledVector(p.vel, dt);
          p.mesh.rotation.y += p.spin * dt;
          p.vel.multiplyScalar(Math.max(0, 1 - dt * 2.2));
          p.spin *= Math.max(0, 1 - dt * 2.0);
        }
      }
      // prop-vs-prop chain hits (cooldown-gated so overlaps don't pump velocity)
      for (let i = 0; i < this.props.length; i++) {
        const a = this.props[i];
        if (a.vel.lengthSq() < 4) continue;
        for (let j = 0; j < this.props.length; j++) {
          if (i === j) continue;
          const b = this.props[j];
          if (b.cool > 0) continue;
          const d = a.mesh.position.distanceTo(b.mesh.position);
          if (d < (a.t.len + b.t.len) / 2 * 0.75) {
            b.cool = 0.4;
            const push = a.vel.clone().multiplyScalar(0.55 * a.t.mass / b.t.mass);
            b.vel.add(push);
            b.spin += (Math.random() - 0.5) * 2;
            a.vel.multiplyScalar(0.5);
            if (!b.hit) {
              b.hit = true;
              b.halo = beaconHalo();
              b.halo.position.y = b.t.hei * 0.75 + 0.6;
              b.mesh.add(b.halo);
              this.combo = Math.min(4, this.combo + 1);
              this.addCash(8000 * b.t.mass * this.combo, '$' + (8 * b.t.mass * this.combo).toFixed(0) + 'K ×' + this.combo);
            }
          }
        }
      }
      // player contact vs props (world space, cooldown-gated per prop)
      if (this.player.speed > 3) {
        const pp = this.player.mesh.position;
        const fwd = new THREE.Vector3(Math.sin(this.player.heading), 0, Math.cos(this.player.heading));
        for (const pr of this.props) {
          if (pr.cool > 0) continue;
          const d = pp.distanceTo(pr.mesh.position);
          const contactR = (2.2 + pr.t.len / 2 * 0.8);
          if (d < contactR) {
            pr.cool = 0.4;
            const push = fwd.clone().multiplyScalar(this.player.speed * 0.5 / pr.t.mass);
            pr.vel.add(push);
            pr.spin += (Math.random() - 0.5) * 1.6;
            this.player.speed *= 0.72;
            if (!pr.hit) {
              pr.hit = true;
              this.impacted = true;
              // the crash ends the run: the car is wrecked and coasts —
              // plowing on at speed re-shovels props 100m+ down the road
              this.player.speed = Math.min(this.player.speed, 13);
              // hazard flashers: hit vehicles blink their head/taillights —
              // beacons that make the wreck field read in the dusk bake
              pr.lights = [];
              pr.mesh.traverse((o) => {
                if (o.isMesh && o.material && /lights/.test(o.material.name || '')) pr.lights.push(o.material);
              });
              pr.halo = beaconHalo();
              pr.halo.position.y = pr.t.hei * 0.75 + 0.6;  // prop's own type record
              pr.mesh.add(pr.halo);
              if (!this.impactPoint) {
                this.impactPoint = pr.mesh.position.clone();
                this.cine = 2.2;           // crash cinematic on the first big hit
                this.game.audio.fire('crash');
                this.game.physics.slowMo(1.6, 0.3);
              }
              this.combo = Math.min(4, this.combo + 1);
              this.comboT = 1.6;
              this.addCash((12000 + pr.t.mass * 15000) * this.combo, '$' + ((12 + pr.t.mass * 15) * this.combo).toFixed(0) + 'K ×' + this.combo);
            }
          }
        }
      }
      if (this.comboT > 0) { this.comboT -= dt; if (this.comboT <= 0) this.combo = 0; }
      if (this.cine > 0) this.cine -= dt;

      // settle: everything slow for 1.2s after an impact ends the attempt —
      // driving out of the junction zone ends it too (the scoring window is done)
      const calm = this.player.speed < 2.5 && this.props.every(p => p.vel.lengthSq() < 1);
      const exited = this.player.s > this.junction.s + this.junction.arm / 2 + 30;
      if (this.impacted && (calm && this.settleT > 1.2 || exited)) {
        this.state = 'done';
        this.game.showCrashResults(this.idx, this.total);
      } else if (this.impacted && calm) this.settleT += dt;
      else this.settleT = 0;
    }

    dispose() {
      for (const p of this.props) this.game.scene.remove(p.mesh);
    }
  }

  S9.Modes = Modes;
  S9.Race = Race;
  S9.RACE_MEDALS = MEDALS;
  S9.RACE_RIVALS = RIVALS;
  S9.Crash = Crash;
})();