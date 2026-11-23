#!/usr/bin/env python3
"""verify_track_shift.py — assert a tracks_data.json regeneration was a PURE TRANSLATION.

Used after modeler-s9's layout pass (Defect A fix) regenerates tracks_data.json.
The client contract (js/track.js) rests on two invariants that a pure XZ
translation preserves exactly:

  1. Centerline delta is ONE constant (dx, dz) vector along the WHOLE centerline
     of every track (and dy constant too). If the delta varies, the path was
     rotated/reshaped, not translated — the LEFT/RIGHT lateral sign convention
     negation at load needs human re-verification before the new assets ship.
  2. Arclength invariants are UNCHANGED: junction s/arm/lateral, furniture
     (type, s, lateral, node) multisets, lanes list, roadWidth, closed flag,
     and per-track centerline point count (same 2m resample of the same path).

Usage:
  python tools/verify_track_shift.py                # HEAD baseline vs working tree
  python tools/verify_track_shift.py old.json new.json

Exit 0 = pure translation, safe to swap client-consumed assets.
Exit 1 = contract risk, do NOT let the new glb/json reach the client before review.
"""
import json
import subprocess
import sys
import tempfile
import os

TOL = 0.02  # meters — anything above this is not a pure translation


def load(path_or_git):
    if path_or_git == "git:HEAD":
        blob = subprocess.run(
            ["git", "show", "HEAD:assets/tracks_data.json"],
            capture_output=True, text=True, check=True).stdout
        return json.loads(blob)
    with open(path_or_git, "r", encoding="utf-8") as f:
        return json.load(f)


def by_id(doc):
    out = {}
    for t in doc["tracks"]:
        out[t.get("id") or t.get("name")] = t
    return out


def check_track(tid, old, new, fails):
    # --- metadata invariants ---
    for key in ("closed", "roadWidth", "lanes"):
        if old.get(key) != new.get(key):
            fails.append(f"[{tid}] {key} changed: {old.get(key)!r} -> {new.get(key)!r}")

    # --- centerline: constant translation vector ---
    oc, nc = old["centerline"], new["centerline"]
    if len(oc) != len(nc):
        fails.append(f"[{tid}] centerline point count changed: {len(oc)} -> {len(nc)} "
                     f"(same path re-sampled at the same 2m spacing must keep N)")
        return
    dxs = [round(n[0] - o[0], 4) for o, n in zip(oc, nc)]
    dys = [round(n[1] - o[1], 4) for o, n in zip(oc, nc)]
    dzs = [round(n[2] - o[2], 4) for o, n in zip(oc, nc)]
    for axis, vals in (("dx", dxs), ("dy", dys), ("dz", dzs)):
        span = max(vals) - min(vals)
        if span > TOL:
            fails.append(f"[{tid}] {axis} varies along centerline by {span:.3f}m "
                         f"(range {min(vals)}..{max(vals)}) — NOT a pure translation; "
                         f"lateral sign convention needs re-verification")
    vec = (dxs[0], dys[0], dzs[0])
    return vec


def check_junctions(tid, old, new, fails):
    oj, nj = old.get("junctions") or [], new.get("junctions") or []
    if len(oj) != len(nj):
        fails.append(f"[{tid}] junction count changed: {len(oj)} -> {len(nj)}")
        return
    for i, (a, b) in enumerate(zip(oj, nj)):
        for key in ("s", "arm", "lateral"):
            if abs(a.get(key, 0) - b.get(key, 0)) > TOL:
                fails.append(f"[{tid}] junction[{i}].{key} changed: "
                             f"{a.get(key)} -> {b.get(key)} (arclength invariant must hold)")


def check_furniture(tid, old, new, fails):
    keyf = lambda f: (f.get("type"), round(f.get("s", 0), 3),
                      round(f.get("lateral", 0), 3), f.get("node"))
    of = sorted(map(keyf, old.get("furniture") or []))
    nf = sorted(map(keyf, new.get("furniture") or []))
    if of != nf:
        only_old = [x for x in of if x not in nf][:5]
        only_new = [x for x in nf if x not in of][:5]
        fails.append(f"[{tid}] furniture multiset changed (s-space entries must be "
                     f"translation-invariant); only-old sample: {only_old}; "
                     f"only-new sample: {only_new}")


def main():
    args = sys.argv[1:]
    if len(args) == 2:
        old_doc, new_doc = load(args[0]), load(args[1])
        label = f"{args[0]} -> {args[1]}"
    else:
        old_doc, new_doc = load("git:HEAD"), load("assets/tracks_data.json")
        label = "HEAD -> working tree"
    print(f"verify_track_shift: {label}  (tol {TOL}m)")

    om, nm = by_id(old_doc), by_id(new_doc)
    fails = []
    if set(om) != set(nm):
        fails.append(f"track id sets differ: {sorted(om)} vs {sorted(nm)}")
    vecs = {}
    for tid in sorted(set(om) & set(nm)):
        vec = check_track(tid, om[tid], nm[tid], fails)
        if vec is not None:
            vecs[tid] = vec
        check_junctions(tid, om[tid], nm[tid], fails)
        check_furniture(tid, om[tid], nm[tid], fails)

    if vecs:
        uniq = set(vecs.values())
        for tid, v in sorted(vecs.items()):
            print(f"  {tid}: translation = ({v[0]}, {v[1]}, {v[2]})")
        if len(uniq) > 1:
            print("  note: tracks shifted by DIFFERENT vectors (expected for the "
                  "footprint separation — each track is its own rigid move)")
    if fails:
        print("FAIL — not a safe pure-translation swap:")
        for f in fails:
            print("  - " + f)
        sys.exit(1)
    print("PASS — pure translation; arclength invariants intact; client contract safe.")


if __name__ == "__main__":
    main()