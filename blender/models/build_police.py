# Signal Nine — POLICE CRUISER (build_police.py) — Pursuit mode asset, M2 spine item 1
# Headless: blender -b -P blender/models/build_police.py
# Generic 2002-era full-size patrol coupe — two-tone black/white, lightbar,
# push bar, spotlight. NO real-brand shapes, badges, or lettering.
# Node contract (hero-pattern, for Pursuit AI built against the real asset):
#   police_body, _glass, _roof (black cap), _trunk (black cap), _hood (black, detach),
#   _interior, _wheel_* + _rim_* (hub-local pairs), _lights_f/_lights_r,
#   police_lightbar + police_lightbar_red/_blue (coder pulses emission),
#   _bumper_f/_bumper_r (detach, centroid origins), police_pushbar, police_spot.
# Slots: paint_police_white / paint_police_black / lights_b are NEW (flag to coder).
# Outputs: ../../assets/police.glb + police_report.json + shots/police.png
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
    "paint_police_white": pbr("paint_police_white", (0.92, 0.93, 0.94), 0.15, 0.35),
    "paint_police_black": pbr("paint_police_black", (0.06, 0.06, 0.07), 0.15, 0.35),
    "glass": pbr("glass", (0.03, 0.05, 0.07), 0.40, 0.10),
    "lights": pbr("lights", (1.00, 0.98, 0.90), 0.0, 0.20),
    "lights_r": pbr("lights_r", (0.70, 0.07, 0.05), 0.0, 0.25),
    "lights_b": pbr("lights_b", (0.10, 0.25, 0.90), 0.0, 0.25),
    "tire": pbr("tire", (0.03, 0.03, 0.03), 0.0, 0.9),
    "rim": pbr("rim", (0.70, 0.71, 0.73), 0.9, 0.35),
    "dark": pbr("dark", (0.10, 0.10, 0.12), 0.0, 0.85),
    "metal": pbr("metal", (0.60, 0.62, 0.65), 0.8, 0.4),
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

def loft(name, rings, mat, smooth=True):
    verts = []
    for ring in rings:
        verts.extend(ring)
    m = len(rings[0])
    faces = []
    for s in range(len(rings) - 1):
        for i in range(m):
            j = (i + 1) % m
            faces.append((s * m + i, s * m + j, (s + 1) * m + j, (s + 1) * m + i))
    faces.append(tuple(range(m - 1, -1, -1)))
    base = (len(rings) - 1) * m
    faces.append(tuple(range(base, base + m)))
    return mesh_from(name, verts, faces, mat, smooth=smooth)

def centroid_loft(name, rings, mat):
    pts = [p for ring in rings for p in ring]
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    cz = sum(p[2] for p in pts) / len(pts)
    shifted = [[(p[0] - cx, p[1] - cy, p[2] - cz) for p in ring] for ring in rings]
    return loft(name, shifted, mat), (cx, cy, cz)

def gauss(x, s):
    return math.exp(-(x * x) / (2 * s * s))

# ---------------- cruiser curves (generic full-size patrol coupe) ----------------
NOSE, TAIL, FLOOR = -2.55, 2.55, 0.18
TOP = [(-2.55, 0.62), (-1.20, 0.80), (-0.70, 0.88), (-0.10, 1.42),
       (0.90, 1.40), (1.60, 1.02), (2.55, 0.98)]
BELT = [(-2.55, 0.56), (-0.70, 0.74), (-0.10, 0.86), (0.90, 0.86), (2.55, 0.84)]
PLAN = [(-2.55, 0.84), (-1.50, 0.94), (0.00, 0.965), (1.30, 0.95), (2.55, 0.88)]
FLARES = (-1.50, 1.45, 0.045)
GH = (-0.70, 1.35, 0.84)
WHEEL_R, TIRE_W, TRACK_HALF = 0.34, 0.26, 0.81
AXLES = (-1.48, 1.47)

