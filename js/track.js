// Signal Nine — track: spline world (greybox v0; consumes tracks_data.json contract later).
// Phase 0 builds a procedural closed coastal-style loop at 2m arc-length spacing —
// the same sampler API the real spline JSON will feed, so nothing upstream changes.
window.S9 = window.S9 || {};
(function () {
  const { clamp, lerp, rng } = S9.util;

  // --- baked-static compose material (ported from the proven Cork Gallery shader) ---
  // albedo sRGB + linear light map, unlit: color = albedo * rolloff(light) * gain + ambient
  S9.composeMaterial = function (albedoTex, lightTex, gain = 2.4, ambient = 0.12, mipBias = 1.2) {
    const mat = new THREE.ShaderMaterial({
      uniforms: THREE.UniformsUtils.merge([
        THREE.UniformsLib.fog,
        {
          uAlbedo: { value: albedoTex },
          uLight: { value: lightTex },
          uLightGain: { value: gain },
          uAmbient: { value: ambient },
          uMipBias: { value: mipBias },
        },
      ]),
      fog: true,  // distant statics must haze into the horizon like Lambert does
      vertexShader: `
        varying vec2 vUv;
        #include <fog_pars_vertex>
        void main() {
          vUv = uv;
          vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
          gl_Position = projectionMatrix * mvPosition;
          #include <fog_vertex>
        }`,
      fragmentShader: `
        uniform sampler2D uAlbedo;
        uniform sampler2D uLight;
        uniform float uLightGain;
        uniform float uAmbient;
        uniform float uMipBias;
        varying vec2 vUv;
        #include <fog_pars_fragment>
        void main() {
          vec3 alb = texture2D(uAlbedo, vUv, uMipBias).rgb;
          vec3 l = texture2D(uLight, vUv).rgb;
          l = l / (l + 0.55);   // gentle rolloff keeps hot bakes in range
          gl_FragColor = vec4(alb * (l * uLightGain + uAmbient), 1.0);
          #include <fog_fragment>
        }`,
    });
    // UniformsUtils.merge clones values — rebind textures so the live
    // Texture objects (with their colorSpace/anisotropy settings) are used
    mat.uniforms.uAlbedo.value = albedoTex;
    mat.uniforms.uLight.value = lightTex;
    return mat;
  };

  // Apply bake.py's manifest: node lists -> atlas group materials. Returns a
  // promise for the number of meshes swapped. loadTex(name, srgb) supplied by main.
  S9.applyBakedStatics = function (staticRoot, manifest, loadTex) {
    const groups = manifest.atlas_groups || {};
    const nodeToGroup = {};
    for (const g in groups) for (const n of groups[g].nodes || []) nodeToGroup[n] = g;
    const GAIN = { coastal: 2.4, props: 2.2 };
    return Promise.all(Object.keys(groups).map((g) =>
      Promise.all([loadTex(groups[g].albedo, true), loadTex(groups[g].light, false)])
        .then(([a, l]) => [g, S9.composeMaterial(a, l, GAIN[g] || 2.4, 0.12)])
    )).then((pairs) => {
      const mats = {};
      for (const [g, m] of pairs) mats[g] = m;
      let swapped = 0;
      staticRoot.traverse((o) => {
        if (o.isMesh && o.name && nodeToGroup[o.name]) {
          o.material = mats[nodeToGroup[o.name]];
          swapped++;
        }
      });
      return swapped;
    });
  };

  class Track {
    constructor(scene, seed, data) {
      this.scene = scene;
      this.spacing = S9.CFG.track.spacing;   // 2m — matches modeler contract
      this.halfW = S9.CFG.track.halfW;
      this.laneOffset = S9.CFG.track.laneOffset;
      this.closed = true;                    // coastal circuit = closed loop

      if (data) {
        this.#buildFromData(data);           // real spline from tracks_data.json
        this.hasGlbStatics = false;          // main.js flips this when tracks.glb lands
      } else {
        this.#buildSpline();
        this.#buildRoad();
        this.#buildRails();
        this.#buildSurrounds(seed);
      }
      this.#buildSky();
    }

    // --- consume modeler-s9's tracks_data.json entry ---
    // Sign convention: their laterals are LEFT-of-travel positive; ours are
    // RIGHT-of-tangent positive — negate at load. With-traffic lanes land on
    // our positive side (+1.2/+3.6), oncoming on negative (-1.2/-3.6).
    #buildFromData(entry) {
      const pts = entry.centerline;
      const N = pts.length;
      this.count = N;
      this.length = N * this.spacing;
      this.closed = !!entry.closed;
      this.px = new Float32Array(N); this.py = new Float32Array(N); this.pz = new Float32Array(N);
      this.tx = new Float32Array(N); this.tz = new Float32Array(N);
      this.yaw = new Float32Array(N);
      for (let n = 0; n < N; n++) {
        this.px[n] = pts[n][0]; this.py[n] = pts[n][1]; this.pz[n] = pts[n][2];
      }
      for (let n = 0; n < N; n++) {
        const a = (n - 1 + N) % N, b = (n + 1) % N;
        const dx = this.px[b] - this.px[a], dz = this.pz[b] - this.pz[a];
        const l = Math.hypot(dx, dz) || 1;
        this.tx[n] = dx / l; this.tz[n] = dz / l;
        this.yaw[n] = Math.atan2(this.tx[n], this.tz[n]);
      }
      if (entry.roadWidth) this.halfW = entry.roadWidth / 2;
      // lanes, negated into our right-positive convention
      const mine = (entry.lanes || [-3.6, -1.2, 1.2, 3.6]).map(l => -l).sort((a, b) => a - b);
      this.lanesWith = mine.filter(l => l > 0);   // [1.2, 3.6] inner→outer
      this.lanesOpp = mine.filter(l => l < 0);    // [-3.6, -1.2]
      this.laneOffset = this.lanesWith[this.lanesWith.length - 1];  // traffic rides outer
      this.laneOncoming = this.lanesOpp[0];       // traffic oncoming = outer
      this.laneDodge = this.lanesOpp[this.lanesOpp.length - 1];     // bot dodge = inner oncoming
      this.laneSqueeze = 0.5;                     // squeeze-pass line between lanes
      this.furniture = entry.furniture || [];
      this.junctions = entry.junctions || [];
      this.name = entry.name || 'track';
      this.id = entry.id || 'track';
    }

    // --- dense closed loop, resampled to exact 2m arc-length spacing ---
    #buildSpline() {
      const M = 2048, pts = [];
      let prev = null, total = 0;
      for (let i = 0; i <= M; i++) {
        const th = (i / M) * Math.PI * 2;
        const r = 420 + 55 * Math.sin(3 * th + 0.7) + 38 * Math.sin(7 * th + 2.1);
        const y = 2.2 * Math.sin(2 * th + 0.5);
        const p = new THREE.Vector3(Math.cos(th) * r, y, Math.sin(th) * r);
        if (prev) total += p.distanceTo(prev);
        pts.push(p); prev = p;
      }
      // last point duplicates the first (closed) — drop it after using its length
      total += pts[0].distanceTo(pts[pts.length - 2]);
      pts.pop();

      const N = Math.max(64, Math.round(total / this.spacing));
      this.count = N;
      this.length = N * this.spacing;
      this.px = new Float32Array(N); this.py = new Float32Array(N); this.pz = new Float32Array(N);
      this.tx = new Float32Array(N); this.tz = new Float32Array(N); // tangents are horizontal
      this.yaw = new Float32Array(N);

      // walk the dense polyline at uniform arc steps
      let seg = 0, segLen = pts[0].distanceTo(pts[1 % pts.length]), acc = 0;
      for (let n = 0; n < N; n++) {
        const target = n * this.spacing;
        while (acc + segLen < target && seg < pts.length) {
          acc += segLen; seg++;
          const a = pts[seg % pts.length], b = pts[(seg + 1) % pts.length];
          segLen = a.distanceTo(b);
        }
        const f = segLen > 0 ? clamp((target - acc) / segLen, 0, 1) : 0;
        const a = pts[seg % pts.length], b = pts[(seg + 1) % pts.length];
        this.px[n] = lerp(a.x, b.x, f); this.py[n] = lerp(a.y, b.y, f); this.pz[n] = lerp(a.z, b.z, f);
      }
      // tangents from neighbors (closed: seam handled by wrap; open: one-sided at ends)
      for (let n = 0; n < N; n++) {
        const a = this.closed ? (n - 1 + N) % N : Math.max(0, n - 1);
        const b = this.closed ? (n + 1) % N : Math.min(N - 1, n + 1);
        const dx = this.px[b] - this.px[a], dz = this.pz[b] - this.pz[a];
        const l = Math.hypot(dx, dz) || 1;
        this.tx[n] = dx / l; this.tz[n] = dz / l;
        this.yaw[n] = Math.atan2(this.tx[n], this.tz[n]);
      }
    }

    #wrapI(i) {
      if (this.closed) return ((i % this.count) + this.count) % this.count;
      return clamp(i, 0, this.count - 1); // point-to-point: clamp, never wrap
    }

    // interpolate sample at fractional sample-index
    #mix(aProp, i) {
      const i0 = Math.floor(i), f = i - i0;
      const a = this[aProp][this.#wrapI(i0)], b = this[aProp][this.#wrapI(i0 + 1)];
      return lerp(a, b, f);
    }
    sToIndex(s) {
      const i = s / this.spacing;
      return this.closed ? i % this.count : clamp(i, 0, this.count - 1.001);
    }

    posAt(s, lateral = 0, out = new THREE.Vector3()) {
      const i = this.sToIndex(s);
      out.set(this.#mix('px', i), this.#mix('py', i), this.#mix('pz', i));
      if (lateral !== 0) {
        const yawv = this.#mix('yaw', i);
        out.x += Math.sin(yawv + Math.PI / 2) * lateral * -1; // right of tangent
        out.z += Math.cos(yawv + Math.PI / 2) * lateral * -1;
      }
      return out;
    }
    tangentYawAt(s) { return this.#mix('yaw', this.sToIndex(s)); }
    curvatureAt(s) {
      const i = this.sToIndex(s);
      const d = Math.abs(S9.util.angDiff(this.#mix('yaw', i + 4), this.#mix('yaw', i - 4))) / (8 * this.spacing);
      return d; // rad per meter
    }

    // project a world position onto the spline (local search around hintS)
    project(p, hintS) {
      const ci = Math.round(this.sToIndex(hintS));
      let best = -1, bestD = Infinity;
      for (let k = -24; k <= 24; k++) {
        const n = this.#wrapI(ci + k);
        const dx = p.x - this.px[n], dz = p.z - this.pz[n];
        const d = dx * dx + dz * dz;
        if (d < bestD) { bestD = d; best = n; }
      }
      // refine with projection onto the two adjacent segments
      const s0 = best * this.spacing;
      const yawv = this.yaw[best];
      const fx = p.x - this.px[best], fz = p.z - this.pz[best];
      const along = fx * this.tx[best] + fz * this.tz[best];
      // lateral = dot(offset, right); right = (-cos yaw, 0, sin yaw)
      const side = fx * -Math.cos(yawv) + fz * Math.sin(yawv);
      return { s: s0 + along, lateral: side, tangentYaw: yawv, index: best };
    }

    // fallback meshes when tracks.glb is unavailable (greybox under-layer)
    buildProceduralMeshes(seed) {
      if (this._built) return;
      this._built = true;
      this.#buildRoad();
      this.#buildRails();
      this.#buildSurrounds(seed || 1234);
    }

    // LOD policy: base mesh < 160m, _lod1 < 420m, _lod2 beyond. Heads follow
    // their pole base. Called from the render loop (throttled).
    collectLodGroups() {
      const groups = {};
      this.staticRoot.traverse((o) => {
        if (!o.isMesh || !o.name) return;
        const key = o.name.replace(/_head$/, '').replace(/_lod[12]$/, '');
        const lod = o.name.endsWith('_lod1') ? 1 : o.name.endsWith('_lod2') ? 2 : 0;
        (groups[key] = groups[key] || { meshes: [[], [], []] }).meshes[lod].push(o);
      });
      this.lodGroups = [];
      for (const key in groups) {
        const g = groups[key];
        if (!g.meshes[1].length && !g.meshes[2].length) continue; // no LOD variants
        const box = new THREE.Box3().setFromObject(g.meshes[0][0] || g.meshes[1][0]);
        const center = box.getCenter(new THREE.Vector3());
        this.lodGroups.push({ key, center, meshes: g.meshes });
      }
      return this.lodGroups.length;
    }

    applyLod(camPos) {
      if (!this.lodGroups) return;
      for (const g of this.lodGroups) {
        const d = camPos.distanceTo(g.center);
        const vis = [d < 160, d >= 160 && d < 420, d >= 420];
        for (let i = 0; i < 3; i++) for (const m of g.meshes[i]) m.visible = vis[i];
      }
    }
    #buildRoad() {
      const N = this.count, hw = this.halfW;
      const pos = [], uv = [], idx = [];
      for (let n = 0; n < N; n++) {
        const yawv = this.yaw[n];
        // right of tangent = (-cos yaw, 0, sin yaw)  [cross(forward, up)]
        const rx = -Math.cos(yawv), rz = Math.sin(yawv);
        const s = n * this.spacing;
        // top surface: left edge, right edge (+2 skirt verts share the road u)
        pos.push(this.px[n] + rx * -hw, this.py[n], this.pz[n] + rz * -hw);
        pos.push(this.px[n] + rx * hw, this.py[n], this.pz[n] + rz * hw);
        pos.push(this.px[n] + rx * -hw, this.py[n] - 3, this.pz[n] + rz * -hw);
        pos.push(this.px[n] + rx * hw, this.py[n] - 3, this.pz[n] + rz * hw);
        // uv for ALL 4 verts (TL, TR, BL, BR) — attribute count must match position count
        uv.push(s / 8, 0, s / 8, 1, s / 8, 0, s / 8, 1);
      }
      for (let n = 0; n < N; n++) {
        const a = n * 4, b = this.#wrapI(n + 1) * 4;
        if (!this.closed && b === a) break; // point-to-point: no wrap quad at the finish
        // road top (up-facing: r × f = up)
        idx.push(a, a + 1, b, a + 1, b + 1, b);
        // left skirt (faces -right), right skirt (faces +right)
        idx.push(a, b, a + 2, a + 2, b + 2, b);
        idx.push(a + 1, a + 3, b + 1, a + 3, b + 3, b + 1);
      }
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
      g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
      g.setIndex(idx); g.computeVertexNormals();

      const cv = document.createElement('canvas'); cv.width = 128; cv.height = 128;
      const cx = cv.getContext('2d');
      cx.fillStyle = '#4a4f57'; cx.fillRect(0, 0, 128, 128);
      // faint asphalt noise
      for (let i = 0; i < 900; i++) {
        cx.fillStyle = Math.random() > 0.5 ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.05)';
        cx.fillRect(Math.random() * 128, Math.random() * 128, 2, 2);
      }
      // double-yellow centerline
      cx.fillStyle = '#e8d75a';
      cx.fillRect(62, 0, 2, 128); cx.fillRect(66, 0, 2, 128);
      // white edge lines
      cx.fillStyle = '#dcdcd6';
      cx.fillRect(5, 0, 3, 128); cx.fillRect(120, 0, 3, 128);
      const tex = new THREE.CanvasTexture(cv);
      tex.wrapS = THREE.RepeatWrapping; tex.wrapT = THREE.ClampToEdgeWrapping;
      tex.colorSpace = THREE.SRGBColorSpace;
      tex.anisotropy = 4;

      this.roadMat = new THREE.MeshLambertMaterial({ map: tex });
      this.road = new THREE.Mesh(g, this.roadMat);
      this.road.frustumCulled = false;
      this.scene.add(this.road);
    }

    #buildRails() {
      const step = 8, per = Math.floor(this.count * this.spacing / step);
      const geo = new THREE.BoxGeometry(0.12, 0.35, 2.0);
      const mat = new THREE.MeshLambertMaterial({ color: S9.CFG.palette.rail });
      const inst = new THREE.InstancedMesh(geo, mat, per * 2);
      const m = new THREE.Matrix4(), q = new THREE.Quaternion(), up = new THREE.Vector3(0, 1, 0);
      let k = 0;
      for (let i = 0; i < per && k < per * 2; i++) {
        const s = i * step, yawv = this.tangentYawAt(s);
        q.setFromAxisAngle(up, yawv);
        for (const side of [-1, 1]) {
          const p = this.posAt(s, side * (this.halfW + 0.55));
          p.y += 0.5;
          m.compose(p, q, new THREE.Vector3(1, 1, 1));
          inst.setMatrixAt(k++, m);
        }
      }
      inst.count = k;
      inst.instanceMatrix.needsUpdate = true;
      inst.frustumCulled = false;
      this.scene.add(inst);
    }

    #buildSurrounds(seed) {
      // scattered greybox blocks for parallax (blur needs things to smear)
      const r = rng(seed ^ 0x9e37);
      const geo = new THREE.BoxGeometry(1, 1, 1);
      const matA = new THREE.MeshLambertMaterial({ color: S9.CFG.palette.hill });
      const matB = new THREE.MeshLambertMaterial({ color: S9.CFG.palette.hillDark });
      const n = 90;
      const instA = new THREE.InstancedMesh(geo, matA, n);
      const instB = new THREE.InstancedMesh(geo, matB, n);
      const m = new THREE.Matrix4(), q = new THREE.Quaternion(), up = new THREE.Vector3(0, 1, 0);
      let a = 0, b = 0;
      for (let i = 0; i < n * 3 && (a < n || b < n); i++) {
        const s = r() * this.length;
        const p = this.posAt(s, (r() < 0.5 ? -1 : 1) * (24 + r() * 160));
        if (Math.abs(p.x) > 1400 || Math.abs(p.z) > 1400) continue;
        const w = 6 + r() * 22, h = 4 + r() * 26, d = 6 + r() * 22;
        q.setFromAxisAngle(up, r() * Math.PI);
        p.y += h / 2 - 1;
        m.compose(p, q, new THREE.Vector3(w, h, d));
        if (a < n && r() < 0.6) instA.setMatrixAt(a++, m);
        else if (b < n) instB.setMatrixAt(b++, m);
      }
      instA.count = a; instB.count = b;
      instA.instanceMatrix.needsUpdate = true; instB.instanceMatrix.needsUpdate = true;
      instA.frustumCulled = false; instB.frustumCulled = false;
      this.scene.add(instA); this.scene.add(instB);

      // ground plane
      const ground = new THREE.Mesh(
        new THREE.CircleGeometry(2400, 48),
        new THREE.MeshLambertMaterial({ color: 0x8fa06a }));
      ground.rotation.x = -Math.PI / 2;
      ground.position.y = -3.2;
      this.scene.add(ground);
    }

    #buildSky() {
      const geo = new THREE.SphereGeometry(3000, 24, 12);
      const mat = new THREE.ShaderMaterial({
        side: THREE.BackSide, depthWrite: false,
        uniforms: {
          top: { value: new THREE.Color(S9.CFG.palette.sky) },
          low: { value: new THREE.Color(S9.CFG.palette.skyLow) },
        },
        vertexShader: `varying vec3 vP; void main(){ vP = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`,
        fragmentShader: `uniform vec3 top, low; varying vec3 vP;
          void main(){ float t = clamp(vP.y / 3000.0 * 1.6 + 0.28, 0.0, 1.0); gl_FragColor = vec4(mix(low, top, pow(t, 0.8)), 1.0); }`,
      });
      this.sky = new THREE.Mesh(geo, mat);
      this.sky.frustumCulled = false;
      this.scene.add(this.sky);
    }
  }

  S9.Track = Track;
})();