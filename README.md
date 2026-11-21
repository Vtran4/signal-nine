# Signal Nine

An arcade street racer in the style of Burnout 2: Point of Impact (2002).
Speed is only earned by driving dangerously — oncoming lanes, near-misses,
drifts, air time — with the constant threat that one bad lane change turns
the whole screen into a 200 mph pileup.

three.js, no build step, runs from `file://` and localhost. See
`Signal Nine - Game Design Document.md` (repo root) for the full design.

## Run

Double-click `start signal nine.bat` (serves on http://127.0.0.1:8139), or
open `index.html` directly (file:// works; assets are base64-embedded).

## Verify

```
python tools/pw_run.py smoke   # boots clean on file:// and localhost
python tools/pw_run.py shots   # key-moment screenshots
python tools/pw_run.py bot     # scripted full run
python tools/pw_run.py fps     # 60 fps @ 1080p, dynamic scaler, full traffic
```

## Layout

`index.html`, `vendor/` (three.bundle.js classic script), `js/` (config, util,
audio, speedfx, track, traffic, cars, physics, modes, game, bot, main),
`assets/` (glb + baked atlases + env pano, embedded by `tools/embed_assets.py`),
`blender/` (track/bake pipeline), `tools/` (verification + embedding).

All original code and assets. Cars are fictional lookalikes; no real brands.