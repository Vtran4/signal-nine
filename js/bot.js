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
      const laneR = track.laneOffset, laneL = -track.laneOffset;

      // lane choice: squeeze past same-direction traffic (near-miss window is
      // 0–2.35m of gap — a full-lane dodge overshoots it), full-dodge into the
      // oncoming lane only when it is time-clear, commit while in it.
      const R = this.#scan(traffic, car, laneR, speed);
      const Lft = this.#scan(traffic, car, laneL, speed);
      const dodgeDist = 14 + speed * 1.0;
      const dodgeT = 2.6; // min seconds until meeting nearest oncoming
      let target = laneR;
      const needPass = R.sameCar && R.minSame < dodgeDist;
      if (needPass && Lft.minOppT > dodgeT) target = R.minSame < 12 ? laneL : -0.5;
      else if (car.lateral < -1.2) {
        // committed to the oncoming run until the right lane is truly clear
        target = (R.minSame > 45 && R.minOppT > dodgeT) ? laneR : laneL;
      }

      // boxed in behind same-direction traffic with nowhere to dodge: match speed.
      // Look-ahead windows SCALE with speed — fixed windows make the bot brake
      // constantly at 100+ mph and never get fast enough to dodge and earn.
      const kNear = Math.abs(this.curvature(track, car.s, Math.max(8, speed * 0.4), speed * 1.4));
      const kFar = Math.abs(this.curvature(track, car.s, speed * 1.4, speed * 2.8)) * 0.75;
      const kMax = Math.max(kNear, kFar);
      const vComfort = kMax > 1e-4 ? Math.sqrt(22.0 / kMax) : car.cfg.topSpeed;
      let vTarget = Math.min(vComfort, car.cfg.topSpeed);
      if (target === laneR && R.sameCar && R.minSame < 34) vTarget = Math.min(vTarget, R.sameCar.speed - 1.0);
      let throttle = 1, brake = 0;
      if (speed > vTarget * 1.06) { throttle = 0; brake = 1; }
      else if (speed > vTarget) throttle = 0.3;

      // steering: curvature feedforward + lateral PD (steer + = left, +slip = left)
      const look = 12 + speed * 0.55;
      const k = this.curvature(track, car.s, look * 0.35, look * 1.35);
      const falloff = 1 / (1 + speed * 0.022);
      const ff = clamp(k * speed / (car.cfg.steerRate * falloff), -1, 1);
      const steer = clamp(ff - (target - car.lateral) * 0.10 - car.slip * 1.25, -1, 1);

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