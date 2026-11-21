# Signal Nine — hero-car BLOCKOUTS (street / perf / super)
# Headless: blender -b -P build_cars.py
# Blockout massing with FINAL node + material naming per the settled contract:
#   <tok>_body, <tok>_glass, <tok>_wheel_fl|fr|rl|rr,
#   <tok>_bumper_f|bumper_r|hood|spoiler (origin at part centroid),
#   <tok>_lights_f|lights_r ; slots paint_street/paint_perf/paint_super/glass/lights/tire
# Blender space: car nose toward -Y (glTF exporter maps Blender -Y -> glTF +Z forward).
# Outputs: ../assets/cars.glb, ../assets/cars_blockout_report.json, ../shots/cars_blockout.png

import bpy
import bmesh
import json
import math
import os
from mathutils import Vector

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

# ---------------- materials (final slot names) ----------------
def pbr(name, color, metallic=0.0, rough=0.5):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (*color, 1.0)
    b.inputs["Metallic"].default_value = metallic
    b.inputs["Roughness"].default_value = rough
    return m

MAT = {
    "paint_street": pbr("paint_street", (1.00, 0.42, 0.08), 0.15, 0.35),
    "paint_perf":   pbr("paint_perf",   (1.00, 0.78, 0.05), 0.15, 0.35),
    "paint_super":  pbr("paint_super",  (0.72, 0.78, 0.88), 0.85, 0.25),
    "glass":        pbr("glass",        (0.03, 0.05, 0.07), 0.40, 0.10),
    "lights":       pbr("lights",       (1.00, 0.98, 0.90), 0.00, 0.20),
    "tire":         pbr("tire",         (0.02, 0.02, 0.02), 0.00, 0.90),
}

# ---------------- mesh helpers ----------------
def mesh_from(name, verts, faces, mat, location):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate()
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    ob.location = location
    if mat is not None:
        me.materials.append(mat)
    scene.collection.objects.link(ob)
    return ob

def extruded_profile(name, pts, width, mat, location=(0, 0, 0)):
    """pts: closed loop of (forward, up) meters; forward<0 = nose.
    Extruded along X (width). Vertex y = forward (nose ends at -Y)."""
    n = len(pts)
    verts, faces = [], []
    for side in (-1.0, 1.0):
        for f, u in pts:
            verts.append((side * width / 2.0, f, u))
    A = list(range(0, n))
    B = list(range(n, 2 * n))
    for i in range(n):
        j = (i + 1) % n
        faces.append((A[i], A[j], B[j], B[i]))
    faces.append(tuple(A))
    faces.append(tuple(reversed(B)))
    return mesh_from(name, verts, faces, mat, location)

def profile_part(name, pts, width, mat):
    """Detachable built from a profile: re-centered on its own centroid,
    origin placed at the centroid (contract requirement)."""
    cf = sum(p[0] for p in pts) / len(pts)
    cu = sum(p[1] for p in pts) / len(pts)
    local = [(f - cf, u - cu) for f, u in pts]
    return extruded_profile(name, local, width, mat, location=(0.0, cf, cu))

def box_at(name, dims, center, mat):
    dx, dy, dz = dims
    verts = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                verts.append((sx * dx / 2, sy * dy / 2, sz * dz / 2))
    faces = [(0, 1, 3, 2), (4, 5, 7, 6), (0, 4, 5, 1),
             (2, 3, 7, 6), (0, 2, 6, 4), (1, 3, 7, 5)]
    return mesh_from(name, verts, faces, mat, center)

def multi_box(name, boxes, mat, location):
    """boxes: [(dims, center_local), ...] merged into one mesh; origin = location."""
    verts, faces = [], []
    for dims, c in boxes:
        dx, dy, dz = dims
        cx, cy, cz = c
        base = len(verts)
        for sx in (-1, 1):
            for sy in (-1, 1):
                for sz in (-1, 1):
                    verts.append((cx + sx * dx / 2, cy + sy * dy / 2, cz + sz * dz / 2))
        faces.extend([(base + 0, base + 1, base + 3, base + 2),
                      (base + 4, base + 5, base + 7, base + 6),
                      (base + 0, base + 4, base + 5, base + 1),
                      (base + 2, base + 3, base + 7, base + 6),
                      (base + 0, base + 2, base + 6, base + 4),
                      (base + 1, base + 3, base + 7, base + 5)])
    return mesh_from(name, verts, faces, mat, location)

