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

  S9.Modes = Modes;
  S9.Race = Race;
  S9.RACE_MEDALS = MEDALS;
  S9.RACE_RIVALS = RIVALS;
})();