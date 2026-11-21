# Signal Nine — HERO CAR FINALS (build_cars_final.py)
# Headless: blender -b -P blender/models/build_cars_final.py
# Replaces the blockout cars.glb at the SAME node/slot contract (zero renames):
#   <car>_body (lofted hull), _glass (greenhouse loft), _roof (painted cap),
#   _interior (+wheel wells), _wheel_fl|fr|rl|rr (torus tire + spoked rim),
#   _lights_f/_lights_r, detachables _bumper_f/_bumper_r/_hood/_spoiler
#   (origin at part centroid, parented under body root).
# Slots: paint_street/paint_perf/paint_super + glass/lights/lights_r/tire/rim/dark.
# Hulls are lofts driven by the VERIFIED blockout silhouette curves, so dims and
# wheelbase/track match what physics already tuned against.
# Outputs: ../../assets/cars.glb + cars_final_report.json + shots/cars_final.png
import bpy
import bmesh
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.normpath(os.path.join(HERE, "..", "..", "assets"))
SHOTS = os.path.normpath(os.path.join(HERE, "..", "shots"))
os.makedirs(ASSETS, exist_ok=True)
os.makedirs(SHOTS, exist_ok=True)

try:
    bpy.ops.wm.read_factory_settings(use_empty=True)
except Exception:
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
scene = bpy.context.scene

def pbr(name, color, metallic=0.0, rough=0.5):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (*color, 1.0)
    b.inputs["Metallic"].default_value = metallic
    b.inputs["Roughness"].default_value = rough
    return m

MAT = {
    "paint_street": pbr("paint_street", (1.00, 0.42, 0.08), 0.20, 0.32),
    "paint_perf":   pbr("paint_perf",   (1.00, 0.78, 0.05), 0.20, 0.32),
    "paint_super":  pbr("paint_super",  (0.72, 0.78, 0.88), 0.85, 0.24),
    "glass":        pbr("glass",        (0.03, 0.05, 0.07), 0.40, 0.10),
    "lights":       pbr("lights",       (1.00, 0.98, 0.90), 0.0, 0.20),
    "lights_r":     pbr("lights_r",     (0.70, 0.07, 0.05), 0.0, 0.25),
    "tire":         pbr("tire",         (0.03, 0.03, 0.03), 0.0, 0.9),
    "rim":          pbr("rim",          (0.75, 0.76, 0.78), 0.9, 0.3),
    "dark":         pbr("dark",         (0.10, 0.10, 0.12), 0.0, 0.85),
}

def mesh_from(name, verts, faces, mat, location=(0, 0, 0), smooth=False):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate()
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    if smooth:
        for p in me.polygons:
            p.use_smooth = True
    ob = bpy.data.objects.new(name, me)
    ob.location = location
    if mat is not None:
        me.materials.append(mat)
    scene.collection.objects.link(ob)
    return ob

def curve(keys, f):
    if f <= keys[0][0]:
        return keys[0][1]
    for k in range(len(keys) - 1):
        a, b = keys[k], keys[k + 1]
        if f <= b[0]:
            t = (f - a[0]) / (b[0] - a[0])
            return a[1] + (b[1] - a[1]) * t
    return keys[-1][1]

def box_into(verts, faces, dims, center, yaw=0.0):
    dx, dy, dz = dims
    cx, cy, cz = center
    base = len(verts)
    ca, sa = math.cos(yaw), math.sin(yaw)
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                lx, ly, lz = sx * dx / 2, sy * dy / 2, sz * dz / 2
                verts.append((cx + lx * ca - ly * sa, cy + lx * sa + ly * ca, cz + lz))
    for f in [(0, 1, 3, 2), (4, 5, 7, 6), (0, 4, 5, 1),
              (2, 3, 7, 6), (0, 2, 6, 4), (1, 3, 7, 5)]:
        faces.append(tuple(vi + base for vi in f))

