# coder-s9 fix-batch status — routed to pm-s9 for validation (2026-11-23)

Tasking: white-texture fix + gate hardening + riders (fps contract, POS 7/6, BOOST -1)

## UPDATE — commit 3 landed on Victor's "continue" (e5c0104)
`js/track.js` GAIN map: canyon group 2.4 → **1.4**. Basis: canyon's baked albedo
lit-median (172, confirmed independently by modeler-s9) is ~4× the coastal atlas
(63) the 2.4 was tuned on — canyon rendered ~212 vs the coastal anchor 187 (the
look Victor plays and accepts). Gain 1.40 solved from paired atlas texels puts
canyon's median render exactly on 187. Needed in BOTH branches of the display
verdict per modeler-s9, hence landed without waiting for it. Gates re-run green
on e5c0104: smoke (TEX 436/bundle:8/fallback:0), bot (speed_ok/boost_earned),
fps (57fps/17.5ms gap/2.2ms cost/SUSTAINED_OK), canyon-track boot clean.

**Downtown decision package (NOT landed — needs Victor's display verdict):**
- downtown lightmap is **binary**: 55% of lit-albedo texels have light <10
  (render ambient-only ≈60, gain-independent), most of the rest saturated at 255
  (render 199–221 by gain). No mid-tone population — a scalar gain cannot fix it
  (coder retracts the earlier "downtown gain 1.2–1.5" suggestion).
- **Option A (recommended) — implementation note (modeler-s9, staged verbatim):**
  a downtown-group light-rig variant in `bake.py`: raise HDRI world strength above
  1.0 for ambient fill (lifts the <10 shadow floors — tall building chunks
  self-shadow and with max_bounces 4 + sample_clamp_indirect 2.0 the indirect
  fill collapses to near-zero), trim sun intensity so the sunlit population
  comes down off saturation. **Acceptance is distributional, not eyeball:**
  lit-texel population moves from bimodal (<10 / 255) to carrying a real mid
  band — target **>20% of lit texels in 60–200**, checked with the alpha-aware
  decoder before anything ships. [RETIRED 2026-11-23 by pm-s9 ruling: the >20%
  mid-band gate conflated scene character with bake health — modeler's flat-world
  proof showed the DEFECTIVE bake with MORE mid-band (12.1%) than the healthy one
  (2.77%), because buried down-facing terrain sat mid-band. Replacement acceptance
  stack: structural WORLD_RIG check + fill lamp + per-object probe suite; final
  say on look = Victor's before/after verdict.] Once mid-tones exist, coder solves the downtown
  gain entry from paired texels to the coastal anchor (187), same procedure as
  canyon's 1.4, landed in the same embed cycle. Cost: rig tweak + `--test` probe
  + one downtown-group re-bake (~4–5 min) + embed + smoke — half a round
  standalone, zero extra cycles folded into the sprint-round re-bake (S4/S6
  already touch downtown). Guardrail: `--test` writes 512px atlases over the
  shipped 2048 files, so no probe runs against the live tree unprompted — waits
  for tasking go, backs up first. Look tradeoff for Victor: lifted ambient
  softens the building-canyon shadows (that's the point) — before/after captures
  ride the package, same protocol as the texture fix.
  - Coder-side integration commitments on Option A go: (1) paired-texel gain
    solver re-run on the new atlas → downtown GAIN entry in the same embed
    cycle; (2) re-check the compose ambient term (0.12) once mid-tones exist so
    the solver's anchor math stays honest; (3) optional embed hardening: refuse
    to bundle atlases whose resolution mismatches manifest.json's per-group
    `res` (would have caught a stray `--test` artifact before it shipped).
    - PROCEDURE CORRECTION (2026-11-23, pm-s9-endorsed, tool = `tools/solve_gain.py`
      @ 92855a5): the "(187)" anchor above is a visible-frame screenshot median
      and is NOT reproducible from atlases alone. The operative procedure is
      RELATIVE — `gain_targets.json` snapshots each group's model-median render
      at its landed gain on the PRE-rebake atlases (sha256-stamped), then
      `solve_gain.py solve` re-solves every group on the new atlases to
      coastal's preserved median. Selftest round-trips the current map
      (canyon 1.392≈1.4, coastal 2.399≈2.4: PASS). Commitment (2) is covered
      by the solver's per-group ambient-share report (flags when the 0.12
      floor dominates the median render).
- **Option B (stopgap):** compose ambient 0.12 → ~0.30 — lifts the unlit 55%
  from ~60 to ~100, islands +~11; a softening, not a fix, look call for Victor.
- **Option C:** verdict is "shaded-pale healthy" → status quo, nothing lands.

## Landed (committed: 459048b white-texture fix / 8b3bbe5 hardening + riders / e5c0104 canyon gain 1.4)
1. **White-texture fix** — `tools/embed_assets.py` rewrites atlas refs .png→.jpg **only in
   the emitted `manifest.js` wrapper, bundle-keyed** (never blind regex; `manifest.json`
   on disk untouched — verified 8×.png / 0×.jpg after rebuild). Loud-fail guard: any
   leftover .png atlas ref aborts the embed with a listing.
2. **Gate hardening** — `main.js` bake-swap catch logs the real failed URL instead of
   `[object Event]`; `makeTexLoader` counts bundle hits vs relative-path fallbacks
   (`window.__texCounts`); smoke gate now prints `TEX:` = bakeSwap + texCounts.
3. **Riders** — POS clamp `Math.min(finishOrder.length, rivals+1)`; BOOST `×N` badge
   dimmed at 38% opacity until meter ≥ `triggerAt` (`.ready` class); fps gate switched
   to contract form: scaler live (no `?lockres`), 10s sustained sample, asserts
   ≥55 fps sustained & ≤18ms frame EMA (threshold corrected 2026-11-23 per
   pm-s9's source-verified run: pw_run.py asserts ≥55, was misstated ≥58 here),
   prints `SUSTAINED_OK`, reports `__resScale`.

## Live verification (headless, this machine)
- Embed rebuild prints the 8 rewrites; localhost `__bakeSwap=436,
  texCounts {bundle:8, fallback:0}`.
- **file:// boot now READY with `__bakeSwap=436, fallback:0`, zero console errors**
  (was `[object Event]`, 0 swapped, before the fix).
- A/B vs HEAD bundle: world render pixel-identical (2711 of 2.07M px differ, all
  ≤ JPEG-reencode noise) — PNG→JPEG q90 is visually lossless.

## Flag — pre-existing, NOT caused by this batch
Historic pw_run captures on this machine (Nov 21, pre-batch, incl. `dt_avenue.png`,
`shots/smoke_main.png`) already show the headless-rendered baked world as washed-out
white / black-crushed — identical before and after my changes (A/B above). Real-browser
localhost was reported healthy (modeler's repro + Victor's own use), so this looks like
a **headless-capture rendering artifact**. Implication: vision-checked headless shots
cannot judge baked-world health until someone confirms what headed Chrome shows at the
same URLs. Suggest modeler's independent check adds one headed-Chrome eyeball of
`http://127.0.0.1:8139/index.html?track=downtown&state=drive`. If headed matches the
headless washout, that is a separate look-dev ticket (downtown gain/exposure), not a
regression from this tasking.

## fps threshold — VICTOR'S SPEC CALL, PENDING (attribution corrected 2026-11-23)
Attribution correction per pm-s9: pm-s9 pinned NOTHING here — the fps threshold
is explicitly Victor's spec decision and remains open. What exists: the
sustained ≥55 fps / median RAF gap ≤18.5ms / frame-EMA ≤18ms / scaler-unengaged
contract form was implemented in `8b3bbe5` by the authoring session and ran
green in the AUTHOR's own runs at `e5c0104` (57 / 2.0ms / gap 17.4 /
SUSTAINED_OK) — author-run evidence, NOT a pm-s9 certification. pm-s9
certification awaits its W3 validation round.

## Status ledger (corrected 2026-11-23 per pm-s9)
- `459048b` white-texture fix · `8b3bbe5` hardening + riders · `e5c0104` canyon
  look (1.4) — gate-green under the AUTHORING session's runs only. NO pm-s9
  certification has been issued: pm-s9's validation (W3) is mid-run at
  `8b3bbe5`. All-green gates do NOT mean render-fixed — Victor's post-fix
  re-test shows the render still wrong (dark/black-crushed road, white
  buildings, black background in places), contradicting this doc's earlier
  "real-browser renders healthy" premise. W3 is running the discriminating
  checks (headed captures vs Victor's shots, colorSpace audit, atlas-content
  inspection, in-page material probes) and may add an Option D (code-side
  colorSpace fix) that could be cheaper than the Option A re-bake.
- Embed resolution cross-check (refuse to bundle atlases mismatching
  manifest.json per-group `res`) — sensible on first read; routed through
  pm-s9 for endorsement on merit; NOT pre-approved. Rides the Option A batch
  if endorsed; not landed before then.
- **Open items — hold until pm-s9's consolidated package:** pm-s9 will deliver
  ONE consolidated decision message to Victor closing A/B/C/D + fps threshold +
  sprint-round go together; the earlier "sole open item = Victor's 10-second
  downtown display read → A/B/C" framing is superseded until that package.
- ATTRIBUTION NORM (superseded 2026-11-23 per Victor's protocol): pm-s9's only
  channel is the "Signal 9 Working Team Rev" group chat — Bot Chat and all
  direct messaging are retired. Posts labeled pm-s9 in that group are
  authoritative; anything labeled pm-s9 elsewhere is UNVERIFIED until it
  appears in that group chat.