def circle_pts(r, seg=20):
    return [(r * math.sin(2 * math.pi * i / seg), r * math.cos(2 * math.pi * i / seg))
            for i in range(seg)]

# ---------------- car specs (blockout proportions, meters) ----------------
CARS = {
    "street": {
        "display": "Vantoro RS",
        "width": 1.85, "wheel_r": 0.33, "tire_w": 0.28,
        "profile": [(-2.15, 0.25), (-2.15, 0.55), (-1.80, 0.66), (-0.60, 0.74),
                    (0.00, 1.22), (0.90, 1.13), (1.70, 0.94), (2.15, 0.84),
                    (2.15, 0.30), (1.20, 0.17), (-1.20, 0.17)],
        "canopy": [(-0.60, 0.72), (0.00, 1.24), (0.90, 1.15), (1.60, 0.96)],
        "canopy_w": 0.82,
        "axle_f": -1.35, "axle_r": 1.10, "track_half": 0.78,
        "hood_pts": [(-2.05, 0.62), (-0.65, 0.77), (-0.65, 0.72), (-2.05, 0.57)],
        "bump_f": (-2.13, 0.38), "bump_r": (2.13, 0.42),
        "spoiler": {"type": "lip", "f": 1.95, "u": 0.91, "chord": 0.26},
        "light_f": (-2.10, 0.48), "light_r": (2.10, 0.52),
    },
    "perf": {
        "display": "Kestrel MR",
        "width": 1.95, "wheel_r": 0.33, "tire_w": 0.30,
        "profile": [(-2.20, 0.22), (-2.20, 0.42), (-1.50, 0.55), (-0.80, 0.68),
                    (-0.45, 1.15), (0.35, 1.10), (1.10, 0.82), (2.20, 0.72),
                    (2.20, 0.28), (1.30, 0.15), (-1.30, 0.15)],
        "canopy": [(-0.80, 0.66), (-0.45, 1.17), (0.35, 1.12), (0.85, 0.84)],
        "canopy_w": 0.82,
        "axle_f": -1.45, "axle_r": 1.15, "track_half": 0.82,
        "hood_pts": [(-2.15, 0.475), (-0.90, 0.705), (-0.90, 0.655), (-2.15, 0.425)],
        "bump_f": (-2.16, 0.34), "bump_r": (2.16, 0.48),
        "spoiler": {"type": "wing", "f": 2.05, "u": 1.02, "chord": 0.36, "strut_h": 0.28},
        "light_f": (-2.18, 0.36), "light_r": (2.18, 0.55),
    },
    "super": {
        "display": "Apex GT1",
        "width": 2.00, "wheel_r": 0.34, "tire_w": 0.32,
        "profile": [(-2.30, 0.15), (-2.30, 0.38), (-1.60, 0.52), (-0.90, 0.62),
                    (-0.50, 1.10), (0.15, 1.08), (0.90, 0.75), (2.30, 0.68),
                    (2.30, 0.22), (1.40, 0.12), (-1.40, 0.12)],
        "canopy": [(-0.90, 0.60), (-0.50, 1.12), (0.15, 1.10), (0.70, 0.77)],
        "canopy_w": 0.62,
        "axle_f": -1.55, "axle_r": 1.17, "track_half": 0.83,
        "hood_pts": [(-2.25, 0.435), (-1.00, 0.655), (-1.00, 0.605), (-2.25, 0.385)],
        "bump_f": (-2.26, 0.28), "bump_r": (2.26, 0.44),
        "spoiler": {"type": "wing", "f": 2.15, "u": 1.05, "chord": 0.42, "strut_h": 0.36},
        "light_f": (-2.28, 0.30), "light_r": (2.28, 0.52),
    },
}

