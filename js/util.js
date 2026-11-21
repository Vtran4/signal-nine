// Signal Nine — util: seeded RNG, math helpers, DOM/format helpers.
window.S9 = window.S9 || {};
(function () {
  // mulberry32 — small, fast, seedable; ?seed=<n> makes runs repeatable.
  function rng(seed) {
    let a = seed >>> 0;
    const f = function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    f.range = (lo, hi) => lo + (hi - lo) * f();
    f.pick = (arr) => arr[Math.floor(f() * arr.length) % arr.length];
    return f;
  }

  const clamp = (v, lo, hi) => v < lo ? lo : v > hi ? hi : v;
  const lerp = (a, b, t) => a + (b - a) * t;
  const smooth = (t) => t * t * (3 - 2 * t);
  const easeOut = (t) => 1 - Math.pow(1 - t, 3);

  // shortest signed angle difference, result in [-PI, PI]
  function angDiff(a, b) {
    let d = (a - b) % (Math.PI * 2);
    if (d > Math.PI) d -= Math.PI * 2;
    if (d < -Math.PI) d += Math.PI * 2;
    return d;
  }

  const fmtMph = (ms) => Math.round(ms * 2.23694);
  function fmtDollars(n) {
    n = Math.max(0, Math.round(n));
    return '$' + n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  }

  // one-shot DOM event popup (NEAR MISS / ONCOMING / BURNOUT xN …)
  let eventTimer = 0;
  function showEvent(text, big) {
    const el = document.getElementById('event');
    if (!el) return;
    el.textContent = text;
    el.style.fontSize = big ? '46px' : '34px';
    el.classList.remove('pop');
    void el.offsetWidth; // restart animation
    el.classList.add('pop');
  }

  S9.util = { rng, clamp, lerp, smooth, easeOut, angDiff, fmtMph, fmtDollars, showEvent };
})();