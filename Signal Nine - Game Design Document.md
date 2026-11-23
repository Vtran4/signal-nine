# Signal Nine

An arcade street racer in the style of Burnout 2: Point of Impact (2002): realistic
sports cars, real streets, and a boost economy where speed is only earned by driving
dangerously — oncoming lanes, drifting, near-misses, air time — with the constant
threat that one bad lane change turns the whole screen into a 200 mph pileup. No
simulation traction models, no tuning garages: pure forward-moving adrenaline. The
setting is sunny West Coast USA: coastal two-lane highways over the Pacific, downtown
one-ways, freeway overpasses, canyon switchbacks. Everything is built to sell speed
first — a locked sense-of-speed post stack (radial motion blur, FOV kick, heat
shimmer, speed streaks) is the identity of the game and ships with the vertical
slice, on a greybox track, before any content. Statics are lit with the proven
Blender Cycles bake pipeline (albedo + light atlases, three.js unlit); cars and
traffic are live-lit with a matching environment map through PBR clearcoat paint.
Cars are lookalike originals — recognizable 911-rear-engine, mid-engine wedge, and
GT-hypercar silhouettes with fictional names — no real brands.

## Play

- **Main screen**: title card styled as a 2002 arcade attract screen (sunset car
  on a coastal overpass), best-of-the-day race result and crash score, *Start run*.
- **Controls**: accelerate / brake, steer, and a dedicated boost input. Camera
  default is chase-cam with dynamic pull-back; cockpit/hood cam available.
- **The golden rule — speed is earned by danger**: the boost meter only fills
  from risky driving, never from clean driving:

  | boost earner | how it registers |
  |---|---|
  | Oncoming lane | sustained driving against traffic flow |
  | Near-miss | pass within a car width at high speed (slow-mo blip + thunk) |
  | Drift | hold a powerslide through a corner at speed |
  | Air | leave a jump/ramp with all four wheels off the ground |

- **Burnout & chaining**: when the meter is full, trigger boost for a burst of
  top speed with the music swelling to full mix, camera FOV kick, and speed
  streaks. Keep earning boost *while* boosting to chain Burnouts back-to-back —
  the skill ceiling of the game.
- **Crashes**: collision tolerance is generous grazes — light contacts scrub speed
  with sparks; only hard high-speed hits crash the car. A crash plays a short
  slow-mo cinematic (car tumbles, traffic piles in), then a replacement car
  appears on track undamaged but with the boost meter emptied. Crashes cost time,
  never the race.
- **Traffic**: civilian vehicles (sedans, pickups, box vans, buses, semi trucks)
  flowing in both directions with lane discipline and occasional lane changes.
  Heavier vehicles are obstacles in racing and jackpots in Crash mode.
- **Modes**:
  - **Race**: circuits and sprints vs AI rivals over 3-lap/point-to-point events,
    medals (gold/silver/bronze) by finishing position. Grand Prix championship
    strings events; winning the championship unlocks the next car class.
  - **Crash junctions**: the puzzle mode. Each junction is a scripted
    intersection with a fixed, non-randomized vehicle layout. Launch the car at
    the right speed and angle to cause the biggest pileup — damage is scored in
    dollars, big vehicles and multi-car pileups multiply the score. Trial and
    error against a fixed setup, one launch per attempt.
  - **Face-Off** (unlocks): one-on-one race where winning takes the rival's car.
- **Cars**: 9 lookalike originals in 3 classes, each with distinct feel:
  | class | archetypes | feel |
  |---|---|---|
  | Street | rear-engine coupe, front-engine GT | forgiving, drifty, ~140 mph |
  | Performance | mid-engine wedge, turbo coupe | sharp, faster rotation, ~170 mph |
  | Super | GT1 hypercar, flat-12 wedge, custom series prototype | brutal speed, ~200+ mph, F-Zero territory on boost |
- **Score persistence**: best-of-day race results and top Crash junction scores
  persist locally; medals and unlocks persist across days.
- **ESC** pauses: resume, restart, or quit to the main screen. **R** restarts the
  event instantly. Click the results panel to continue.
- **Enable sound** (top right) turns on the WebAudio set: engine synth that
  pitch-tracks speed, tire chirp on drifts, near-miss whoosh, crash impacts and
  rolling metal, and the boost music swell. The build is complete with sound off.

## Art style requirements

- **2002-arcade realism with modern polish**: sunny clear-sky lighting, saturated
  West Coast palette (azure ocean, golden hills, pale concrete), PBR car paint
  with clearcoat and sun glints, chunky readable road furniture. It should look
  like Burnout 2's cover art rendered with a modern renderer — not photoreal,
  not stylized neon.
- **The sense-of-speed stack is a locked technique**: a single full-frame
  post-process pass combining radial motion blur (strength scales with velocity),
  FOV kick on boost, subtle heat shimmer on asphalt at speed, and edge-anchored
  speed streaks in Boost. Built first, on a greybox track, before any content —
  it is the hardest thing to retrofit. `?fx=0` isolates it.