# ---------------- builders ----------------
def build_car(tok, spec):
    body = extruded_profile(tok + "_body", spec["profile"], spec["width"], MAT["paint_" + tok])
    parts = [body]

    canopy = extruded_profile(tok + "_glass", spec["canopy"],
                              spec["width"] * spec["canopy_w"], MAT["glass"])
    parts.append(canopy)

    for key, axle in (("fl", spec["axle_f"]), ("fr", spec["axle_f"]),
                      ("rl", spec["axle_r"]), ("rr", spec["axle_r"])):
        x = -spec["track_half"] if key in ("fl", "rl") else spec["track_half"]
        wheel = extruded_profile(tok + "_wheel_" + key, circle_pts(spec["wheel_r"]),
                                 spec["tire_w"], MAT["tire"], location=(x, axle, spec["wheel_r"]))
        parts.append(wheel)

    parts.append(profile_part(tok + "_hood", spec["hood_pts"],
                              spec["width"] * 0.90, MAT["paint_" + tok]))

    for end, (bf, bu) in (("f", spec["bump_f"]), ("r", spec["bump_r"])):
        parts.append(box_at(tok + "_bumper_" + end,
                            (spec["width"] * 0.98, 0.16, 0.22), (0.0, bf, bu),
                            MAT["paint_" + tok]))

    for end, (lf, lu) in (("f", spec["light_f"]), ("r", spec["light_r"])):
        parts.append(box_at(tok + "_lights_" + end,
                            (spec["width"] * 0.55, 0.07, 0.09), (0.0, lf, lu),
                            MAT["lights"]))

    sp = spec["spoiler"]
    if sp["type"] == "lip":
        parts.append(profile_part(
            tok + "_spoiler",
            [(sp["f"] - sp["chord"] / 2, sp["u"] - 0.02),
             (sp["f"] + sp["chord"] / 2, sp["u"] + 0.015),
             (sp["f"] + sp["chord"] / 2, sp["u"] - 0.025),
             (sp["f"] - sp["chord"] / 2, sp["u"] - 0.065)],
            spec["width"] * 0.88, MAT["paint_" + tok]))
    else:
        boxes = [((spec["width"] * 0.88, sp["chord"], 0.05), (0.0, 0.0, 0.0))]
        for sx in (-1, 1):
            boxes.append(((0.06, 0.08, sp["strut_h"]),
                          (sx * spec["width"] * 0.31, 0.0, -(sp["strut_h"] / 2 + 0.025))))
        parts.append(multi_box(tok + "_spoiler", boxes, MAT["paint_" + tok],
                               location=(0.0, sp["f"], sp["u"])))

    for p in parts:
        if p is not body:
            p.parent = body
    return body

offsets = {"street": -5.5, "perf": 0.0, "super": 5.5}
bodies = {}
for tok, spec in CARS.items():
    bodies[tok] = build_car(tok, spec)
    bodies[tok].location.x = offsets[tok]

# ---------------- evidence report ----------------
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

report = {"generated_by": "build_cars.py (blockout)", "units": "meters",
          "note": "Blockout massing, final node/material naming. Car forward = glTF +Z after export.",
          "materials": list(MAT.keys()), "cars": []}
for tok, spec in CARS.items():
    objs = subtree(bodies[tok])
    tris = sum(tri_count(o) for o in objs)
    fs = [p[0] for p in spec["profile"]]
    us = [p[1] for p in spec["profile"]]
    report["cars"].append({
        "token": tok, "display_name": spec["display"], "tri_count": tris,
        "dims": {"length": round(max(fs) - min(fs), 3), "width": spec["width"],
                 "height": round(max(us), 3)},
        "wheelbase": round(spec["axle_r"] - spec["axle_f"], 3),
        "track": round(2 * spec["track_half"], 3),
        "wheel_radius": spec["wheel_r"],
        "nodes": sorted(o.name for o in objs),
    })
report_path = os.path.join(ASSETS, "cars_blockout_report.json")
with open(report_path, "w", encoding="utf-8") as fh:
    json.dump(report, fh, indent=2)
for c in report["cars"]:
    print("CAR", c["token"], c["display_name"], "tris:", c["tri_count"],
          "dims:", c["dims"], "wb:", c["wheelbase"], "track:", c["track"])

# ---------------- verification shot (3/4 front-left) ----------------
render_ok = False
try:
    cam_data = bpy.data.cameras.new("cam")
    cam_data.lens = 35
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
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
    box_at("ground", (60, 60, 0.05), (0.0, 0.0, -0.025), ground_mat)

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
    scene.render.filepath = os.path.join(SHOTS, "cars_blockout.png")
    bpy.ops.render.render(write_still=True)
    render_ok = True
    print("RENDER_OK", scene.render.filepath)
except Exception as exc:
    print("RENDER_SKIPPED:", exc)

# ---------------- export (cars centered at origin) ----------------
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