def loft(name, rings, mat, smooth=True, cap_start=True, cap_end=True):
    """rings: equal-length closed loops of (x, y, z). Quads between rings + caps."""
    verts = []
    for ring in rings:
        verts.extend(ring)
    m = len(rings[0])
    faces = []
    for s in range(len(rings) - 1):
        for i in range(m):
            j = (i + 1) % m
            faces.append((s * m + i, s * m + j, (s + 1) * m + j, (s + 1) * m + i))
    if cap_start:
        faces.append(tuple(range(m - 1, -1, -1)))
    if cap_end:
        base = (len(rings) - 1) * m
        faces.append(tuple(range(base, base + m)))
    return mesh_from(name, verts, faces, mat, smooth=smooth)

def centroid_loft(name, rings, mat):
    """Loft re-centered on its own centroid; origin placed at the centroid."""
    pts = [p for ring in rings for p in ring]
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    cz = sum(p[2] for p in pts) / len(pts)
    shifted = [[(p[0] - cx, p[1] - cy, p[2] - cz) for p in ring] for ring in rings]
    return loft(name, shifted, mat, smooth=True, cap_start=True, cap_end=True), (cx, cy, cz)

# ---------------- car curve definitions (derived from verified blockouts) ----------------
CARS = {
    "street": {
        "display": "Vantoro RS", "paint": "paint_street", "width": 1.84,
        "nose": -2.15, "tail": 2.15, "floor": 0.17,
        "top": [(-2.15, 0.55), (-1.80, 0.66), (-0.60, 0.74), (0.00, 1.22),
                (0.90, 1.13), (1.70, 0.94), (2.15, 0.84)],
        "belt": [(-2.15, 0.50), (-0.60, 0.66), (0.00, 0.78), (0.90, 0.80), (2.15, 0.72)],
        "plan": [(-2.15, 0.80), (-1.35, 0.90), (0.00, 0.92), (1.10, 0.92), (2.15, 0.83)],
        "flares": (-1.35, 1.10, 0.055),
        "gh": (-0.60, 1.60, 0.80),
        "wheel_r": 0.33, "tire_w": 0.28, "track_half": 0.78, "axles": (-1.35, 1.10),
        "spoiler": {"type": "lip", "f": 1.95, "u": 0.91, "chord": 0.26},
        "bump_u": 0.40,
    },
    "perf": {
        "display": "Kestrel MR", "paint": "paint_perf", "width": 1.94,
        "nose": -2.20, "tail": 2.20, "floor": 0.15,
        "top": [(-2.20, 0.42), (-1.50, 0.55), (-0.80, 0.68), (-0.45, 1.15),
                (0.35, 1.10), (1.10, 0.82), (2.20, 0.72)],
        "belt": [(-2.20, 0.40), (-0.80, 0.60), (-0.45, 0.78), (0.35, 0.80), (2.20, 0.66)],
        "plan": [(-2.20, 0.82), (-1.45, 0.94), (0.00, 0.97), (1.15, 0.96), (2.20, 0.86)],
        "flares": (-1.45, 1.15, 0.06),
        "gh": (-0.80, 0.85, 0.82),
        "wheel_r": 0.33, "tire_w": 0.30, "track_half": 0.82, "axles": (-1.45, 1.15),
        "spoiler": {"type": "wing", "f": 2.05, "u": 1.02, "chord": 0.36, "strut_h": 0.28},
        "bump_u": 0.36,
    },
    "super": {
        "display": "Apex GT1", "paint": "paint_super", "width": 2.00,
        "nose": -2.30, "tail": 2.30, "floor": 0.12,
        "top": [(-2.30, 0.38), (-1.60, 0.52), (-0.90, 0.62), (-0.50, 1.10),
                (0.15, 1.08), (0.90, 0.75), (2.30, 0.68)],
        "belt": [(-2.30, 0.36), (-0.90, 0.56), (-0.50, 0.76), (0.15, 0.78), (2.30, 0.62)],
        "plan": [(-2.30, 0.86), (-1.55, 0.97), (0.00, 1.00), (1.17, 0.98), (2.30, 0.88)],
        "flares": (-1.55, 1.17, 0.05),
        "gh": (-0.90, 0.70, 0.66),
        "wheel_r": 0.34, "tire_w": 0.32, "track_half": 0.83, "axles": (-1.55, 1.17),
        "spoiler": {"type": "wing", "f": 2.15, "u": 1.05, "chord": 0.42, "strut_h": 0.36},
        "bump_u": 0.30,
    },
}

