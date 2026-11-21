// Signal Nine — traffic: civilian vehicles flowing both directions with lane discipline.
// Greybox v0: box-massing prototypes (sedan/pickup/van/bus/semi), spline-lane AI.
// Near-miss detection lives here; collisions are resolved in physics.js.
window.S9 = window.S9 || {};
(function () {
  const { rng, clamp, angDiff } = S9.util;

  // massing from modeler-s9's traffic blockout report (real footprints);
  // heavier = bigger = Crash-mode jackpots later
  const TYPES = [
    { name: 'sedan', len: 4.80, wid: 1.85, hei: 1.42, mass: 1.0 },
    { name: 'hatch', len: 4.10, wid: 1.75, hei: 1.46, mass: 0.9 },
    { name: 'pickup', len: 5.40, wid: 1.95, hei: 1.72, mass: 1.2 },
    { name: 'boxvan', len: 5.80, wid: 2.05, hei: 2.45, mass: 1.6 },
    { name: 'bus', len: 11.00, wid: 2.50, hei: 2.85, mass: 2.4 },
    { name: 'semi', len: 16.00, wid: 2.45, hei: 3.60, mass: 3.2 },
  ];
  const TYPE_WEIGHTS = ['sedan', 'sedan', 'sedan', 'hatch', 'hatch', 'pickup', 'boxvan', 'bus', 'semi'];

  function buildProto(type, color) {
    const g = new THREE.Group();
    const mat = new THREE.MeshLambertMaterial({ color });
    const glass = new THREE.MeshLambertMaterial({ color: 0x223344 });
    const body = new THREE.Mesh(new THREE.BoxGeometry(type.wid, type.hei, type.len), mat);
    body.position.y = type.hei / 2 + 0.35;
    g.add(body);
    if (type.name === 'sedan' || type.name === 'pickup') {
      const cab = new THREE.Mesh(new THREE.BoxGeometry(type.wid * 0.92, type.hei * 0.5, type.len * 0.45), glass);
      cab.position.set(0, type.hei + 0.22, type.name === 'pickup' ? type.len * 0.1 : -type.len * 0.05);
      g.add(cab);
    }
    // dark chassis + wheel hint boxes
    const chassis = new THREE.Mesh(new THREE.BoxGeometry(type.wid * 0.96, 0.35, type.len * 0.94),
      new THREE.MeshLambertMaterial({ color: 0x1a1d22 }));
    chassis.position.y = 0.35;
    g.add(chassis);
    for (const zz of [-type.len * 0.32, type.len * 0.32]) {
      for (const xx of [-type.wid / 2, type.wid / 2]) {
        const w = new THREE.Mesh(new THREE.BoxGeometry(0.22, 0.6, 0.6),
          new THREE.MeshLambertMaterial({ color: 0x111318 }));
        w.position.set(xx, 0.3, zz);
        g.add(w);
      }
    }
    return g;
  }

  class Traffic {
    constructor(scene, track, seed, gltf) {
      this.scene = scene; this.track = track;
      this.r = rng(seed ^ 0x51f7);
      this.cfg = S9.CFG.traffic;
      this.cars = [];
      this.events = [];   // {type:'nearmiss', relSpeed, heavy}
      if (gltf) {
        // glb prototypes: node names are `<type>_*` (hierarchical under <type>_body)
        this.protos = TYPES.map((t) => {
          const g = new THREE.Group();
          for (const node of gltf.scene.children) {
            if (!node.name || !node.name.startsWith(t.name + '_')) continue;
            g.add(node.clone(true));
          }
          return { t, mesh: g };
        });
        this.protoPick = () => {
          const name = this.r.pick(TYPE_WEIGHTS);
          return this.protos.find(p => p.t.name === name) || this.protos[0];
        };
      } else {
        this.protos = [];
        for (const t of TYPES) for (const c of this.cfg.colors.slice(0, 3)) this.protos.push({ t, color: c, mesh: buildProto(t, c) });
        this.protoPick = () => this.r.pick(this.protos);
      }
      this.playerS = 0;
    }

    spawnInitial(playerS) {
      for (let i = 0; i < this.cfg.density; i++) this.#spawn(playerS, i * 60);
    }

    #spawn(playerS, offsetHint) {
      const proto = this.protoPick();
      const dir = this.r() < 0.65 ? 1 : -1;                   // coastal highway: mostly with-traffic
      // with-traffic rides the outer right lane; oncoming the outer left lane
      const lane = dir > 0 ? this.track.laneOffset
        : (this.track.laneOncoming !== undefined ? this.track.laneOncoming : -this.track.laneOffset);
      const mesh = proto.mesh.clone();
      const wheels = [];
      mesh.traverse((o) => { if (/wheel/i.test(o.name || '')) { o.rotation.order = 'YXZ'; wheels.push(o); } });
      this.scene.add(mesh);
      const L = this.track.length;
      let s = (playerS + (dir > 0 ? 40 : 0) + offsetHint + this.r.range(0, 40));
      s = this.track.closed ? s % L : clamp(s, 10, L - 10);
      this.cars.push({
        mesh, s, lane, dir, wheels,
        speed: this.r.range(this.cfg.speedMin, this.cfg.speedMax) * (dir > 0 ? 1 : 0.92),
        t: proto.t, passed: false, cool: 0,
      });
    }

    // wrap ds into [-L/2, L/2] on circuits; plain signed distance point-to-point
    #ds(a, b) {
      const L = this.track.length;
      if (!this.track.closed) return a - b;
      let d = (a - b) % L;
      if (d > L / 2) d -= L; if (d < -L / 2) d += L;
      return d;
    }

    update(dt, player) {
      this.events.length = 0;
      const L = this.track.length;
      const window0 = -380, window1 = 480;
      // keep density: respawn far-behind/far-ahead strays
      while (this.cars.length < this.cfg.density) this.#spawn(player.s, this.r.range(window1 * 0.5, window1));
      for (let i = this.cars.length - 1; i >= 0; i--) {
        const c = this.cars[i];
        c.s = this.track.closed
          ? (c.s + c.dir * c.speed * dt + L) % L
          : c.s + c.dir * c.speed * dt;
        c.cool = Math.max(0, c.cool - dt);
        if (c.grazeCool > 0) c.grazeCool -= dt;
        const ds = this.#ds(c.s, player.s) * c.dir; // distance ahead in the car's own direction
        if (ds < window0 || ds > window1
            || (!this.track.closed && (c.s < 0 || c.s > L))) {
          this.scene.remove(c.mesh);
          this.cars.splice(i, 1);
          continue;
        }
        const p = this.track.posAt(c.s, c.lane);
        c.mesh.position.copy(p);
        c.mesh.rotation.y = this.track.tangentYawAt(c.s) + (c.dir < 0 ? Math.PI : 0);
        for (const w of c.wheels) w.rotation.x += c.speed * dt / 0.34; // rolling on the shared axle radius

        // near-miss: pass within a car width at high relative speed, no contact
        // (suppressed while the player is crashing/respawning)
        const pdx = Math.abs(this.#ds(c.s, player.s));
        const latGap = Math.abs(c.lane - player.lateral) - (c.t.wid + 1.9) / 2;
        const rel = c.dir > 0 ? Math.abs(player.speed - c.speed) : player.speed + c.speed;
        const NM = S9.CFG.boost; // near-miss thresholds live with the boost economy
        if (player.crashed <= 0 && !c.passed && pdx < 3.2 && latGap > 0 && latGap < NM.nearMissGap
            && rel > NM.nearMissRelSpeed && player.speed > 18) {
          c.passed = true; c.cool = this.cfg.nearMissCooldown;
          this.fireCount = (this.fireCount || 0) + 1;
          (this.closeLog = this.closeLog || []).push({ EV: 1, pdx: Math.round(pdx * 10) / 10, latGap: Math.round(latGap * 100) / 100, rel: Math.round(rel), mph: Math.round(player.speed * 2.23694) });
          if (this.closeLog.length > 40) this.closeLog.splice(0, this.closeLog.length - 40);
          this.events.push({ type: 'nearmiss', relSpeed: rel, heavy: c.t.mass >= 1.6 });
          if (this.onNearMiss) this.onNearMiss(rel, c.t.mass >= 1.6); // direct hook — events array is for replay/debug
        } else if (pdx > 6) c.passed = false;
        // rejection telemetry: what killed the most recent close pass
        if (!c.passed && pdx < 4 && latGap > 0 && latGap < 4) {
          this.lastReject = {
            latGap: Math.round(latGap * 100) / 100, rel: Math.round(rel * 10) / 10,
            mph: Math.round(player.speed * 2.23694), why:
              pdx >= 3.2 ? 'pdx' :
              latGap >= NM.nearMissGap ? 'gap' :
              rel <= NM.nearMissRelSpeed ? 'rel' :
              player.speed <= 18 ? 'mph' : '?',
          };
        }
      }
    }
  }

  S9.Traffic = Traffic;
})();