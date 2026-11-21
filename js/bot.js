// Signal Nine — bot: scripted driver for ?auto=1 and the verification gates.
// Phase 0: follows the with-traffic lane, dodges into the oncoming lane when the
// lane ahead is blocked (earning oncoming boost naturally), brakes for corners,
// triggers boost on straights. Race rivals + scripted crash come in Phase 2/3.
window.S9 = window.S9 || {};
(function () {
  const { clamp, angDiff } = S9.util;

  class Bot {
    // signed curvature (rad/m, + = left) over [s+a, s+b]
    curvature(track, s, a, b) {
      const y1 = track.tangentYawAt(s + a);
      const y2 = track.tangentYawAt(s + b);
      return angDiff(y2, y1) / (b - a);
    }

    // scan a lane ahead of the player: nearest same-direction gap (m), that car,
    // and nearest oncoming meeting TIME (s). Cars within 1.7m lateral count.
    #scan(traffic, car, lane, speed) {
      const L = car.track.length;
      let minSame = 1e9, sameCar = null, minOppT = 1e9;
      for (const c of traffic.cars) {
        if (Math.abs(c.lane - lane) > 1.7) continue;
        let ds = (c.s - car.s) % L;
        if (ds > L / 2) ds -= L; if (ds < -L / 2) ds += L;
        if (ds <= 2) continue;
        if (c.dir > 0) {
          if (ds < minSame) { minSame = ds; sameCar = c; }
        } else {
          minOppT = Math.min(minOppT, ds / Math.max(4, speed + c.speed));
        }
      }
      return { minSame, sameCar, minOppT };
    }

    update(car, track, dt) {
      const speed = car.speed;
      const traffic = car.track.trafficRef;
      const laneR = track.laneOffset, laneL = (track.laneDodge !== undefined ? track.laneDodge : -track.laneOffset);
      const squeeze = track.laneSqueeze !== undefined ? track.laneSqueeze : -0.7;
      const L = track.length;
      const wrap = (d) => {
        if (!track.closed) return d;
        d = d % L; if (d > L / 2) d -= L; if (d < -L / 2) d += L; return d;
      };

      const R = this.#scan(traffic, car, laneR, speed);
      const Lft = this.#scan(traffic, car, laneL, speed);

      // pass-state memory: commit once started, HOLD the squeeze line until
      // genuinely clear (|ds| > 12) — without this the swing-wide overshoot
      // passes at 4-6m separation and never crosses the near-miss window.
      if (this.passing) {
        const still = traffic.cars.includes(this.passing);
        const ds = still ? wrap(this.passing.s - car.s) : 999;
        if (!still || ds > (this.passDeep ? 20 : 12) || ds < -6) this.passing = null;
      }
      const dodgeT = 2.4; // min seconds until meeting nearest oncoming
      // commit distance scales with closing speed — a fixed 40m commit at
      // 80+ mph arrives alongside still 1m from the traffic car (clip/graze
      // instead of near-miss). The lateral shift needs ~2.5-3s.
      const closing = R.sameCar ? Math.max(2, speed - R.sameCar.speed) : 0;
      const commitDist = Math.max(40, 22 + closing * 2.2);
      if (!this.passing && R.sameCar && R.minSame < commitDist && Lft.minOppT > dodgeT) {
        this.passing = R.sameCar;
        this.passDeep = R.minSame < 15; // close car → full oncoming dodge
      }
      let target = laneR;
      if (this.passing) {
        // bail out of a squeeze if an oncoming is about to arrive head-on
        if (!this.passDeep && Lft.minOppT < 1.2) target = laneR;
        else target = this.passDeep ? laneL : squeeze;
      } else if (car.lateral < laneL + 0.3) {
        // committed to the oncoming run until the right lane is truly clear
        target = (R.minSame > 45 && R.minOppT > dodgeT) ? laneR : laneL;
      }
      this.lastTarget = target;

      // boxed in behind same-direction traffic with nowhere to dodge: match speed.
      // Look-ahead windows SCALE with speed — fixed windows make the bot brake
      // constantly at 100+ mph and never get fast enough to dodge and earn.
      const kNear = Math.abs(this.curvature(track, car.s, Math.max(12, speed * 0.4), speed * 1.4));
      const kFar = Math.abs(this.curvature(track, car.s, speed * 1.4, speed * 2.8)) * 0.75;
      const kMax = Math.max(kNear, kFar);
      const vComfort = kMax > 1e-4 ? Math.sqrt(22.0 / kMax) : car.cfg.topSpeed;
      let vTarget = Math.min(vComfort, car.cfg.topSpeed);
      if (target === laneR && !this.passing && R.sameCar && R.minSame < 30) vTarget = Math.min(vTarget, R.sameCar.speed - 1.0);
      // proportional braking (bang-bang from 106→17mph overshoots badly)
      const over = speed - vTarget;
      let throttle = 1, brake = 0;
      if (over > 1) { throttle = 0; brake = clamp(over / 9, 0.25, 1); }
      else if (over > -2) throttle = clamp(0.5 + over * 0.2, 0.3, 1);

      // steering: curvature feedforward + lateral PD (steer + = left, +slip = left)
      const look = 12 + speed * 0.55;
      const k = this.curvature(track, car.s, look * 0.35, look * 1.35);
      const falloff = 1 / (1 + speed * 0.022);
      const ff = clamp(k * speed / (car.cfg.steerRate * falloff), -1, 1);
      const steer = clamp(ff - (target - car.lateral) * 0.12 - car.slip * 1.6, -1, 1);

      // boost on a full meter when the road ahead is straight enough (speed-scaled)
      let boost = false;
      const kAhead = Math.max(
        Math.abs(this.curvature(track, car.s, Math.max(6, speed * 0.2), speed * 1.6)),
        Math.abs(this.curvature(track, car.s, speed * 1.2, speed * 2.6)) * 0.7);
      if (car.boost.meter >= 0.99 && kAhead < 0.0075 && speed > car.cfg.topSpeed * 0.45) boost = true;
      if (car.boost.active) boost = true; // hold it while it lasts

      return { throttle, brake, steer, boost, drift: false };
    }
  }

  S9.Bot = Bot;
})();