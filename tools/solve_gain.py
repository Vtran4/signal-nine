#!/usr/bin/env python3
"""solve_gain.py — paired-texel gain solver for the baked atlas compose (v2).

Client compose (js/track.js composeMaterial):
    linear_render = srgb_decode(albedo) * (light/(light+0.55) * GAIN + AMBIENT)
    display       = srgb_encode(linear_render)     # renderer outputColorSpace
albedo is sampled sRGB-decoded, light sampled linear (main.js loadTex).

WHY MODEL-SPACE, NOT SCREEN-SPACE ANCHORS: the recorded screenshot anchors
(coastal 187 / canyon ~212) are visible-frame pixel medians — the frame
overweights near-camera road texels, so they are NOT whole-island texel
medians and cannot be reproduced from the atlases alone. The model here IS
internally consistent: it reproduces the landed e5c0104 equality exactly
(canyon@1.4 median == coastal@2.4 median == 154 in model space, established
as 187 == 187 on screen). Solves are therefore RELATIVE:

  snapshot : pre-rebake, record each group's model-median render at its
             CURRENT landed gain -> tools/gain_targets.json. The operative
             look anchor is coastal's median (the accepted look).
  solve    : post-rebake, solve each group's GAIN on the NEW atlases to hit
             the preserved coastal target (all groups ride the accepted
             look; canyon's landed 1.4 was defined as equality-with-coastal,
             so this reproduces that intent; downtown/props old medians were
             defect artifacts and must NOT be preserved). Requires the
             snapshot file — never recomputes targets against a moved
             baseline.

  --selftest : snapshot + solve in one pass against the CURRENT tree and
             assert the round-trip returns the current gains (validates the
             solver without touching anything).

Island mask: lossless albedo PNG, max-channel > 2/255 (bake background is
clear-black). Values: the SHIPPED JPGs (what the client samples), mean-channel
luminance. Also reports per group: light distribution, mid-band share
(60-200 — informational distribution stat only; the ">20% mid-band" acceptance
gate was RETIRED 2026-11-23, see tools/fix_batch_status.md), and the
ambient-term share of the median render (flags when the 0.12 compose floor
dominates — the cue to re-check the ambient term before trusting the gain).
"""
import hashlib
import json
import os
import sys

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
TARGETS = os.path.join(ROOT, "tools", "gain_targets.json")

CURRENT_GAIN = {"coastal": 2.4, "props": 1.78, "canyon": 1.39, "downtown": 1.01}  # landed map (post-neon rebake; keep in sync with js/track.js GAIN)
AMBIENT = 0.12


def srgb_decode(c):
    c = c / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def srgb_encode(c):
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055) * 255.0


def jpg_of(png_name):
    return os.path.join(ASSETS, png_name.rsplit(".", 1)[0] + ".jpg")


def atlas_state():
    """sha256 (16-hex) of every atlas jpg the client samples — detects a moved baseline."""
    import glob
    out = {}
    for p in sorted(glob.glob(os.path.join(ASSETS, "albedo_*.jpg")) +
                    glob.glob(os.path.join(ASSETS, "light_*.jpg"))):
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        out[os.path.basename(p)] = h.hexdigest()[:16]
    return out


def load_group(name, groups):
    g = groups[name]
    png_a = Image.open(os.path.join(ASSETS, g["albedo"]))
    jpg_a = Image.open(jpg_of(g["albedo"])).convert("RGB")
    jpg_l = Image.open(jpg_of(g["light"])).convert("RGB")
    if jpg_a.size != jpg_l.size:
        raise SystemExit(f"[{name}] albedo/light jpg size mismatch {jpg_a.size} vs {jpg_l.size}")
    mask = np.asarray(png_a, dtype=np.uint8).max(axis=2) > 2
    if int(mask.sum()) < 1000:
        raise SystemExit(f"[{name}] island mask too small ({int(mask.sum())} texels) — atlas broken?")
    j_a = np.asarray(jpg_a, dtype=np.float64)[mask]
    j_l = np.asarray(jpg_l, dtype=np.float64)[mask]
    alb_lin = srgb_decode(j_a.mean(axis=1))
    l_lin = (j_l / 255.0).mean(axis=1)
    return alb_lin, l_lin, mask


def median_display(gain, alb_lin, l_lin):
    return float(np.median(srgb_encode(alb_lin * ((l_lin / (l_lin + 0.55)) * gain + AMBIENT))))


