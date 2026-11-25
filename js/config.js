// Signal Nine — config: URL params, palette, car classes, tuning constants.
window.S9 = window.S9 || {};
(function () {
  const q = new URLSearchParams(location.search);
  const num = (k, d) => { const v = parseFloat(q.get(k)); return Number.isFinite(v) ? v : d; };
  const bool = (k) => q.get(k) === '1' || q.get(k) === 'true';
  const inSet = (k, set, d) => { const v = q.get(k); return set.includes(v) ? v : d; };

  const MPH = 2.23694; // m/s -> mph

  // The three M1 hero cars, one per class. Feel per design doc:
  //   Street: forgiving, drifty. Performance: sharp, faster rotation. Super: brutal speed.
  const CARS = [
    {
      id: 'street', name: 'VANTORO RS', cls: 'Street', clsName: 'VANTORO RS',
      topSpeed: 62.5,            // ~140 mph
      boostTop: 72,              // ~161 mph on boost
      accel: 9.0, brake: 16, engineBrake: 2.2,
      steerRate: 1.9, grip: 6.0, driftGrip: 2.6, driftYaw: 1.15,
      mass: 1240, paint: 0xd8452e, paintName: 'Signal Red', flake: 0.35,
      wheelbase: 2.45, trackWidth: 1.56, rideHeight: 0.12, // modeler blockout measurements
    },
    {
      id: 'perf', name: 'KESTREL MR', cls: 'Performance', clsName: 'KESTREL MR',
      topSpeed: 76,              // ~170 mph
      boostTop: 87,
      accel: 10.5, brake: 17, engineBrake: 2.4,
      steerRate: 2.25, grip: 7.0, driftGrip: 2.9, driftYaw: 1.3,
      mass: 1150, paint: 0x2fb7a9, paintName: 'Kestrel Teal', flake: 0.5,
      wheelbase: 2.60, trackWidth: 1.64, rideHeight: 0.10,
    },
    {
      id: 'gt3', name: 'VANTORO GT3-E', cls: 'Super', clsName: 'VANTORO GT3-E',
      topSpeed: 88,              // ~197 mph — GT3-class: fast, sharp, less brutal than GT1
      boostTop: 101,
      accel: 11.5, brake: 18, engineBrake: 2.6,
      steerRate: 2.5, grip: 8.2, driftGrip: 3.0, driftYaw: 1.35,
      mass: 1120, paint: 0xc81e14, paintName: 'Vantoro Factory Red', flake: 0.4,
      wheelbase: 2.60, trackWidth: 2.00, rideHeight: 0.10, // modeler WS-A locked ratios (L 4.55 / WB 2.60 / W 2.0)
    },
    {
      id: 'super', name: 'APEX GT1', cls: 'Super', clsName: 'APEX GT1',
      topSpeed: 91.5,            // ~205 mph
      boostTop: 106,             // ~237 mph — F-Zero territory
      accel: 12.5, brake: 18, engineBrake: 2.6,
      steerRate: 2.4, grip: 8.0, driftGrip: 3.2, driftYaw: 1.4,
      mass: 1080, paint: 0xf2f0e6, paintName: 'Apex White', flake: 0.65,
      wheelbase: 2.72, trackWidth: 1.66, rideHeight: 0.09,
    },
    { // Pursuit cruiser (M2) — heavy, tall, modest top end; ?car=police to drive it
      id: 'police', name: 'INTERCEPTOR', cls: 'Pursuit', clsName: 'INTERCEPTOR',
      topSpeed: 70,              // ~157 mph
      boostTop: 80,
      accel: 9.5, brake: 15, engineBrake: 2.2,
      steerRate: 1.75, grip: 6.6, driftGrip: 2.7, driftYaw: 1.1,
      mass: 1620, paint: 0xf2f2f0, paintName: 'Patrol White', flake: 0.2,
      wheelbase: 2.95, trackWidth: 1.62, rideHeight: 0.14,
      police: true,             // beacon alternation + slot mapping in buildCarFromGltf
    },
  ];

  const CFG = {
    MPH,
    params: {
      auto: bool('auto'),                       // bot drives (also attract mode)
      seed: num('seed', 1234),
      t: num('t', 0),                           // simulate to t seconds, then freeze
      view: inSet('view', ['chase', 'hood', 'bumper', 'crash', 'track'], 'chase'),
      track: inSet('track', ['coastal', 'downtown', 'canyon'], 'coastal'),
      state: q.get('state') || '',              // state jump: race | crash3 | results | boost | drive
      fx: q.get('fx') !== '0',                  // ?fx=0 disables the sense-of-speed pass
      lockres: bool('lockres'),                 // pin the dynamic-resolution scaler
      lit: q.get('lit') !== '0',                // Phase 2.0 WS-B1 lit pipeline is the DEFAULT
                                                // (landed); ?lit=0 preserves the certified M1
                                                // compose path for A/B evidence
      car: inSet('car', ['street', 'perf', 'super', 'gt3', 'police'], 'street'),
    },

    palette: {
      sky: 0x8fd0e8, skyLow: 0xffd9a0, fog: 0xbfe0ea, sun: 0xffe8c0,
      asphalt: 0x4a4f57, asphaltEdge: 0x394049, lane: 0xe8d75a,
      hill: 0xc9a44f, hillDark: 0x9c7a38, ocean: 0x2f8fb8,
      rail: 0xd8d8d2, post: 0x9a9a94,
    },

    // WS-B1b per-track light rigs — applied ONLY under ?lit=1 (the certified
    // compose path keeps the M1 daytime look; cars are live-lit in both paths,
    // so un-flagged rigs would leak into it). Values tune the existing
    // hemisphere + directional pair, fog color, and the pano background
    // intensity (night dims the daytime pano until real night panos exist —
    // modeler's WS-B2 night-env capture is the proper fix).
    lightRigs: {
      coastal: null,            // certified daytime — rig = current scene values
      downtown: {               // permanent-night kit target: neon-lit dark city
        hemiSky: 0x2a3448, hemiGround: 0x1a1610, hemiI: 0.32,
        sunI: 0.35, sunColor: 0x8fa8d8, sunPos: [-160, 220, 90],  // moon
        fog: 0x11141c, bgIntensity: 0.18,
        emissiveI: 1.0,         // WS-B1c: procedural lit windows on at night
        neonI: 2.0,             // WS-B2 neon signs: read hotter than window interiors
        // B1b2: swap the near-white pano dome for the procedural gradient sky
        // (the pano dominates luminance at any intensity — verified); IBL from
        // the daytime pano drops to near-zero (night has no daylight bounce)
        useProceduralSky: true, skyTop: 0x0a0e1a, skyLow: 0x1a2233, envI: 0.08,
      },
      canyon: {                 // golden-hour red-rock target
        hemiSky: 0xffd9b0, hemiGround: 0x7a4a2a, hemiI: 0.75,
        sunI: 2.6, sunColor: 0xffb060, sunPos: [420, 180, -240],  // low warm sun
        fog: 0xe8c8a0, bgIntensity: 0.8,
        emissiveI: 0.15,        // a few lit windows at dusk
        neonI: 0.4,             // dusk neon: dimmed
        useProceduralSky: true, skyTop: 0x88a8d8, skyLow: 0xffb870, envI: 0.5,
      },
    },

    // --- the golden rule: boost is earned ONLY by danger ---
    boost: {
      triggerAt: 0.99,          // meter must be full to activate
      drainPerSec: 0.16,        // meter burn while boosting
      earn: {
        oncoming: 0.105,        // per second, sustained, in the oncoming lane
        nearMiss: 0.10,         // instant chunk per near-miss
        drift: 0.085,           // per second while powersliding at speed
        air: 0.05,              // per second airborne + landing bonus below
        airLanding: 0.10,       // per 0.5s of air on touchdown
      },
      hopVy: 3.7,               // Option 1 arcade-hop impulse (ruling 2026-11-24):
                                // crest triggers floor at this vy -> ~0.75s airtime
                                // on every track, not just physically-sharp crests
      oncomingMinSpeed: 20,     // m/s before oncoming registers
      driftMinSpeed: 16, driftMinSlip: 0.24,
      nearMissGap: 2.35,        // max lateral gap (m) that still counts
      nearMissRelSpeed: 5,      // min closing/passing speed (m/s)
    },

    track: {
      width: 10, halfW: 5, laneOffset: 2.5,
      spacing: 2.0,             // arc-length sample spacing (m) — matches modeler contract
      guardrail: true,
    },

    traffic: {
      density: 20,               // cars kept alive around the player (6-lane roads)
      speedMin: 14, speedMax: 23,
      colors: [0xb8b2a6, 0x6f7d8c, 0x7a4f3a, 0x9aa77e, 0x51616f, 0xcfc7b8],
      nearMissCooldown: 1.2,
      // Downtown Sprint section config (spec §2/§3, committed ab77e46) — consumed
      // by traffic.js when track.id === 'downtown'. Zones BIAS respawns toward
      // the named s-ranges (w = weight); excludes veto any spawn inside them.
      sprintZones: [
        { from: 120,  to: 280,  kind: 'pocket',   w: 3 },   // S1 opening near-miss pocket
        { from: 200,  to: 300,  kind: 'junction', w: 2 },   // pre-J1 corridor
        { from: 800,  to: 902,  kind: 'junction', w: 2 },   // pre-J2 corridor
        { from: 940,  to: 1360, kind: 'oncoming', w: 3 },   // S3 oncoming corridor
        { from: 1080, to: 1340, kind: 'pocket',   w: 3 },   // S3 3-4 car pocket
        { from: 1310, to: 1414, kind: 'junction', w: 2 },   // pre-J3 corridor
        { from: 2350, to: 2540, kind: 'pocket',   w: 3 },   // S5 descent run-in
        { from: 2480, to: 2586, kind: 'junction', w: 2 },   // pre-J4 corridor
      ],
      sprintExcludes: [         // junction clean bubbles (s ±30) + S4 crest air runway
        { from: 270,  to: 330 },
        { from: 872,  to: 932 },
        { from: 1384, to: 1444 },
        { from: 2556, to: 2616 },
        { from: 1850, to: 2080 },
      ],
    },

    physics: {
      wallScrub: 0.965,         // speed retained per wall contact frame
      grazeScrub: 0.80,         // speed retained on a graze (light contact)
      crashRelSpeed: 13,        // closing speed (m/s) above which a hit is a crash
      dtMax: 0.05,
    },

    camera: {
      fov: 62, fovBoostKick: 13,
      chaseDist: 6.4, chaseDistSpeed: 2.6, chaseHeight: 2.6, lookAhead: 7,
      shake: 0.05,
    },

    fpsGate: { target: 60, scaleMin: 0.55, scaleMax: 1.0, msHigh: 18.5, msLow: 13.0 },
  };

  S9.CFG = CFG;
  S9.CARS = CARS;
})();