HULL_RING = [(-1.00, 0.00), (-1.00, 0.45), (-0.96, 0.80), (-0.90, 1.00),
             (-0.45, 1.02), (0.00, 1.03), (0.45, 1.02), (0.90, 1.00),
             (0.96, 0.80), (1.00, 0.45), (1.00, 0.00), (0.50, 0.00), (-0.50, 0.00)]
GH_RING = [(-1.00, 0.00), (-0.88, 0.55), (-0.62, 0.92), (0.00, 1.00),
           (0.62, 0.92), (0.88, 0.55), (1.00, 0.00)]

def gauss(x, s):
    return math.exp(-(x * x) / (2 * s * s))

def halfwidth(spec, f):
    w = curve(spec["plan"], f)
    fa, ra, amp = spec["flares"]
    return w + amp * (gauss(f - fa, 0.55) + gauss(f - ra, 0.55))

def deck_of(spec, f):
    g0, g1, _ = spec["gh"]
    if g0 <= f <= g1:
        return curve(spec["belt"], f)
    return curve(spec["top"], f)

def hull_ring(spec, f):
    fl = spec["floor"]
    belt = min(curve(spec["belt"], f), deck_of(spec, f))
    w = halfwidth(spec, f)
    ring = []
    for lf, uf in HULL_RING:
        ring.append((lf * w, f, fl + uf * (belt - fl)))
    return ring

def gh_ring(spec, f):
    g0, g1, gwf = spec["gh"]
    belt = curve(spec["belt"], f)
    top = curve(spec["top"], f)
    gw = halfwidth(spec, f) * gwf
    ring = []
    for lf, uf in GH_RING:
        ring.append((lf * gw, f, belt + uf * (top - belt)))
    return ring

def build_wheel(name, rim_name, r, tire_w, x, f_axle):
    """Torus tire + rim disc + 5 spokes. Two meshes in hub-local space, origin at
    the hub center so axle spin is a local X rotation."""
    verts, faces = [], []
    R, r = r - 0.10, 0.10
    SU, SV = 22, 12
    for i in range(SU):
        a = 2 * math.pi * i / SU
        for j in range(SV):
            b = 2 * math.pi * j / SV
            rr = R + r * math.cos(b)
            verts.append(((tire_w / 2) * math.sin(b), rr * math.sin(a), rr * math.cos(a)))
    for i in range(SU):
        for j in range(SV):
            i2, j2 = (i + 1) % SU, (j + 1) % SV
            faces.append((i * SV + j, i2 * SV + j, i2 * SV + j2, i * SV + j2))
    wheel = mesh_from(name, verts, faces, MAT["tire"], smooth=True)
    rv, rf = [], []
    rr = R - 0.02
    for xs in (-tire_w * 0.28, tire_w * 0.28):
        for k in range(14):
            a = 2 * math.pi * k / 14
            rv.append((xs, rr * math.sin(a), r + rr * math.cos(a)))
    for k in range(14):
        k2 = (k + 1) % 14
        rf.append((k, k2, 14 + k2, 14 + k))
    rf.append(tuple(range(14)))
    rf.append(tuple(range(14, 28)))
    for s in range(5):
        a = 2 * math.pi * s / 5 + 0.3
        base = len(rv)
        ca, sa = math.cos(a), math.sin(a)
        for sx in (-1, 1):
            for sy in (-0.10, 0.10):
                for sz in (r * 0.30, r * 0.85):
                    rv.append((sx * tire_w * 0.22,
                               sy * ca - sz * sa, sy * sa + sz * ca))
        for f in [(0, 1, 3, 2), (4, 5, 7, 6), (0, 4, 5, 1),
                  (2, 3, 7, 6), (0, 2, 6, 4), (1, 3, 7, 5)]:
            rf.append(tuple(vi + base for vi in f))
    rim = mesh_from(rim_name, rv, rf, MAT["rim"])
    return wheel, rim