HULL_RING = [(-1.00, 0.00), (-1.00, 0.45), (-0.96, 0.80), (-0.90, 1.00),
             (-0.45, 1.02), (0.00, 1.03), (0.45, 1.02), (0.90, 1.00),
             (0.96, 0.80), (1.00, 0.45), (1.00, 0.00), (0.50, 0.00), (-0.50, 0.00)]
GH_RING = [(-1.00, 0.00), (-0.88, 0.55), (-0.62, 0.92), (0.00, 1.00),
           (0.62, 0.92), (0.88, 0.55), (1.00, 0.00)]

def halfwidth(f):
    w = curve(PLAN, f)
    fa, ra, amp = FLARES
    return w + amp * (gauss(f - fa, 0.55) + gauss(f - ra, 0.55))

def deck_of(f):
    if GH[0] <= f <= GH[1]:
        return curve(BELT, f)
    return curve(TOP, f)

def hull_ring(f):
    belt = min(curve(BELT, f), deck_of(f))
    w = halfwidth(f)
    return [(lf * w, f, FLOOR + uf * (belt - FLOOR)) for lf, uf in HULL_RING]

def gh_ring(f):
    belt = curve(BELT, f)
    top = curve(TOP, f)
    gw = halfwidth(f) * GH[2]
    return [(lf * gw, f, belt + uf * (top - belt)) for lf, uf in GH_RING]

def build_wheel(name, rim_name, x, f_axle):
    verts, faces = [], []
    R, r = WHEEL_R - 0.10, 0.10
    SU, SV = 22, 12
    for i in range(SU):
        a = 2 * math.pi * i / SU
        for j in range(SV):
            b = 2 * math.pi * j / SV
            rr = R + r * math.cos(b)
            verts.append(((TIRE_W / 2) * math.sin(b), rr * math.sin(a), rr * math.cos(a)))
    for i in range(SU):
        for j in range(SV):
            i2, j2 = (i + 1) % SU, (j + 1) % SV
            faces.append((i * SV + j, i2 * SV + j, i2 * SV + j2, i * SV + j2))
    wheel = mesh_from(name, verts, faces, MAT["tire"], smooth=True)
    rv, rf = [], []
    rr = R - 0.02
    for xs in (-TIRE_W * 0.26, TIRE_W * 0.26):
        for k in range(14):
            a = 2 * math.pi * k / 14
            rv.append((xs, rr * math.sin(a), WHEEL_R + rr * math.cos(a)))
    for k in range(14):
        k2 = (k + 1) % 14
        rf.append((k, k2, 14 + k2, 14 + k))
    rf.append(tuple(range(14)))
    rf.append(tuple(range(14, 28)))
    rim = mesh_from(rim_name, rv, rf, MAT["rim"])
    return wheel, rim

def cap_panel(name, f0, f1, mat, width_frac=0.94, lift=0.012):
    """Thin painted cap panel (roof/hood/trunk in the black two-tone)."""
    rings = []
    for i in range(6):
        f = f0 + (f1 - f0) * i / 5
        top = curve(TOP, f) + lift
        hw = halfwidth(f) * width_frac
        rings.append([(-hw, f, top - 0.02), (-hw * 0.6, f, top + 0.02),
                      (0.0, f, top + 0.035), (hw * 0.6, f, top + 0.02),
                      (hw, f, top - 0.02), (0.0, f, top - 0.045)])
    part, _ = centroid_loft(name, rings, mat)
    return part

# ---------------- build ----------------
parts = []
hull_stations = []
for i in range(30):
    f = NOSE + (TAIL - NOSE) * i / 29
    hull_stations.append(hull_ring(f))
body = loft("police_body", hull_stations, MAT["paint_police_white"])
parts.append(body)

gh_stations = []
for i in range(12):
    f = GH[0] + (GH[1] - GH[0]) * i / 11
    gh_stations.append(gh_ring(f))
parts.append(loft("police_glass", gh_stations, MAT["glass"]))

