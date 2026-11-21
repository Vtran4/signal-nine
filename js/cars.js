// Signal Nine — cars: hero car blockouts, arcade physics, THE boost economy.
// Model: car lives in track space (s, lateral). Heading deviating from the spline
// tangent IS the slip angle — steering into a corner, drifting, and oncoming
// lane driving all fall out of one relation: ds = v·cos(slip), dLat = v·sin(slip).
window.S9 = window.S9 || {};
(function () {
  const { clamp, lerp, angDiff } = S9.util;

  function buildCarMesh(cfg) {
    const g = new THREE.Group();
    const paint = new THREE.MeshStandardMaterial({
      color: cfg.paint, metalness: 0.45, roughness: 0.34,
      envMapIntensity: 1.0, flatShading: true,
    });
    const dark = new THREE.MeshLambertMaterial({ color: 0x14161c });
    const glass = new THREE.MeshStandardMaterial({ color: 0x1c2c3c, metalness: 0.6, roughness: 0.15 });

    // class-proportioned blockout: long hood, wide stance, low roofline
    const dims = {
      street: { L: 4.3, W: 1.85, H: 0.62, cabL: 1.7, cabH: 0.5, cabZ: -0.35, nose: 0.55 },
      perf:   { L: 4.5, W: 1.95, H: 0.5,  cabL: 1.9, cabH: 0.42, cabZ: -0.55, nose: 0.7 },
      super:  { L: 4.6, W: 2.0,  H: 0.46, cabL: 1.6, cabH: 0.4,  cabZ: -0.75, nose: 0.85 },
    }[cfg.id];

    const body = new THREE.Mesh(new THREE.BoxGeometry(dims.W, dims.H, dims.L), paint);
    body.position.y = 0.52;
    g.add(body);
    const nose = new THREE.Mesh(new THREE.BoxGeometry(dims.W * 0.96, dims.H * 0.55, dims.nose), paint);
    nose.position.set(0, 0.42, dims.L / 2 + dims.nose / 2 - 0.06);
    g.add(nose);
    const cab = new THREE.Mesh(new THREE.BoxGeometry(dims.W * 0.82, dims.cabH, dims.cabL), glass);
    cab.position.set(0, 0.52 + dims.H / 2 + dims.cabH / 2 - 0.04, dims.cabZ);
    g.add(cab);
    // rear deck / wing for perf+super
    if (cfg.id !== 'street') {
      const wing = new THREE.Mesh(new THREE.BoxGeometry(dims.W * 0.9, 0.06, 0.32), paint);
      wing.position.set(0, 0.95, -dims.L / 2 + 0.15);
      g.add(wing);
      for (const xx of [-dims.W * 0.32, dims.W * 0.32]) {
        const strut = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.22, 0.1), dark);
        strut.position.set(xx, 0.82, -dims.L / 2 + 0.15);
        g.add(strut);
      }
    }
    // lights
    const hl = new THREE.MeshStandardMaterial({ color: 0xfff6d8, emissive: 0x887744, emissiveIntensity: 0.6 });
    const tl = new THREE.MeshStandardMaterial({ color: 0xff3322, emissive: 0xcc1100, emissiveIntensity: 0.9 });
    for (const xx of [-dims.W * 0.3, dims.W * 0.3]) {
      const a = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.1, 0.06), hl);
      a.position.set(xx, 0.5, dims.L / 2 + dims.nose - 0.04); g.add(a);
      const b = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.08, 0.06), tl);
      b.position.set(xx, 0.55, -dims.L / 2 - 0.02); g.add(b);
    }
    // wheels — cylinder segments low (blockout)
    const wgeo = new THREE.CylinderGeometry(0.34, 0.34, 0.26, 10);
    wgeo.rotateZ(Math.PI / 2);
    const wheels = [];
    for (const zz of [dims.L * 0.32, -dims.L * 0.32]) {
      for (const xx of [-dims.W / 2 + 0.02, dims.W / 2 - 0.02]) {
        const w = new THREE.Mesh(wgeo, dark);
        w.position.set(xx, 0.34, zz);
        g.add(w); wheels.push(w);
      }
    }
    g.userData.wheels = wheels;
    g.userData.dims = dims;
    return g;
  }

  class Car {
    static _count = 0;
    constructor(track, cfg) {
      this._id = ++Car._count;
      this.track = track; this.cfg = cfg;
      this.mesh = buildCarMesh(cfg);
      this.s = 30; this.lateral = 0; this.heading = track.tangentYawAt(30);
      this.speed = 0; this.slip = 0; this.drifting = false;
      this.steerVis = 0;
      this.boost = { meter: 0, active: false, chain: 0, ease: 0 };
      this.air = { up: false, time: 0 };
      this.crashed = 0;          // >0 = crash timer (respawn countdown)
      this.invuln = 0;
      this.earnAcc = { oncoming: 0, drift: 0, air: 0 };
      this.stats = { nearMisses: 0, oncomingTime: 0, driftTime: 0, topMph: 0, burnouts: 0, crashes: 0 };
      this.place();
    }

    get topSpeed() { return this.boost.active ? this.cfg.boostTop : this.cfg.topSpeed; }

    // --- boost economy ---
    #updateBoost(dt, input) {
      const b = this.boost, B = S9.CFG.boost;
      // earners (danger only)
      let earn = 0;
      if (this.drifting && this.speed > B.driftMinSpeed) { earn += B.earn.drift; this.stats.driftTime += dt; }
      if (this.lateral < -1.2 && this.speed > B.oncomingMinSpeed && !this.crashed) {
        earn += B.earn.oncoming; this.stats.oncomingTime += dt;
      }
      if (this.air.up) earn += B.earn.air;
      b.meter = clamp(b.meter + earn * dt, 0, 1);

      // trigger
      if (input.boost && !b.active && b.meter >= B.triggerAt && !this.crashed) {
        b.active = true;
        return 'boost_start';
      }
      // burn + Burnout chaining: refill to full DURING one activation = chain
      if (b.active) {
        b.meter -= B.drainPerSec * dt;
        if (earn > 0) b.meter += earn * dt;
        if (b.meter >= 0.999) {
          b.meter = 1; b.chain++; this.stats.burnouts++;
          return 'burnout';
        }
        if (b.meter <= 0) { b.meter = 0; b.active = false; b.chain = 0; return 'boost_end'; }
      }
      return null;
    }

    addNearMiss(heavy) {
      const B = S9.CFG.boost;
      this.nmCalls = (this.nmCalls || 0) + 1;
      if (this.crashed) { this.nmSwallowed = (this.nmSwallowed || 0) + 1; return; }
      this.boost.meter = clamp(this.boost.meter + B.earn.nearMiss * (heavy ? 1.3 : 1), 0, 1);
      this.stats.nearMisses++;
    }

    update(dt, input) {
      const cfg = this.cfg, T = this.track;

      if (this.crashed > 0) {
        this.crashed = Math.max(0, this.crashed - dt);
        this.speed = Math.max(0, this.speed - 30 * dt);
        if (this.crashed <= 0) this.#respawn();
        this.place();
        return null;
      }
      this.invuln = Math.max(0, this.invuln - dt);

      // steering (speed-sensitive falloff; handbrake sharpens rotation)
      const falloff = 1 / (1 + this.speed * 0.022);
      const steerAuth = input.drift ? cfg.driftYaw : 1;
      const yawRate = input.steer * cfg.steerRate * falloff * steerAuth;
      this.heading += yawRate * dt;

      // slip = heading vs path direction; it IS the lateral motion
      const tangentYaw = T.tangentYawAt(this.s);
      this.slip = angDiff(this.heading, tangentYaw);
      this.drifting = Math.abs(this.slip) > S9.CFG.boost.driftMinSlip && this.speed > S9.CFG.boost.driftMinSpeed;

      // tire alignment pulls heading back toward the path (weak while drifting)
      const align = input.drift ? cfg.driftGrip * 0.45 : cfg.grip * 0.55;
      this.heading -= this.slip * clamp(align * dt, 0, 0.5);

      // longitudinal: thrust vs drag, boost raises ceiling + accel
      const top = this.topSpeed;
      const accel = cfg.accel * (this.boost.active ? 1.55 : 1);
      const drag = accel * Math.pow(clamp(this.speed / top, 0, 1.2), 2.4);
      let a = input.throttle * accel - drag;
      a -= input.brake * cfg.brake * (this.speed > 0 ? 1 : 0);
      if (input.throttle < 0.05 && !input.brake) a -= cfg.engineBrake;
      this.speed = Math.max(0, this.speed + a * dt);
      if (this.boost.active) this.speed = Math.min(this.speed, top * 1.02);

      // integrate in track space. d(lateral)/dt = dot(v, right) = -v·sin(slip):
      // nose left of tangent (slip > 0) = moving toward the oncoming side.
      this.s = (this.s + this.speed * Math.cos(this.slip) * dt + T.length) % T.length;
      this.lateral -= this.speed * Math.sin(this.slip) * dt;

      // walls: clamp + scrub (graze tolerance — light contacts never crash).
      // Scrape response reflects the nose outward with a minimum kick — a pure
      // damping term equilibrates against steering input and grinds forever.
      const lim = T.halfW - 0.95;
      if (Math.abs(this.lateral) > lim) {
        const side = Math.sign(this.lateral);
        this.lateral = side * lim;
        this.speed *= S9.CFG.physics.wallScrub;
        const latVel = -this.speed * Math.sin(this.slip); // d(lateral)/dt
        if (latVel * side > 0) {
          // scrape throws the car away from the wall — kick must beat the tire
          // align term or the car oscillates pinned at the rail forever
          const slipOut = Math.asin(clamp(latVel * 0.35 / Math.max(this.speed, 2), -0.45, 0.45));
          this.heading = tangentYaw + side * Math.max(0.32, Math.abs(slipOut) * 1.2);
        }
        return 'wall';
      }

      const ev = this.#updateBoost(dt, input);
      const mph = this.speed * S9.CFG.MPH;
      if (mph > this.stats.topMph) this.stats.topMph = mph;
      this.steerVis = lerp(this.steerVis, input.steer, clamp(dt * 10, 0, 1));
      this.place();
      return ev;
    }

    #respawn() {
      // replacement car, undamaged, boost emptied — crashes cost time, never the race
      this.crashed = 0;   // MUST reset: a residual negative is truthy and
                          // silently swallows every near-miss afterwards
      this.speed = 8;
      this.lateral = this.track.laneOffset;
      this.heading = this.track.tangentYawAt(this.s);
      this.slip = 0;
      this.boost.meter = 0; this.boost.active = false; this.boost.chain = 0;
      this.invuln = 2;
      this.place();
    }

    crash() {
      if (this.invuln > 0 || this.crashed > 0) return false;
      this.crashed = 1.4;
      this.boost.meter = 0; this.boost.active = false; this.boost.chain = 0;
      this.stats.crashes++;
      return true;
    }

    graze(strength) {
      this.speed *= S9.CFG.physics.grazeScrub;
      this.lateral += strength * 0.4; // shoved aside, keeps going
    }

    place() {
      const p = this.track.posAt(this.s, this.lateral);
      this.mesh.position.copy(p);
      this.mesh.rotation.y = this.heading;
      this.mesh.rotation.z = -this.slip * 0.55;  // lean into the slide
      const wheels = this.mesh.userData.wheels;
      for (let i = 0; i < wheels.length; i++) {
        wheels[i].rotation.x += this.speed * 0.06;
        if (i < 2) wheels[i].rotation.y = this.steerVis * 0.42; // front pair — cylinder rotated: use y? set on group below
      }
      // note: wheel cylinders were rotated at geometry level; steer via rotation.y works post-rotateZ
    }
  }

  S9.Car = Car;
})();