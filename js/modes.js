// Signal Nine — modes: state machine + the Race event controller.
// Race: staggered grid start, countdown, 3-lap circuits / point-to-point
// sprints vs 3 AI rivals, live position, medals by finishing position,
// best-medal persistence per track.
window.S9 = window.S9 || {};
(function () {
  const { clamp } = S9.util;

  const SKILL = [0.97, 0.92, 0.88];               // rival throttle scales — gold is earnable clean
  const RIVALS = [
    { cfg: 'perf', name: 'KESTREL MR', paint: 0x2fb7a9 },
    { cfg: 'super', name: 'APEX GT1', paint: 0xf2f0e6 },
    { cfg: 'street', name: 'VANDAL GT', paint: 0x3a6fd8 },
  ];
  const MEDALS = ['GOLD', 'SILVER', 'BRONZE', '4TH'];

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
        });
        const rival = new S9.Car(this.track, cfg);
        const L = this.track.length;
        rival.s = this.track.closed ? ((30 - 9 - i * 9) + L) % L : clamp(30 - 9 - i * 9, 2, L - 2);
        rival.lateral = (i % 2 === 0 ? -1.8 : 1.8); // two-column grid, clear of the pole lane
        rival.heading = this.track.tangentYawAt(rival.s);
        rival.place();
        rival.bot = new S9.Bot();
        if (rival.shadowMesh) game.scene.add(rival.shadowMesh);
        game.scene.add(rival.mesh);
        return rival;
      });
      this.prevS = [this.player.s, ...this.rivals.map(r => r.s)];
      this.lapCount = [0, 0, 0, 0];     // wraps on circuits
      this.done = [false, false, false, false];
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
            this.medal = MEDALS[clamp(this.playerPos - 1, 0, 3)];
            this.state = 'finished';
            this.resultsTimer = 1.4;
            S9.util.showEvent(this.medal === '4TH' ? 'FINISHED' : this.medal + ' MEDAL', true);
          }
        }
      }
      if (!this.done[0]) {
        this.playerPos = 1 + this.rivals.filter((_, k) => !this.done[k + 1] && this.progress(k + 1) > this.progress(0)).length;
      }
    }
  }

  // ---------------- Crash junction mode ----------------
  // Fixed, non-randomized vehicle layouts per junction (trial-and-error
  // puzzles). Launch straight down the runway; every staged vehicle hit adds
  // cash, combos multiply; the attempt ends when everything settles.
  const CRASH_TYPES = {
    sedan: { len: 4.80, wid: 1.85, mass: 1.0 },
    hatch: { len: 4.10, wid: 1.75, mass: 0.9 },
    pickup: { len: 5.40, wid: 1.95, mass: 1.2 },
    boxvan: { len: 5.80, wid: 2.05, mass: 1.6 },
    bus: { len: 11.0, wid: 2.50, mass: 2.4 },
    semi: { len: 16.0, wid: 2.45, mass: 3.2 },
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
        this.props.push({ type: spec.type, t, mesh, vel: new THREE.Vector3(), spin: 0, hit: false });
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

      // prop integration: drift, spin, decay
      for (const p of this.props) {
        if (p.vel.lengthSq() > 0.01) {
          p.mesh.position.addScaledVector(p.vel, dt);
          p.mesh.rotation.y += p.spin * dt;
          p.vel.multiplyScalar(Math.max(0, 1 - dt * 2.2));
          p.spin *= Math.max(0, 1 - dt * 2.0);
        }
      }
      // prop-vs-prop chain hits
      for (let i = 0; i < this.props.length; i++) {
        const a = this.props[i];
        if (a.vel.lengthSq() < 4) continue;
        for (let j = 0; j < this.props.length; j++) {
          if (i === j) continue;
          const b = this.props[j];
          const d = a.mesh.position.distanceTo(b.mesh.position);
          if (d < (a.t.len + b.t.len) / 2 * 0.75) {
            const push = a.vel.clone().multiplyScalar(0.55 * a.t.mass / b.t.mass);
            b.vel.add(push);
            b.spin += (Math.random() - 0.5) * 2;
            a.vel.multiplyScalar(0.5);
            if (!b.hit) {
              b.hit = true;
              this.combo = Math.min(4, this.combo + 1);
              this.addCash(8000 * b.t.mass * this.combo, '$' + (8 * b.t.mass * this.combo).toFixed(0) + 'K ×' + this.combo);
            }
          }
        }
      }
      // player contact vs props (world space)
      if (this.player.speed > 3) {
        const pp = this.player.mesh.position;
        const fwd = new THREE.Vector3(Math.sin(this.player.heading), 0, Math.cos(this.player.heading));
        for (const pr of this.props) {
          const d = pp.distanceTo(pr.mesh.position);
          const contactR = (2.2 + pr.t.len / 2 * 0.8);
          if (d < contactR) {
            const closing = this.player.speed * (1 + pr.t.mass * 0.08);
            const push = fwd.clone().multiplyScalar(this.player.speed * 0.5 / pr.t.mass);
            pr.vel.add(push);
            pr.spin += (Math.random() - 0.5) * 1.6;
            this.player.speed *= 0.72;
            if (!pr.hit) {
              pr.hit = true;
              this.impacted = true;
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