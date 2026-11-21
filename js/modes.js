// Signal Nine — modes: the state machine (attract / drive / results / crash placeholder).
// Phase 0 ships attract + drive (greybox freerun) + results; race and crash modes
// plug into the same enter/exit seams in Phase 2/3.
window.S9 = window.S9 || {};
(function () {
  class Modes {
    constructor(game) {
      this.game = game;
      this.mode = 'attract';
    }

    set(mode) {
      if (this.mode === mode) return;
      const from = this.mode;
      this.mode = mode;
      this.game.onModeChange(from, mode);
    }

    // URL ?state= jumps — hard-to-reach states for verification
    jump(name) {
      const g = this.game;
      if (name === 'drive' || name === 'race') { g.startRun(); return true; }
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

  S9.Modes = Modes;
})();