def solve_to(target, alb_lin, l_lin, lo=0.05, hi=16.0, iters=90):
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if median_display(mid, alb_lin, l_lin) < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def snapshot(groups, verbose=True):
    medians = {}
    for name in sorted(groups):
        alb, l, mask = load_group(name, groups)
        gain = CURRENT_GAIN.get(name, 2.4)
        medians[name] = {"median": round(median_display(gain, alb, l), 1),
                         "gain": gain,
                         "island_pct": round(float(mask.mean()) * 100, 1)}
        if verbose:
            print(f"  [{name}] @ current gain {gain} -> model median {medians[name]['median']} "
                  f"(island {medians[name]['island_pct']}%)")
    # landed-fix invariant: canyon@1.4 must equal coastal@2.4 (e5c0104 equality)
    if "canyon" in medians and "coastal" in medians:
        d = abs(medians["canyon"]["median"] - medians["coastal"]["median"])
        flag = "OK" if d < 1.0 else f"DRIFT {d:.1f} — model no longer matches the landed fix"
        print(f"  invariant canyon@{medians['canyon']['gain']} == coastal@{medians['coastal']['gain']}: {flag}")
    return medians


def report_group(name, alb, l, solved, target):
    l_p = np.percentile(l, [10, 50, 90])
    disp = srgb_encode(alb * ((l / (l + 0.55)) * solved + AMBIENT))
    midband = float(((disp >= 60) & (disp <= 200)).mean())
    i50 = int(np.argsort((l / (l + 0.55)) * alb)[len(l) // 2])
    amb_share = AMBIENT / ((l[i50] / (l[i50] + 0.55)) * solved + AMBIENT)
    print(f"  [{name}] light p10/p50/p90 = {l_p[0]:.3f}/{l_p[1]:.3f}/{l_p[2]:.3f}  "
          f"solved gain {solved:.3f} -> median {median_display(solved, alb, l):.0f} (target {target:.0f})")
    print(f"          mid-band 60-200 {midband*100:.1f}%  ambient share {amb_share*100:.1f}%"
          + ("   <-- AMBIENT DOMINATES, re-check compose ambient" if amb_share > 0.25 else ""))


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "snapshot"
    targets = None    # in-memory snapshot (selftest only; never the frozen file)
    manifest = json.load(open(os.path.join(ASSETS, "manifest.json")))
    groups = manifest["atlas_groups"]
    state = atlas_state()

    if mode in ("snapshot", "--selftest"):
        print(f"solve_gain snapshot: current gains {CURRENT_GAIN}")
        medians = snapshot(groups)
        targets = {"coastal_target": medians["coastal"]["median"],
                   "per_group": medians,
                   "atlas_state": state}
        if mode == "snapshot":
            # guard: the snapshot IS the frozen baseline — never silently
            # overwrite an existing one (a snapshot run in the PNG-new/JPG-old
            # window of a rebake round would otherwise hybrid-corrupt it; that
            # accident happened 2026-11-23 and cost a git restore)
            if os.path.exists(TARGETS) and "--force" not in sys.argv:
                raise SystemExit(f"refusing to overwrite existing {TARGETS} — the snapshot is the "
                                 f"frozen pre-rebake baseline; pass --force only if you intend to "
                                 f"re-baseline against the current atlases")
            with open(TARGETS, "w") as f:
                json.dump(targets, f, indent=1)
            print(f"targets written -> {TARGETS} (coastal anchor {medians['coastal']['median']})")
            return
        # --selftest keeps targets in memory only — NEVER touches the file

    if mode in ("solve", "--selftest"):
        if mode == "--selftest":
            t = targets          # in-memory from the selftest snapshot above
        else:
            if not os.path.exists(TARGETS):
                raise SystemExit(f"no snapshot at {TARGETS} — run 'python tools/solve_gain.py snapshot' "
                                 f"against the PRE-rebake atlases first; never recompute targets post-rebake")
            t = json.load(open(TARGETS))
        assert t is not None  # selftest path binds it above; solve path loads it here
        changed = state != t.get("atlas_state")
        target = t["coastal_target"]
        print(f"solve_gain solve: coastal anchor {target} from snapshot; "
              f"atlases {'CHANGED since snapshot (expected post-rebake)' if changed else 'UNCHANGED (selftest path)'}")
        gain_out = {}
        selftest_ok = True
        for name in sorted(groups):
            alb, l, mask = load_group(name, groups)
            solved = solve_to(target, alb, l)
            gain_out[name] = round(solved, 2)
            report_group(name, alb, l, solved, target)
            if mode == "--selftest" and not changed:
                # round-trip: solving to the group's OWN snapshot median must
                # reproduce its current gain (validates solver math even for
                # groups whose lightmaps can't reach the coastal target)
                own = t["per_group"][name]["median"]
                rt = solve_to(own, alb, l)
                cur = CURRENT_GAIN.get(name, 2.4)
                if abs(rt - cur) > 0.05:
                    print(f"  SELFTEST FAIL [{name}]: round-trip to own median {own} "
                          f"gave {rt:.3f} != current {cur} on unchanged atlases")
                    selftest_ok = False
        print("\nGAIN map for js/track.js:")
        print("  const GAIN = { " + ", ".join(f"{k}: {v}" for k, v in sorted(gain_out.items())) + " };")
        if mode == "--selftest":
            if not selftest_ok:
                sys.exit(1)
            print("SELFTEST PASS — round-trip reproduces the current gain map on unchanged atlases")
        return

    raise SystemExit(__doc__)


if __name__ == "__main__":
    main()