# Signal Nine — Downtown Sprint: Section Config Spec

Status: PROPOSAL — OWNER: coder-s9 (gameplay/track config); reviewers: modeler-s9, pm-s9, Victor; authored by room-side session (unconfirmed). Zero-code deliverable written
under the texture-fix freeze; nothing in `js/` or `tools/` was touched.
Grounded in: `assets/tracks_data.json` (downtown entry), `js/track.js`, `js/modes.js`,
`js/bot.js`, `js/cars.js`, `js/config.js` as of `b249c78`.

Track facts (measured from tracks_data.json, not estimated):

| Property | Value |
|---|---|
| id / name | `downtown` / "Downtown Sprint" |
| topology | point-to-point (`closed: false`), 1505 samples @ 2 m = **3010 m** |
| roadWidth | 15 m → 6 lanes @ 2.5 m (ours: with-traffic +1.25/+3.75/+6.25, oncoming −1.25/−3.75/−6.25) |
| crash junctions | s=300 (arm 44), s=902 (arm 52), s=1414 (arm 56), s=2586 (arm 64) |
| furniture | 8 signals (2 per junction), 26 poles @ 80 m rhythm (lat ±6.6), 1 start gantry at s=0 |
| elevation | flat ~0.2 m to s≈1500; climbs to 9.7 m by s≈2000 (peak grade +3.4%); drops back to ~0 m by s≈2500 (peak −2.9%); flat to finish |
| curvature | never tight — max sustained ≈0.004 rad/m. It is a speed rhythm track: straight → sweeper chain → straight → climb → drop → straight |
| sprint rules | Race laps = 1 (`modes.js`: `closed ? 2 : 1`); finish at s ≥ L−12 = **2998 m** |

Design intent (from the design doc): downtown = "one-ways" — a full-throttle one-way
sprint where the boost economy is the gameplay. Sections below are named for the
rhythm the measured geometry already has; **no spline/geometry changes required.**

---

## 1. Section breakdown (s = meters along spline)

### S1 — Launch Grid · s 0–300
- Dead straight (curv ≤0.0008), start gantry at s=0, grid at s≈54 (see §4 grid fix).
- Character: clean launch, HUD settles, first traffic sighted ahead.
- Earners: **opening near-miss pocket** (traffic density bump s 120–280). Meter starts
  at 0; the pocket exists so the meter is moving before the first sweeper.
- J1 (s=300) closes the section: signalized crossing, pass-through in Race.

### S2 — The Long Sweep · s 300–902
- The track's defining corner chain: sustained gentle sweepers s 400–900
  (mean curv 0.0026–0.0041, peak window s 600–800). J2 (s=902) ends it.
- Character: the **drift-earn stretch**. Inside line + handbrake tap holds a
  powerslide (drift 0.085/s → full meter in ~11.7 s of sliding); the outer
  oncoming lane is the alternate earn line on the straighter links (oncoming
  0.105/s → full in ~9.5 s).
- Earners: drift geometry comes free from the spline. Traffic: light, spread in the
  with-traffic lanes; **keep −1.25 (inner oncoming / bot dodge line) clear** per the
  E5 rule; keep the squeeze/pass lane viable (see §5 laneSqueeze flag).
- J2 pass-through at section end.

### S3 — Midtown Run · s 902–1414
- Longest junction gap (512 m), gently easing bend (curv 0.0017–0.0033).
- Character: **oncoming-lane corridor** — straight sightlines where the player
  banks oncoming time; the classic "wrong side of the road" downtown moment.
- Earners: oncoming corridor 940–1360; one 3–4 car near-miss pocket s 1080–1340
  in the with-traffic lanes (pacing: the player should reach ~60–80% meter here if
  they took the drift line in S2 — the corridor is what tips it over trigger 0.99).
- J3 (s=1414) closes the section.

### S4 — The Ramp · s 1414–2000
- J3, then the climb: 0.3 → 9.7 m over ~580 m (peak grade +3.4% at s 1560–1760),
  easing to the plateau. Curv stays gentle (≤0.0025).
- Character: the **air window**. Clean runway s 1850–2080 (no traffic) so a
  full-throttle player lifts at the crest (~s 2050): air 0.05/s + landing bonus
  0.10 per 0.5 s. Also the visual payoff — city drops away below the plateau.
- Earners: air at the crest; the climb itself is not an earner (no drift, no
  oncoming) — it is the breath before S5.
- Dressing note for modeler (optional, re-bake only if dressed): this is the
  design doc's "freeway overpass" beat — retaining wall right side on the climb,
  skyline reveal at the crest.

### S5 — Overpass Drop · s 2000–2586
- Plateau ~9.3 m to s≈2260, then the drop (9.3 → 0 m, peak −2.9% at s 2260–2420)
  with a sweeper on the descent (window mean 0.0039 at s 2200–2400). J4 (s=2586,
  arm 64 — the biggest junction) ends it.
- Character: **speed carry + second drift line.** Downhill exit off the crest into
  the sweeper; traffic pocket s 2350–2540 gives near-miss income on the run-in to
  J4. Land the crest air, drift the descent sweeper, thread the pocket.
- J4 pass-through (Race); Crash mode stages here at full complexity.

### S6 — Finish Straight · s 2586–3010
- 424 m dead straight (curv ≤0.0004), finish line at s≥2998.
- Character: the **burn runway.** Boost drain 0.16/s ≈ 6.25 s of boost; at sprint
  speeds one full meter covers ~this entire straight. Whatever is banked by J4 is
  spent here to the flag. No new earners — optionally one last near-miss pair just
  after J4 for a final meter top-up.