def build_car_final(tok, spec):
    paint = MAT[spec["paint"]]
    g0, g1, _ = spec["gh"]
    parts = []

    hull_stations = []
    ns = 30
    for i in range(ns):
        f = spec["nose"] + (spec["tail"] - spec["nose"]) * i / (ns - 1)
        hull_stations.append(hull_ring(spec, f))
    body = loft(tok + "_body", hull_stations, paint, smooth=True)
    parts.append(body)

    gh_stations = []
    ng = 12
    for i in range(ng):
        f = g0 + (g1 - g0) * i / (ng - 1)
        gh_stations.append(gh_ring(spec, f))
    glass = loft(tok + "_glass", gh_stations, MAT["glass"], smooth=True)
    parts.append(glass)

    # roof cap (painted panel slightly proud of the glass crown)
    rf0, rf1 = g0 + 0.35, g1 - 0.30
    roof_rings = []
    for i in range(6):
        f = rf0 + (rf1 - rf0) * i / 5
        top = curve(spec["top"], f) + 0.02
        gw = halfwidth(spec, f) * spec["gh"][2] * 0.62
        ring = [(-gw, f, top - 0.015), (-gw * 0.75, f, top + 0.012),
                (0.0, f, top + 0.028), (gw * 0.75, f, top + 0.012),
                (gw, f, top - 0.015), (0.0, f, top - 0.03)]
        roof_rings.append(ring)
    roof, _ = centroid_loft(tok + "_roof", roof_rings, paint)
    parts.append(roof)

    # interior + wheel wells (dark), one mesh
    iv, ifc = [], []
    cab0, cab1 = g0 + 0.30, g1 - 0.30
    box_into(iv, ifc, (spec["width"] * 0.55, 0.30, 0.16),
             (0.0, cab0 + 0.18, spec["floor"] + 0.42))  # dash
    for sx in (-1, 1):
        box_into(iv, ifc, (0.42, 0.48, 0.30),
                 (sx * spec["width"] * 0.20, (cab0 + cab1) / 2 - 0.15, spec["floor"] + 0.34))
    box_into(iv, ifc, (spec["width"] * 0.86, (cab1 - cab0) * 0.9, 0.05),
             (0.0, (cab0 + cab1) / 2, spec["floor"] + 0.10))  # cabin floor
    for axle in spec["axles"]:
        for sx in (-1, 1):
            box_into(iv, ifc, (1.05, spec["tire_w"] + 0.16, spec["wheel_r"] * 1.5),
                     (sx * (spec["track_half"] - 0.10), axle, spec["wheel_r"] * 0.72))
    interior = mesh_from(tok + "_interior", iv, ifc, MAT["dark"])
    parts.append(interior)

    # wheels
    for key, axle in (("fl", spec["axles"][0]), ("fr", spec["axles"][0]),
                      ("rl", spec["axles"][1]), ("rr", spec["axles"][1])):
        x = -spec["track_half"] if key in ("fl", "rl") else spec["track_half"]
        wheel, rim = build_wheel(tok + "_wheel_" + key, tok + "_rim_" + key,
                                 spec["wheel_r"], spec["tire_w"], x, axle)
        wheel.location = (x, axle, spec["wheel_r"])
        rim.location = (x, axle, spec["wheel_r"])
        parts.append(wheel)
        parts.append(rim)

    # lights
    nw = halfwidth(spec, spec["nose"] + 0.1)
    lv, lf = [], []
    for sx in (-1, 1):
        box_into(lv, lf, (0.34, 0.08, 0.11),
                 (sx * nw * 0.55, spec["nose"] + 0.02, spec["bump_u"] + 0.24))
    mesh_from(tok + "_lights_f", lv, lf, MAT["lights"])
    rv, rf = [], []
    for sx in (-1, 1):
        box_into(rv, rf, (0.30, 0.07, 0.10),
                 (sx * halfwidth(spec, spec["tail"] - 0.1) * 0.55, spec["tail"] - 0.02,
                  spec["bump_u"] + 0.26))
    lights_r = mesh_from(tok + "_lights_r", rv, rf, MAT["lights_r"])
    parts.append(lights_r)

    # detachable bumpers (centroid origins)
    fl = spec["floor"]
    def bumper_ring(w, f):
        bu = spec["bump_u"]
        return [(-0.98 * w, f, fl + 0.06), (-0.98 * w, f, bu), (-0.50 * w, f, bu + 0.10),
                (0.50 * w, f, bu + 0.10), (0.98 * w, f, bu), (0.98 * w, f, fl + 0.06),
                (0.50 * w, f, fl + 0.02), (-0.50 * w, f, fl + 0.02)]
    bf_stations = []
    for i in range(3):
        f = spec["nose"] - 0.05 + 0.16 * i / 2
        bf_stations.append(bumper_ring(halfwidth(spec, f), f))
    bump_f, pos_f = centroid_loft(tok + "_bumper_f", bf_stations, paint)
    parts.append(bump_f)
    br_stations = []
    for i in range(3):
        f = spec["tail"] + 0.05 - 0.16 * i / 2
        br_stations.append(bumper_ring(halfwidth(spec, f), f))
    bump_r, pos_r = centroid_loft(tok + "_bumper_r", br_stations, paint)
    parts.append(bump_r)

    # hood (thin crowned panel over the front deck, centroid origin)
    h0, h1 = spec["nose"] + 0.30, g0 - 0.12
    hood_rings = []
    for i in range(6):
        f = h0 + (h1 - h0) * i / 5
        top = curve(spec["top"], f) + 0.012
        hw = halfwidth(spec, f) * 0.88
        ring = [(-hw, f, top - 0.02), (-hw * 0.6, f, top + 0.02),
                (0.0, f, top + 0.035), (hw * 0.6, f, top + 0.02),
                (hw, f, top - 0.02), (0.0, f, top - 0.045)]
        hood_rings.append(ring)
    hood, pos_h = centroid_loft(tok + "_hood", hood_rings, paint)
    parts.append(hood)

    # spoiler (lip slab / wing + struts), centroid origin
    sp = spec["spoiler"]
    if sp["type"] == "lip":
        ring = [(sp["f"] - sp["chord"] / 2, sp["u"] - 0.02),
                (sp["f"] + sp["chord"] / 2, sp["u"] + 0.015),
                (sp["f"] + sp["chord"] / 2, sp["u"] - 0.025),
                (sp["f"] - sp["chord"] / 2, sp["u"] - 0.065)]
        w = halfwidth(spec, sp["f"]) * 0.88
        slab = extruded_ring_part(tok + "_spoiler", [(p[0], p[1]) for p in ring], w, paint)
        parts.append(slab)
    else:
        boxes = [((halfwidth(spec, sp["f"]) * 0.88 * 2, sp["chord"], 0.05), (0.0, 0.0, 0.0))]
        for sx in (-1, 1):
            boxes.append(((0.06, 0.08, sp["strut_h"]),
                          (sx * halfwidth(spec, sp["f"]) * 0.31, 0.0,
                           -(sp["strut_h"] / 2 + 0.025))))
        verts, faces = [], []
        for dims, c in boxes:
            box_into(verts, faces, dims, c)
        cx = sum(v[0] for v in verts) / len(verts)
        cy = sum(v[1] for v in verts) / len(verts)
        cz = sum(v[2] for v in verts) / len(verts)
        shifted = [(v[0] - cx, v[1] - cy, v[2] - cz) for v in verts]
        wing = mesh_from(tok + "_spoiler", shifted, faces, paint,
                         location=(cx, cy + sp["f"], cz + sp["u"]))
        parts.append(wing)

    for p in parts:
        if p is not body:
            p.parent = body
    return body