parts.append(cap_panel("police_roof", GH[0] + 0.35, GH[1] - 0.30, MAT["paint_police_black"], 0.60))
parts.append(cap_panel("police_hood", NOSE + 0.30, GH[0] - 0.12, MAT["paint_police_black"], 0.88))
parts.append(cap_panel("police_trunk", GH[1] + 0.25, TAIL - 0.12, MAT["paint_police_black"], 0.90))

iv, ifc = [], []
cab0, cab1 = GH[0] + 0.30, GH[1] - 0.30
box_into(iv, ifc, (1.10, 0.32, 0.16), (0.0, cab0 + 0.18, FLOOR + 0.44))
for sx in (-1, 1):
    box_into(iv, ifc, (0.44, 0.50, 0.32),
             (sx * 0.38, (cab0 + cab1) / 2 - 0.15, FLOOR + 0.36))
box_into(iv, ifc, (1.65, (cab1 - cab0) * 0.9, 0.05), (0.0, (cab0 + cab1) / 2, FLOOR + 0.10))
for axle in AXLES:
    for sx in (-1, 1):
        box_into(iv, ifc, (1.05, TIRE_W + 0.16, WHEEL_R * 1.5),
                 (sx * (TRACK_HALF - 0.10), axle, WHEEL_R * 0.72))
parts.append(mesh_from("police_interior", iv, ifc, MAT["dark"]))

for key, axle in (("fl", AXLES[0]), ("fr", AXLES[0]), ("rl", AXLES[1]), ("rr", AXLES[1])):
    x = -TRACK_HALF if key in ("fl", "rl") else TRACK_HALF
    wheel, rim = build_wheel("police_wheel_" + key, "police_rim_" + key, x, axle)
    wheel.location = (x, axle, WHEEL_R)
    rim.location = (x, axle, WHEEL_R)
    parts.extend([wheel, rim])

lv, lf = [], []
for sx in (-1, 1):
    box_into(lv, lf, (0.36, 0.08, 0.11), (sx * halfwidth(NOSE + 0.1) * 0.55, NOSE + 0.02, 0.62))
parts.append(mesh_from("police_lights_f", lv, lf, MAT["lights"]))
rv, rf = [], []
for sx in (-1, 1):
    box_into(rv, rf, (0.32, 0.07, 0.10), (sx * halfwidth(TAIL - 0.1) * 0.55, TAIL - 0.02, 0.66))
parts.append(mesh_from("police_lights_r", rv, rf, MAT["lights_r"]))

# lightbar: base + red/blue lens groups (coder pulses emission on the color nodes)
base_u = curve(TOP, 0.35) + 0.03
lbv, lbf = [], []
box_into(lbv, lbf, (1.25, 0.30, 0.06), (0.0, 0.35, base_u))
parts.append(mesh_from("police_lightbar", lbv, lbf, MAT["dark"]))
red_v, red_f, blue_v, blue_f = [], [], [], []
for k, sx in enumerate((-1, 1)):
    box_into(red_v, red_f, (0.24, 0.24, 0.10), (sx * 0.44, 0.35, base_u + 0.09))
for k, sx in enumerate((-1, 1)):
    box_into(blue_v, blue_f, (0.24, 0.24, 0.10), (sx * 0.15, 0.35, base_u + 0.09))
parts.append(mesh_from("police_lightbar_red", red_v, red_f, MAT["lights_r"]))
parts.append(mesh_from("police_lightbar_blue", blue_v, blue_f, MAT["lights_b"]))

# push bar + A-pillar spotlight
pv, pf = [], []
for sx in (-1, 1):
    box_into(pv, pf, (0.05, 0.05, 0.55), (sx * 0.52, NOSE - 0.12, 0.48))