- Dressing note for modeler: **finish gantry** at ~s 2998 (there is a start gantry
  at s=0 but no finish marker — cheap prop, closes the sprint visually).

## 2. Junction usage in Race mode

- Junctions stay **pass-through set pieces** in Race (they belong to Crash mode).
  No routing through arms; arms remain hazard space off the racing line.
- Rule for the traffic pass: density bump ~100 m before each junction (near-miss
  corridors: s 200–300, 800–902, 1310–1414, 2480–2586), but a **clean 60 m bubble
  at each junction** (junction.s ±30): Crash stages reuse this spline and race
  traffic must never park inside a junction box.
- Signals at every junction (already baked) double as the visual cadence —
  the player reads "green means flat-out" downtown.

## 3. Boost-earner map (summary)

Economy per `config.js`: trigger at meter 0.99; drain 0.16/s; earn oncoming
0.105/s, near-miss 0.10 (0.13 heavy), drift 0.085/s, air 0.05/s (+0.10 landing
per 0.5 s). Race score: near-miss 150, drift 50/s, oncoming 25/s, takedown 1000.

| s range | Earner | Mechanism |
|---|---|---|
| 120–280 | near-miss pocket | density bump, with-traffic lanes |
| 400–900 | drift line | existing sweeper chain, inside line |
| 800–902 / 400–500 | oncoming option | outer oncoming lanes, straighter links |
| 940–1360 | oncoming corridor | sustained wrong-side running |
| 1080–1340 | near-miss pocket | 3–4 cars, with-traffic lanes |
| 200–300 / 800–902 / 1310–1414 / 2480–2586 | pre-junction corridors | density bump |
| junctions ±30 m | clean bubble | no traffic (Crash-stage reuse) |
| 1850–2080 | clean crest runway | enables the air window |
| ~2050 | air | crest lift + landing bonus |
| 2350–2540 | near-miss pocket | descent run-in to J4 |
| 2586–3010 | burn runway | spend banked meter to the line |

Intended meter arc: pocket starts it in S1 → drift/oncoming fills most of it across
S2–S3 → trigger (0.99) typically available entering S4 → first Burnout through the
crest air → refill via S5 drift+pocket → final burn down S6. A clean lap sees 1–2
full activations; a great lap chains into Burnout territory.

## 4. Race-mode defects this pass should fix (queued post-freeze, small)

Found while grounding this spec — flagging now so they ride the same pass:

1. **Sprint grid pinch.** `modes.js` staggers rivals `30 − 9 − i·9` then clamps to
   `[2, L−2]` on open tracks → rivals 4 and 5 both clamp to s=2 (three cars bunched
   at the spline start; only two grid columns so they overlap laterally too).
   Fix in the pass: sprint start `player.s = 54` (rivals land 45/36/27/18/9 — all
   on-spline, no clamp). Closed tracks unaffected (wrap handles it).
   This may also relate to the queued POS 7/6 punch item — worth checking together.
2. **`laneSqueeze` sign.** `track.js` computes `−lanesOpp[last]` = **+1.25** (inner
   WITH-traffic lane — the lane E5 traffic spreads across), but three independent
   comments (track.js:131, traffic.js:86, commit b249c78) all say the pass line is
   the inner ONCOMING lane at **−1.25**, and `bot.js`'s squeeze bail-out only makes
   sense against oncoming traffic. Looks like one extra sign flip
   (`−lanesOpp[last]` should be `lanesOpp[last]` = −1.25). Gates still pass because
   the deep-pass line (`laneDodge`, −1.25) and same-lane obstacle checks mask it.
   One-char fix + bot re-run in the pass. **Spec §3 assumes the comment behavior
   (squeeze = −1.25, dodge lane kept clear).**

## 5. Implementation shape (when the freeze lifts)

- All data-level: per-section traffic density weights + pocket/bubble/corridor
  tables (new config on `S9.CFG` or a `tracks_data.json` extension), sprint grid
  constants, `laneSqueeze` sign. No spline, GLB, or bake changes required.
- Modeler asks are optional dressing only: overpass retaining wall on S4, finish
  gantry on S6. Both can ship without; re-bake only if dressed.
- Acceptance: bot sprint run log-matched (boost earned via oncoming + near-miss on
  downtown; drift line held in S2; crest air observed ≥0.3 s; meter arc per §3);
  shots: crest air frame, J4 approach pocket, finish-straight burn; gates green on
  localhost AND file:// with vision-checked textures (per the texture-fix protocol).

## 6. Answers pm-s9 asked for in this thread

- **"nofx isolated shot clean" — what did it verify?** Only that `?fx=0` boots with
  zero console errors and captures a screenshot — a post-stack-off canary. Nobody
  vision-checked that shot's textures. It could not have caught this bug anyway:
  all gates run localhost, where the bundle-miss fallback silently loads the
  on-disk PNGs — every localhost screenshot shows textured surfaces (PNGs, never
  the shipped JPEGs). The file:// path was never exercised by pw_run. Agreed with
  pm: post-fix gates must vision-check shots on BOTH protocols.
- **Per-track pano intent (`loadEnv` hardcodes `env_coast.jpg`).** By-scope-correct
  for M1: the design doc commits exactly one Cycles pano (`env_coast.jpg`,
  `## Files` section). Downtown's dusk read comes from the baked light atlas, not
  the pano; the canyon's flat-gray skybox is the procedural gradient sky
  (`track.js #buildSky`), not a broken pano. Per-track/TOD panos = modeler's parked
  post-M1 item (1 bake pass each + a 1-line `loadEnv` param — queued post-freeze
  if Victor wants them in M1).