def extruded_ring_part(name, pts, width, mat):
    """Small closed-profile extrusion re-centered on its centroid (detach part)."""
    cf = sum(p[0] for p in pts) / len(pts)
    cu = sum(p[1] for p in pts) / len(pts)
    local = [(f - cf, u - cu) for f, u in pts]
    n = len(local)
    verts, faces = [], []
    for side in (-1.0, 1.0):
        for f, u in local:
            verts.append((side * width / 2.0, f, u))
    A = list(range(0, n)); B = list(range(n, 2 * n))
    for i in range(n):
        j = (i + 1) % n
        faces.append((A[i], A[j], B[j], B[i]))
    faces.append(tuple(A))
    faces.append(tuple(reversed(B)))
    return mesh_from(name, verts, faces, mat, location=(0.0, cf, cu))

# ---------------- build all three ----------------
offsets = {"street": -5.5, "perf": 0.0, "super": 5.5}
bodies = {}
for tok, spec in CARS.items():
    bodies[tok] = build_car_final(tok, spec)
    bodies[tok].location.x = offsets[tok]

# ---------------- evidence shots + report ----------------
def subtree(root):
    out, stack = [], [root]
    while stack:
        o = stack.pop()
        out.append(o)
        stack.extend(o.children)
    return out

def tri_count(ob):
    if ob.type != "MESH":
        return 0
    me = ob.data
    me.calc_loop_triangles()
    return len(me.loop_triangles)

