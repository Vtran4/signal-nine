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
      id: 'super', name: 'APEX GT1', cls: 'Super', clsName: 'APEX GT1',
      topSpeed: 91.5,            // ~205 mph
      boostTop: 106,             // ~237 mph — F-Zero territory
      accel: 12.5, brake: 18, engineBrake: 2.6,
      steerRate: 2.4, grip: 8.0, driftGrip: 3.2, driftYaw: 1.4,
      mass: 1080, paint: 0xf2f0e6, paintName: 'Apex White', flake: 0.65,
      wheelbase: 2.72, trackWidth: 1.66, rideHeight: 0.09,
    },
  ];

  const CFG = {
    MPH,
    params: {
      auto: bool('auto'),                       // bot drives (also attract mode)
      seed: num('seed', 1234),
      t: num('t', 0),                           // simulate to t seconds, then freeze
      view: inSet('view', ['chase', 'hood', 'bumper', 'crash', 'track'], 'chase'),
      track: inSet('track', ['coastal', 'downtown'], 'coastal'),
      state: q.get('state') || '',              // state jump: race | crash3 | results | boost | drive
      fx: q.get('fx') !== '0',                  // ?fx=0 disables the sense-of-speed pass
      lockres: bool('lockres'),                 // pin the dynamic-resolution scaler
      car: inSet('car', ['street', 'perf', 'super'], 'street'),
    },

    palette: {
      sky: 0x8fd0e8, skyLow: 0xffd9a0, fog: 0xbfe0ea, sun: 0xffe8c0,
      asphalt: 0x4a4f57, asphaltEdge: 0x394049, lane: 0xe8d75a,
      hill: 0xc9a44f, hillDark: 0x9c7a38, ocean: 0x2f8fb8,
      rail: 0xd8d8d2, post: 0x9a9a94,
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
      density: 14,              // cars kept alive around the player
      speedMin: 14, speedMax: 23,
      colors: [0xb8b2a6, 0x6f7d8c, 0x7a4f3a, 0x9aa77e, 0x51616f, 0xcfc7b8],
      nearMissCooldown: 1.2,
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