// Signal Nine — physics: car-vs-traffic resolution, spark bursts, slow-mo helper.
// Collision tolerance is generous grazes: light contacts scrub speed with sparks;
// only hard high-speed hits crash the car (cinematic + respawn is modes/game's job).
window.S9 = window.S9 || {};
(function () {
  const { clamp } = S9.util;

  // --- spark bursts: one shared Points pool, additive, cheap ---
  class Sparks {
    constructor(scene, max = 240) {
      this.max = max;
      this.pos = new Float32Array(max * 3);
      this.vel = new Float32Array(max * 3);
      this.life = new Float32Array(max);
      this.head = 0;
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(this.pos, 3));
      const mat = new THREE.PointsMaterial({
        color: 0xffc36b, size: 0.14, transparent: true, opacity: 0.95,
        blending: THREE.AdditiveBlending, depthWrite: false,
      });
      this.points = new THREE.Points(g, mat);
      this.points.frustumCulled = false;
      for (let i = 0; i < max; i++) this.pos[i * 3 + 1] = -999;
      scene.add(this.points);
    }

    burst(p, n = 14, spread = 5) {
      for (let k = 0; k < n; k++) {
        const i = this.head; this.head = (this.head + 1) % this.max;
        this.pos[i * 3] = p.x; this.pos[i * 3 + 1] = p.y + 0.5; this.pos[i * 3 + 2] = p.z;
        this.vel[i * 3] = (Math.random() - 0.5) * spread;
        this.vel[i * 3 + 1] = Math.random() * spread * 0.7;
        this.vel[i * 3 + 2] = (Math.random() - 0.5) * spread;
        this.life[i] = 0.5 + Math.random() * 0.3;
      }
    }

    update(dt) {
      let live = false;
      for (let i = 0; i < this.max; i++) {
        if (this.life[i] <= 0) continue;
        live = true;
        this.life[i] -= dt;
        this.vel[i * 3 + 1] -= 9 * dt;
        this.pos[i * 3] += this.vel[i * 3] * dt;
        this.pos[i * 3 + 1] += this.vel[i * 3 + 1] * dt;
        this.pos[i * 3 + 2] += this.vel[i * 3 + 2] * dt;
        if (this.life[i] <= 0) this.pos[i * 3 + 1] = -999;
      }
      if (live) this.points.geometry.attributes.position.needsUpdate = true;
    }
  }

  class Physics {
    constructor(scene) {
      this.sparks = new Sparks(scene);
      this.timeScale = 1; this.slowT = 0;
    }

    slowMo(dur = 0.3, scale = 0.35) { this.slowT = dur; this.slowScale = scale; }

    tickScale(dt) {
      if (this.slowT > 0) { this.slowT -= dt; return this.slowScale; }
      return 1;
    }

    // player car vs traffic, in track space; returns list of game events
    resolve(car, traffic, dt) {
      const events = [];
      if (car.crashed > 0 || car.invuln > 0) return events;
      const pl = 4.4, pw = 1.9; // player massing (blockout)
      for (const c of traffic.cars) {
        const L = car.track.length;
        let ds = (c.s - car.s) % L;
        if (ds > L / 2) ds -= L; if (ds < -L / 2) ds += L;
        const latGap = c.lane - car.lateral;
        const overlapS = Math.abs(ds) < (pl + c.t.len) / 2 - 0.35;
        const overlapW = Math.abs(latGap) < (pw + c.t.wid) / 2 - 0.12;
        if (!overlapS || !overlapW) continue;

        const closing = car.speed - c.dir * c.speed; // + = player running into them
        if (Math.abs(closing) > S9.CFG.physics.crashRelSpeed) {
          const p = car.mesh.position;
          this.sparks.burst(p, 34, 9);
          events.push({ type: 'crash', heavy: c.t.mass >= 1.6 });
        } else {
          // graze tolerance: scrub ONCE per contact, not per overlap frame
          if (!(c.grazeCool > 0)) {
            c.grazeCool = 0.6;
            const p = car.mesh.position;
            this.sparks.burst(p, 8, 4);
            car.graze(Math.sign(latGap) || 1);
            events.push({ type: 'graze' });
          }
        }
        break; // one contact per frame is enough
      }
      return events;
    }

    update(dt, car) {
      this.sparks.update(dt);
    }
  }

  S9.Physics = Physics;
})();