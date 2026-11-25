// Signal Nine — speedfx: THE sense-of-speed post stack (locked technique).
// One full-frame pass combining:
//   - radial motion blur (strength scales with velocity, stronger toward edges)
//   - subtle heat shimmer on the asphalt ahead at speed
//   - edge-anchored speed streaks while boosting
// FOV kick on boost is applied by the camera controller (game.js), not here.
// ?fx=0 bypasses the composer entirely (isolate rendering bugs).
window.S9 = window.S9 || {};
(function () {
  const SenseSpeedShader = {
    uniforms: {
      tDiffuse: { value: null },
      uTime: { value: 0 },
      uSpeed: { value: 0 },     // 0..1 normalized speed
      uBoost: { value: 0 },     // 0..1 eased boost intensity
      uAspect: { value: 1.78 },
      uCenter: { value: new THREE.Vector2(0.5, 0.42) }, // vanishing point
    },
    vertexShader: /* glsl */`
      varying vec2 vUv;
      void main() {
        vUv = uv;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }`,
    fragmentShader: /* glsl */`
      uniform sampler2D tDiffuse;
      uniform float uTime, uSpeed, uBoost, uAspect;
      uniform vec2 uCenter;
      varying vec2 vUv;

      // cheap 2-octave value noise for heat shimmer
      float h21(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
      float vnoise(vec2 p) {
        vec2 i = floor(p), f = fract(p);
        vec2 u = f * f * (3.0 - 2.0 * f);
        return mix(mix(h21(i), h21(i + vec2(1, 0)), u.x),
                   mix(h21(i + vec2(0, 1)), h21(i + vec2(1, 1)), u.x), u.y);
      }

      void main() {
        vec2 rel = vUv - uCenter;
        rel.x *= uAspect;
        float r = length(rel);
        vec2 dir = rel / max(r, 1e-4);

        // --- heat shimmer: only on the road band ahead (just below center) ---
        vec2 uv = vUv;
        float road = smoothstep(0.62, 0.45, vUv.y) * smoothstep(0.05, 0.22, vUv.y);
        if (road > 0.001) {
          vec2 np = vec2(vUv.x * 90.0, vUv.y * 14.0 - uTime * 2.6);
          float n = vnoise(np) - 0.5 + 0.5 * (vnoise(np * 2.7 + 31.7) - 0.5);
          uv.x += n * 0.0034 * (0.35 + uSpeed) * road;
          uv.y += n * 0.0017 * (0.35 + uSpeed) * road;
        }

        // --- radial motion blur: taps step toward the vanishing point ---
        float speed = uSpeed * (1.0 + uBoost * 0.9);
        float str = (0.010 + 0.055 * r * r) * speed;
        vec3 acc = texture2D(tDiffuse, uv).rgb * 0.5;
        for (int i = 1; i <= 8; i++) {
          float t = float(i) / 8.0;
          vec2 off = -dir * str * t;
          off.x /= uAspect;
          acc += texture2D(tDiffuse, uv + off).rgb * (0.5 / 8.0);
        }

        // --- edge-anchored speed streaks (boost only): radial smear + gain ---
        vec3 col = acc;
        float streakMask = smoothstep(0.28, 0.72, r);
        if (uBoost > 0.01 && streakMask > 0.001) {
          // post retune: two taps (near + far) with falloff — distinct elongated
          // streak lines instead of one diffuse smear (identity-stack verify read)
          vec2 soff = dir * (0.045 + 0.10 * r) * uBoost;
          soff.x /= uAspect;
          vec3 sm1 = texture2D(tDiffuse, uv + soff).rgb;
          vec3 sm2 = texture2D(tDiffuse, uv + soff * 1.9).rgb;
          float lum = dot(sm1, vec3(0.35, 0.5, 0.15));
          col += (sm1 + sm2 * 0.55) * streakMask * uBoost * (0.30 + 0.5 * lum);
        }

        // --- subtle 2002-style vignette that closes in with speed ---
        float vig = 1.0 - smoothstep(0.55, 1.05, r) * (0.22 + 0.20 * speed);
        col *= vig;

        gl_FragColor = vec4(col, 1.0);
      }`,
  };

  class SpeedFX {
    constructor(renderer, scene, camera, enabled, lit) {
      this.enabled = !!enabled;
      this.lit = !!lit;
      this.renderer = renderer;
      this.scene = scene;
      this.camera = camera;
      this.boostEase = 0;
      if (!this.enabled || typeof THREE.EffectComposer === 'undefined') {
        this.enabled = false;
        this.composer = null;
        return;
      }
      this.composer = new THREE.EffectComposer(renderer);
      this.composer.addPass(new THREE.RenderPass(scene, camera));
      this.pass = new THREE.ShaderPass(SenseSpeedShader);
      this.composer.addPass(this.pass);
      // WS-B1e: bright-pass bloom under the lit pipeline only — emissive
      // windows/taillights/neon need the glow to sell night; the certified
      // compose look ships without it. UnrealBloomPass is in the bundle
      // (no rebuild); threshold sits high so only HDR-bright content blooms.
      if (this.lit && THREE.UnrealBloomPass) {
        this.bloom = new THREE.UnrealBloomPass(
          new THREE.Vector2(innerWidth || 1280, innerHeight || 720),
          0.4,   // strength
          0.5,   // radius
          0.85); // threshold — HDR-bright only (emissives, sky highlights)
        this.composer.addPass(this.bloom);
      }
      if (THREE.OutputPass) this.composer.addPass(new THREE.OutputPass());
      this.resize(innerWidth || 1280, innerHeight || 720);
    }

    // speedNorm: 0..1 of top speed; boostK: 0..1 raw boost-active indicator
    update(dt, speedNorm, boostK, time) {
      if (!this.enabled) return;
      // attack fast, release slow — streaks bloom in and linger out
      const target = boostK > 0.5 ? 1 : 0;
      this.boostEase += (target - this.boostEase) * (target > this.boostEase ? Math.min(1, dt * 7) : Math.min(1, dt * 2.2));
      const u = this.pass.uniforms;
      u.uTime.value = time;
      u.uSpeed.value = S9.util.clamp(speedNorm, 0, 1.15);
      u.uBoost.value = this.boostEase;
    }

    // css dimensions; composer tracks the renderer's pixel ratio itself
    resize(w, h) {
      if (!this.enabled) return;
      this.composer.setPixelRatio(this.renderer.getPixelRatio());
      this.composer.setSize(w, h);
      this.pass.uniforms.uAspect.value = w / Math.max(1, h);
    }

    render() {
      if (this.enabled) this.composer.render();
      else this.renderer.render(this.scene, this.camera);
    }
  }

  S9.SpeedFX = SpeedFX;
})();