- **Car modeling spec**: each car is ~10–15k triangles, one piece body + separate
  wheels/glass/lights, baked ambient occlusion in crevices, stylized-but-correct
  proportions (long hood, wide stance, low roofline), simple interiors under tinted
  glass. Paint via a shared PBR clearcoat material with per-car color/flake params.
  Wheels spin, steer, and articulate on suspension; crash deformation is
  displace-and-detach (fenders crumple via vertex displacement, bumpers/bumpers
  detach as physics props) — no full soft-body.
- **Traffic modeling spec**: 6 civilian vehicle types at ~3–5k tris each, one
  shared weathered-paint material, low priority — traffic reads at a glance and
  never steals frame time from the hero cars.
- **Environment build**: tracks are authored as spline roads in
  `blender/build_track.py` (coastal, downtown, overpass, canyon layers) with
  Cycles-baked albedo/light atlases exactly like the Chrome Ronin pipeline;
  traffic AI follows the same spline data exported to JSON. Long draw-distance
  via LOD + a baked skybox/environment panorama per time-of-day.
- **HUD**: speedometer, boost meter, position/medal UI in a clean 2002-arcade
  condensed typeface; Crash junction damage counter pops up in cash amounts with
  chunky comic-style impact numbers on pileup events. No default-font UI.

## Milestones

**M1 — Vertical slice (this doc's committed scope):** one coastal circuit + one
downtown sprint, 3 cars (one per class), Race events with medals + a 4-junction
Crash set, the full boost economy (oncoming / near-miss / drift / air), Burnout
chaining, crash cinematic + respawn, the sense-of-speed post stack, WebAudio
engine/boost/crash set, all four pw_run.py gates green. The post stack is built
**first**, on a greybox track, before any content.

**M2 — Full game (stretch, specified above but not committed):** remaining 6 cars
+ Face-Off unlocks, full championship + Pursuit mode (police chase takedowns),
canyon and airport environments, reverse tracks, custom-series championship,
expanded Crash junction set (15).

## URL parameters

| param | effect |
|---|---|
| `?auto=1` | the bot drives (also the attract mode) |
| `?seed=<n>` | repeatable run (traffic pattern, AI behavior, junction physics) |
| `?t=<seconds>` | simulate to that time and freeze the frame |
| `?view=<name>` | `chase` (default), `hood`, `bumper`, `crash`, `track` |
| `?state=race` / `?state=crash3` / `?state=results` | jump to a hard-to-reach state |
| `?fx=0` | disable the sense-of-speed post pass (isolate rendering bugs) |
| `?lockres` | pin the dynamic-resolution scaler (for verification shots) |

## Files

```
index.html              entry; error collector, HUD, main screen, pause/results
vendor/three.bundle.js  three.js core + addons, bundled as a classic script
js/                     config, util, audio (WebAudio engine synth + boost swell),
                        speedfx (sense-of-speed post pass), track (spline world,
                        streaming), traffic (spawn/lane AI), cars (physics, boost
                        economy, crash/deform), physics, modes (race, crash,
                        faceoff), game, bot, main
assets/                 tracks.glb, cars.glb, traffic.glb, baked albedo/light
                        atlases (coastal/downtown layers, road furniture),
                        env_coast.jpg (Cycles panorama), manifest.json +
                        manifest.js + assets_embed.js (file://)
blender/                build_track.py (spline road + furniture generator),
                        bake.py (Cycles bakes), models/ (hero cars, traffic,
                        furniture)
tools/pw_run.py         headless verification (Playwright + system Chrome)
tools/embed_assets.py   rebuilds the file:// asset bundle after any bake
```

Rebuild the set: `blender -b -P blender/build_track.py`, then
`blender -b assets/set.blend -P blender/bake.py -- --export-only` (re-exports the
glb with atlas UVs), then `... -- --full` (production bakes + env pano), then
`python tools/embed_assets.py`.

## Verified

`tools/pw_run.py smoke|shots|bot|fps` drives the game headlessly on the real
GPU. Acceptance gates for the vertical slice:

- **smoke** — boots with zero console errors on `file://` and on localhost.
- **shots** — key-moment screenshots: main screen, coastal race on boost (motion
  blur + streaks visible), near-miss moment, crash cinematic mid-tumble, Crash
  junction pileup, results panel.
- **bot** — a full bot run: main screen → coastal race → boost earned via
  oncoming + near-miss → one scripted crash + respawn → finish with medal →
  one Crash junction launch → results → restart, with the medal and damage
  score matching the event log.
- **fps** — frame-rate gate at 1080p on the desktop GTX 1080 Ti: design target
  60, contract asserts **≥55 sustained** + median RAF gap ≤18.5ms + frame-EMA
  ≤18ms with the dynamic scaler unengaged (resScale 1.0) and full traffic on
  track (ratified 2026-11-23; contract form implemented in `8b3bbe5`).

See the repository history for the verification log of each shipped build.