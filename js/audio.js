// Signal Nine — audio: WebAudio set. Engine synth pitch-tracks speed, tire chirp,
// near-miss whoosh+thunk, crash impacts, and the boost music swell acting on a
// procedural 2002-arcade music bed. Everything is synthesized — zero assets.
// Sound stays OFF until the user enables it (autoplay policy); the build is
// complete with sound off.
window.S9 = window.S9 || {};
(function () {
  const { clamp } = S9.util;

  class AudioSet {
    constructor() {
      this.on = false;
      this.ctx = null;
      this._step = 0;
      this._nextStep = 0;
    }

    enable() {
      if (this.on) return;
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      const ctx = this.ctx = new AC();
      this.master = ctx.createGain(); this.master.gain.value = 0.85;
      this.master.connect(ctx.destination);

      // buses
      this.busEngine = ctx.createGain(); this.busEngine.gain.value = 0.0; this.busEngine.connect(this.master);
      this.busSfx = ctx.createGain(); this.busSfx.gain.value = 0.9; this.busSfx.connect(this.master);
      this.busMusic = ctx.createGain(); this.busMusic.gain.value = 0.3; this.busMusic.connect(this.master);

      // --- engine: 2 detuned saws + sub sine -> lowpass ---
      this.engFilter = ctx.createBiquadFilter(); this.engFilter.type = 'lowpass'; this.engFilter.frequency.value = 800;
      this.engFilter.connect(this.busEngine);
      this.engGain = ctx.createGain(); this.engGain.gain.value = 0.0; this.engGain.connect(this.engFilter);
      this.osc = [];
      for (const [type, det] of [['sawtooth', -7], ['sawtooth', 7], ['sine', 0]]) {
        const o = ctx.createOscillator(); o.type = type; o.detune.value = det; o.frequency.value = 45;
        const g = ctx.createGain(); g.gain.value = type === 'sine' ? 0.5 : 0.3;
        o.connect(g); g.connect(this.engGain); o.start();
        this.osc.push(o);
      }
      // wind/road noise layer
      this.noiseBuf = this.#makeNoise(2.0);
      const wind = ctx.createBufferSource(); wind.buffer = this.noiseBuf; wind.loop = true;
      this.windFilter = ctx.createBiquadFilter(); this.windFilter.type = 'bandpass'; this.windFilter.frequency.value = 700; this.windFilter.Q.value = 0.6;
      this.windGain = ctx.createGain(); this.windGain.gain.value = 0;
      wind.connect(this.windFilter); this.windFilter.connect(this.windGain); this.windGain.connect(this.master);
      wind.start();

      // --- drift chirp: looping filtered noise, gated ---
      const chirp = ctx.createBufferSource(); chirp.buffer = this.noiseBuf; chirp.loop = true;
      const cf = ctx.createBiquadFilter(); cf.type = 'bandpass'; cf.frequency.value = 2400; cf.Q.value = 8;
      this.chirpGain = ctx.createGain(); this.chirpGain.gain.value = 0;
      chirp.connect(cf); cf.connect(this.chirpGain); this.chirpGain.connect(this.busSfx);
      chirp.start();

      this.on = true;
      this._nextStep = ctx.currentTime + 0.1;
      setInterval(() => this.#schedule(), 90);
    }

    disable() {
      if (!this.on) return;
      this.ctx.close(); this.ctx = null; this.on = false;
    }

    #makeNoise(sec) {
      const ctx = this.ctx;
      const buf = ctx.createBuffer(1, ctx.sampleRate * sec, ctx.sampleRate);
      const d = buf.getChannelData(0);
      for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
      return buf;
    }

    // --- procedural music bed: 96 BPM, 4-bar loop, swells on boost ---
    #schedule() {
      const ctx = this.ctx; if (!ctx || !this.on) return;
      const spb = 60 / 96 / 2; // 8th notes at 96 BPM
      while (this._nextStep < ctx.currentTime + 0.25) {
        this.#step(this._step % 64, this._nextStep);
        this._step++;
        this._nextStep += spb;
      }
    }

    #step(i, t) {
      const ctx = this.ctx, bar = Math.floor(i / 16), pos = i % 16;
      // kick on 0 and 8 of each bar
      if (pos === 0 || pos === 8) {
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.type = 'sine'; o.frequency.setValueAtTime(150, t); o.frequency.exponentialRampToValueAtTime(44, t + 0.11);
        g.gain.setValueAtTime(0.5, t); g.gain.exponentialRampToValueAtTime(0.001, t + 0.16);
        o.connect(g); g.connect(this.busMusic); o.start(t); o.stop(t + 0.2);
      }
      // hats on off-beats
      if (pos % 4 === 2) {
        const n = ctx.createBufferSource(); n.buffer = this.noiseBuf;
        const f = ctx.createBiquadFilter(); f.type = 'highpass'; f.frequency.value = 7000;
        const g = ctx.createGain();
        g.gain.setValueAtTime(0.12, t); g.gain.exponentialRampToValueAtTime(0.001, t + 0.05);
        n.connect(f); f.connect(g); g.connect(this.busMusic); n.start(t); n.stop(t + 0.06);
      }
      // bass line (A minor rock vamp)
      const bass = [55, 0, 55, 65.4, 55, 0, 49, 0,  55, 0, 55, 65.4, 73.4, 0, 65.4, 0];
      const note = bass[pos];
      if (note) {
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.type = 'square'; o.frequency.value = note;
        g.gain.setValueAtTime(0.09, t); g.gain.exponentialRampToValueAtTime(0.001, t + 0.2);
        o.connect(g); g.connect(this.busMusic); o.start(t); o.stop(t + 0.22);
      }
      // pad chord per bar: Am / F / C / G
      const chords = [[220, 261.6, 329.6], [174.6, 220, 261.6], [196, 261.6, 329.6], [196, 246.9, 293.7]];
      if (pos === 0) {
        for (const fq of chords[bar % 4]) {
          const o = ctx.createOscillator(), g = ctx.createGain();
          o.type = 'sawtooth'; o.frequency.value = fq; o.detune.value = (Math.random() - 0.5) * 12;
          g.gain.setValueAtTime(0.0001, t); g.gain.linearRampToValueAtTime(0.028, t + 0.4);
          g.gain.setValueAtTime(0.028, t + 1.6); g.gain.linearRampToValueAtTime(0.0001, t + 2.0);
          o.connect(g); g.connect(this.busMusic); o.start(t); o.stop(t + 2.1);
        }
      }
    }

    // per-frame update
    update(dt, st) {
      if (!this.on) return;
      const ctx = this.ctx;
      const speedNorm = clamp(st.speedNorm, 0, 1);
      // engine pitch tracks speed (+ load wobble), boost opens the filter up
      const f = 42 + speedNorm * 185 * (st.boostK > 0.5 ? 1.28 : 1) + Math.sin(ctx.currentTime * 31) * speedNorm * 3;
      for (const o of this.osc) o.frequency.setTargetAtTime(f * (o === this.osc[2] ? 0.5 : 1), ctx.currentTime, 0.03);
      this.engFilter.frequency.setTargetAtTime(500 + speedNorm * 1900 + (st.boostK > 0.5 ? 900 : 0), ctx.currentTime, 0.05);
      this.engGain.gain.setTargetAtTime(0.05 + st.throttle * 0.10 + speedNorm * 0.06, ctx.currentTime, 0.05);
      this.windGain.gain.setTargetAtTime(speedNorm * speedNorm * 0.11, ctx.currentTime, 0.1);
      this.chirpGain.gain.setTargetAtTime(st.drifting ? 0.16 : 0, ctx.currentTime, st.drifting ? 0.03 : 0.12);
      // boost swell: music cranks to full mix
      const target = st.boostK > 0.5 ? 1.0 : 0.3;
      this.busMusic.gain.setTargetAtTime(target, ctx.currentTime, st.boostK > 0.5 ? 0.15 : 0.6);
    }

    // one-shot events
    fire(ev) {
      if (!this.on) return;
      const ctx = this.ctx, t = ctx.currentTime;
      if (ev === 'nearmiss') {
        const n = ctx.createBufferSource(); n.buffer = this.noiseBuf;
        const f = ctx.createBiquadFilter(); f.type = 'bandpass'; f.Q.value = 2;
        f.frequency.setValueAtTime(500, t); f.frequency.exponentialRampToValueAtTime(3400, t + 0.14);
        const g = ctx.createGain(); g.gain.setValueAtTime(0.4, t); g.gain.exponentialRampToValueAtTime(0.001, t + 0.2);
        n.connect(f); f.connect(g); g.connect(this.busSfx); n.start(t); n.stop(t + 0.22);
        const o = ctx.createOscillator(), g2 = ctx.createGain();
        o.type = 'sine'; o.frequency.setValueAtTime(130, t); o.frequency.exponentialRampToValueAtTime(58, t + 0.09);
        g2.gain.setValueAtTime(0.5, t); g2.gain.exponentialRampToValueAtTime(0.001, t + 0.12);
        o.connect(g2); g2.connect(this.busSfx); o.start(t); o.stop(t + 0.14);
      } else if (ev === 'crash') {
        const n = ctx.createBufferSource(); n.buffer = this.noiseBuf;
        const g = ctx.createGain(); g.gain.setValueAtTime(0.75, t); g.gain.exponentialRampToValueAtTime(0.001, t + 0.7);
        const f = ctx.createBiquadFilter(); f.type = 'lowpass'; f.frequency.setValueAtTime(3600, t);
        f.frequency.exponentialRampToValueAtTime(220, t + 0.6);
        n.connect(f); f.connect(g); g.connect(this.busSfx); n.start(t); n.stop(t + 0.75);
        for (const det of [0, 13, -9]) {
          const o = ctx.createOscillator(), g2 = ctx.createGain();
          o.type = 'square'; o.frequency.value = 320 + det * 9; o.detune.value = det * 40;
          g2.gain.setValueAtTime(0.11, t + 0.02); g2.gain.exponentialRampToValueAtTime(0.001, t + 0.5);
          o.connect(g2); g2.connect(this.busSfx); o.start(t + 0.02); o.stop(t + 0.55);
        }
      } else if (ev === 'burnout') {
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.type = 'sawtooth'; o.frequency.setValueAtTime(220, t); o.frequency.exponentialRampToValueAtTime(880, t + 0.35);
        g.gain.setValueAtTime(0.22, t); g.gain.exponentialRampToValueAtTime(0.001, t + 0.45);
        o.connect(g); g.connect(this.busSfx); o.start(t); o.stop(t + 0.5);
      } else if (ev === 'wall') {
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.type = 'triangle'; o.frequency.setValueAtTime(180, t); o.frequency.exponentialRampToValueAtTime(70, t + 0.06);
        g.gain.setValueAtTime(0.25, t); g.gain.exponentialRampToValueAtTime(0.001, t + 0.09);
        o.connect(g); g.connect(this.busSfx); o.start(t); o.stop(t + 0.1);
      }
    }
  }

  S9.AudioSet = AudioSet;
})();