box_into(pv, pf, (1.14, 0.05, 0.05), (0.0, NOSE - 0.12, 0.36))
box_into(pv, pf, (1.14, 0.05, 0.05), (0.0, NOSE - 0.12, 0.62))
parts.append(mesh_from("police_pushbar", pv, pf, MAT["metal"]))
sv, sf = [], []
box_into(sv, sf, (0.07, 0.07, 0.16), (-halfwidth(GH[0] + 0.15) * 0.70, GH[0] + 0.15, curve(BELT, GH[0] + 0.15) + 0.16))
parts.append(mesh_from("police_spot", sv, sf, MAT["dark"]))

# detachable bumpers (centroid origins)
def bumper_ring(w, f):
    bu = 0.42
    return [(-0.98 * w, f, FLOOR + 0.06), (-0.98 * w, f, bu), (-0.50 * w, f, bu + 0.10),
            (0.50 * w, f, bu + 0.10), (0.98 * w, f, bu), (0.98 * w, f, FLOOR + 0.06),
            (0.50 * w, f, FLOOR + 0.02), (-0.50 * w, f, FLOOR + 0.02)]
bf_stations = [bumper_ring(halfwidth(NOSE - 0.05 + 0.16 * i / 2), NOSE - 0.05 + 0.16 * i / 2)
               for i in range(3)]
bump_f, _ = centroid_loft("police_bumper_f", bf_stations, MAT["paint_police_white"])
parts.append(bump_f)
br_stations = [bumper_ring(halfwidth(TAIL + 0.05 - 0.16 * i / 2), TAIL + 0.05 - 0.16 * i / 2)
               for i in range(3)]
bump_r, _ = centroid_loft("police_bumper_r", br_stations, MAT["paint_police_white"])
parts.append(bump_r)

for p in parts:
    if p is not body:
        p.parent = body

# ---------------- report + shot + export ----------------
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

objs = subtree(body)
tris = sum(tri_count(o) for o in objs)
report = {"generated_by": "build_police.py", "units": "meters",
          "note": "Pursuit cruiser, finals fidelity, hero node contract. Forward = glTF +Z after export. Generic two-tone patrol coupe — no real-brand marks. New slots: paint_police_white, paint_police_black, lights_b.",
          "materials": list(MAT.keys()),
          "dims": {"length": 5.10, "width": 1.95, "height": 1.45},
          "wheelbase": round(AXLES[1] - AXLES[0], 2), "track": round(2 * TRACK_HALF, 2),
          "wheel_radius": WHEEL_R, "tri_count": tris,
          "nodes": sorted(o.name for o in objs)}
report_path = os.path.join(ASSETS, "police_report.json")
with open(report_path, "w", encoding="utf-8") as fh:
    json.dump(report, fh, indent=2)
print("POLICE tris:", tris, "nodes:", len(report["nodes"]))

try:
    cam_data = bpy.data.cameras.new("cam")
    cam_data.lens = 38
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    from mathutils import Vector
    loc = Vector((-6.5, -9.5, 3.4))
    tgt = Vector((0.0, 0.0, 0.7))
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
    gv, gf = [], []
    box_into(gv, gf, (40, 40, 0.05), (0.0, 0.0, -0.025))
    mesh_from("ground", gv, gf, pbr("ground", (0.55, 0.57, 0.60), 0.0, 0.95))
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.image_settings.file_format = "PNG"
    for eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "BLENDER_WORKBENCH"):
        try:
            scene.render.engine = eng
            break
        except Exception:
            continue
    scene.render.filepath = os.path.join(SHOTS, "police.png")
    bpy.ops.render.render(write_still=True)
    print("RENDER_OK", scene.render.filepath)
except Exception as exc:
    print("RENDER_SKIPPED:", exc)

for junk in ("ground", "cam", "sun"):
    o = bpy.data.objects.get(junk)
    if o:
        bpy.data.objects.remove(o, do_unlink=True)
glb_path = os.path.join(ASSETS, "police.glb")
try:
    bpy.ops.export_scene.gltf(filepath=glb_path, export_format="GLB", export_apply=False)
    print("GLB_OK", glb_path)
except Exception as exc:
    print("GLB_FAILED:", exc)
print("REPORT_OK", report_path)