report = {"generated_by": "build_cars_final.py (finals v1)", "units": "meters",
          "note": "Lofted hulls driven by the verified blockout curves. Forward = glTF +Z after export.",
          "materials": list(MAT.keys()), "cars": []}
for tok, spec in CARS.items():
    objs = subtree(bodies[tok])
    tris = sum(tri_count(o) for o in objs)
    fs = [p[0] for p in spec["top"]] + [spec["nose"], spec["tail"]]
    us = [p[1] for p in spec["top"]]
    nodes = sorted(o.name for o in objs)
    report["cars"].append({
        "token": tok, "display_name": spec["display"], "tri_count": tris,
        "dims": {"length": round(max(fs) - min(fs), 2),
                 "width": round(2 * max(halfwidth(spec, spec["nose"] + (spec["tail"] - spec["nose"]) * i / 40)
                                        for i in range(41)), 2),
                 "height": round(max(us) + 0.03, 2)},
        "wheelbase": round(spec["axles"][1] - spec["axles"][0], 2),
        "track": round(2 * spec["track_half"], 2),
        "nodes": nodes,
    })
report_path = os.path.join(ASSETS, "cars_final_report.json")
with open(report_path, "w", encoding="utf-8") as fh:
    json.dump(report, fh, indent=2)
for c in report["cars"]:
    print("CAR", c["token"], c["display_name"], "tris:", c["tri_count"], "nodes:", len(c["nodes"]))

# ---------------- verification shot ----------------
render_ok = False
try:
    cam_data = bpy.data.cameras.new("cam")
    cam_data.lens = 35
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    from mathutils import Vector
    loc = Vector((-9.5, -13.0, 4.4))
    tgt = Vector((0.0, 0.0, 0.6))
    cam.location = loc
    cam.rotation_euler = (tgt - loc).to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam
    world = bpy.data.worlds.new("sky")
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = (0.52, 0.68, 0.88, 1.0)
    bg.inputs[1].default_value = 1.1
    scene.world = world
    sun_data = bpy.data.lights.new("sun", type="SUN")
    sun_data.energy = 3.5
    sun = bpy.data.objects.new("sun", sun_data)
    scene.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(55), 0.0, math.radians(-35))
    ground_mat = pbr("ground", (0.55, 0.57, 0.60), 0.0, 0.95)
    gv, gf = [], []
    box_into(gv, gf, (60, 60, 0.05), (0.0, 0.0, -0.025))
    mesh_from("ground", gv, gf, ground_mat)
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.image_settings.file_format = "PNG"
    for eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "BLENDER_WORKBENCH"):
        try:
            scene.render.engine = eng
            break
        except Exception:
            continue
    try:
        scene.eevee.taa_render_samples = 16
    except Exception:
        pass
    scene.render.filepath = os.path.join(SHOTS, "cars_final.png")
    bpy.ops.render.render(write_still=True)
    render_ok = True
    print("RENDER_OK", scene.render.filepath)
except Exception as exc:
    print("RENDER_SKIPPED:", exc)

# ---------------- export (centered) ----------------
for tok in CARS:
    bodies[tok].location.x = 0.0
for junk in ("ground", "cam", "sun"):
    o = bpy.data.objects.get(junk)
    if o:
        bpy.data.objects.remove(o, do_unlink=True)
glb_path = os.path.join(ASSETS, "cars.glb")
try:
    bpy.ops.export_scene.gltf(filepath=glb_path, export_format="GLB", export_apply=False)
    print("GLB_OK", glb_path)
except Exception as exc:
    print("GLB_FAILED:", exc)
print("REPORT_OK", report_path)