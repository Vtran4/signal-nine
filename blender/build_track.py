# Signal Nine — coastal circuit greybox generator (build_track.py)
# Headless: blender -b -P blender/build_track.py
# Emits: assets/set.blend, assets/tracks.glb (preliminary), assets/tracks_data.json,
#        assets/env_coast.jpg (early pano), blender/shots/track_top.png + track_start.png
# Contract: centerline samples every 2 m, closed loop (no duplicated wrap sample),
# furniture {type, s, lateral, node} with node = exact glb node name.
# JSON/glb world space = glTF axes (y-up): json = (x, z_blender, -y_blender).
import bpy
import bmesh
import json
import math
import os
import random
from math import radians, sin, cos

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
ASSETS = os.path.join(ROOT, "assets")
SHOTS = os.path.join(HERE, "shots")
os.makedirs(ASSETS, exist_ok=True)
os.makedirs(SHOTS, exist_ok=True)
random.seed(9)

try:
    bpy.ops.wm.read_factory_settings(use_empty=True)
except Exception:
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
scene = bpy.context.scene

# ---------------- materials (greybox; bake.py re-materials per atlas group) ----------------
def pbr(name, color, metallic=0.0, rough=0.8):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (*color, 1.0)
    b.inputs["Metallic"].default_value = metallic
    b.inputs["Roughness"].default_value = rough
    return m

MAT = {
    "road":   pbr("road",   (0.42, 0.42, 0.44)),
    "terrain": pbr("terrain", (0.62, 0.52, 0.30)),
    "ocean":  pbr("ocean",  (0.05, 0.22, 0.45), 0.0, 0.25),
    "metal":  pbr("metal",  (0.65, 0.67, 0.70), 0.6, 0.45),
    "white":  pbr("white",  (0.85, 0.85, 0.82)),
}

# ---------------- mesh helpers ----------------
def mesh_from(name, verts, faces, mat, location=(0, 0, 0)):
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

def smoothstep(a, b, x):
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)

def dist3(a, b):
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2)

# ---------------- coastal spline (closed loop) ----------------
CTRL = [(620, -420, 26), (640, -140, 28), (660, 140, 30), (620, 380, 32),
        (480, 560, 36), (260, 620, 42), (0, 600, 46), (-240, 480, 50),
        (-420, 300, 52), (-500, 80, 48), (-420, -100, 42), (-300, -260, 38),
        (-140, -380, 34), (60, -460, 28), (280, -500, 24), (480, -480, 24)]

def catmull(p0, p1, p2, p3, t):
    t2, t3 = t * t, t * t * t
    return tuple(0.5 * ((2 * p1[i]) + (-p0[i] + p2[i]) * t
                        + (2 * p0[i] - 5 * p1[i] + 4 * p2[i] - p3[i]) * t2
                        + (-p0[i] + 3 * p1[i] - 3 * p2[i] + p3[i]) * t3)
                 for i in range(3))

dense = []
n_ctrl = len(CTRL)
STEPS = 160
for i in range(n_ctrl):
    p0, p1 = CTRL[(i - 1) % n_ctrl], CTRL[i]
    p2, p3 = CTRL[(i + 1) % n_ctrl], CTRL[(i + 2) % n_ctrl]
    for j in range(STEPS):
        dense.append(catmull(p0, p1, p2, p3, j / STEPS))

SPACING = 2.0
def resample_closed(points, spacing):
    """Uniform arc-length samples over a CLOSED loop: n = round(total/spacing),
    step = total/n — the wrap segment is exactly step too (no remainder seam)."""
    n_pts = len(points)
    total = sum(dist3(points[i], points[(i + 1) % n_pts]) for i in range(n_pts))
    n = max(8, int(round(total / spacing)))
    step = total / n
    out = []
    idx, acc = 0, 0.0
    for k in range(n):
        target = k * step
        while idx < n_pts - 1:
            seg = dist3(points[idx], points[idx + 1])
            if acc + seg >= target:
                break
            acc += seg
            idx += 1
        a = points[idx]
        b = points[(idx + 1) % n_pts]
        seg = dist3(a, b) or 1e-9
        f = max(0.0, min(1.0, (target - acc) / seg))
        out.append(tuple(a[c] + (b[c] - a[c]) * f for c in range(3)))
    return out

S = resample_closed(dense, SPACING)
N = len(S)
TRACK_LEN = N * SPACING
print("TRACK samples:", N, "length_m:", round(TRACK_LEN, 1))

def tangents_lefts(samples):
    n = len(samples)
    tans, lefts = [], []
    for i in range(n):
        a = samples[(i - 1) % n]
        b = samples[(i + 1) % n]
        t = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        L = math.sqrt(t[0] ** 2 + t[1] ** 2 + t[2] ** 2) or 1.0
        t = (t[0] / L, t[1] / L, t[2] / L)
        tans.append(t)
        lefts.append((-t[1], t[0], 0.0))  # up x tangent (left-positive)
    return tans, lefts

TAN, LEFT = tangents_lefts(S)

def curvature(i):
    a, b = TAN[(i - 2) % N], TAN[(i + 2) % N]
    dot = max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]))
    return math.acos(dot) / (4 * SPACING)

def cross_z(a, b):
    return a[0] * b[1] - a[1] * b[0]

# ---------------- road ribbon ----------------
HW = 5.0  # roadWidth 10
def build_road():
    verts, faces, uvs = [], [], []
    for i, p in enumerate(S):
        l = LEFT[i]
        verts.append((p[0] + l[0] * HW, p[1] + l[1] * HW, p[2]))
        uvs.append((0.0, i * SPACING / 20.0))
    for i, p in enumerate(S):
        l = LEFT[i]
        verts.append((p[0] - l[0] * HW, p[1] - l[1] * HW, p[2]))
        uvs.append((1.0, i * SPACING / 20.0))
    for i in range(N - 1):
        faces.append((i, N + i, N + i + 1, i + 1))
    ob = mesh_from("coastal_road", verts, faces, MAT["road"])
    uv = ob.data.uv_layers.new(name="UVMap")
    for poly in ob.data.polygons:
        for li in poly.loop_indices:
            vi = ob.data.loops[li].vertex_index
            uv.data[li].uv = uvs[vi]
    return ob

road = build_road()

# ---------------- terrain (flattens under road, cliffs into ocean east) ----------------
TX0, TX1, TY0, TY1 = -700.0, 800.0, -700.0, 860.0
CELL = 15.0
NX = int((TX1 - TX0) / CELL)
NY = int((TY1 - TY0) / CELL)
road_coarse = S[::8]
def terrain_h(x, y):
    # noise tapers to 0 approaching the eastern shore: the waterline then
    # crosses on the smooth cliff step alone (no 15m-cell stair silhouette)
    shore_taper = 1.0 - smoothstep(0.0, 1.0, (x - 480.0) / 120.0)
    h = ((sin(x * 0.0021 + 1.3) * cos(y * 0.0017 + 0.7) * 9.0
          + sin(x * 0.0043 + 0.2) * sin(y * 0.0039 + 1.1) * 5.0) * shore_taper
         + 14.0)
    best, bz = 1e9, 0.0
    for p in road_coarse:
        d = (p[0] - x) ** 2 + (p[1] - y) ** 2
        if d < best:
            best, bz = d, p[2]
    d = math.sqrt(best)
    near = 1.0 - smoothstep(6.0, 22.0, d)  # 1 inside road corridor, 0 beyond
    if d < 22.0:
        h = h * (1 - near) + (bz - 0.6) * near
    # cliff into the ocean — suppressed inside the corridor so the road keeps
    # its shoulder and the plunge happens just past the guardrail line
    h -= 55.0 * smoothstep(0.0, 1.0, (x - 540.0) / 220.0) * (1.0 - near)
    h -= 18.0 * smoothstep(0.0, 1.0, (-y - 560.0) / 240.0)  # southern valley exit
    return h

def build_terrain():
    verts = []
    for iy in range(NY + 1):
        for ix in range(NX + 1):
            x = TX0 + ix * CELL
            y = TY0 + iy * CELL
            verts.append((x, y, terrain_h(x, y)))
    faces = []
    def v(ix, iy):
        return iy * (NX + 1) + ix
    for iy in range(NY):
        for ix in range(NX):
            faces.append((v(ix, iy), v(ix + 1, iy), v(ix + 1, iy + 1), v(ix, iy + 1)))
    return mesh_from("coastal_terrain", verts, faces, MAT["terrain"])

terrain = build_terrain()

# ---------------- ocean ----------------
ocean = mesh_from("coastal_ocean",
                  [(700, -1800, -0.25), (3200, -1800, -0.25),
                   (3200, 1800, -0.25), (700, 1800, -0.25)],
                  [(0, 1, 2, 3)], MAT["ocean"])

# ---------------- furniture ----------------
furniture = []

def pad(s):
    return f"{int(round(s)):04d}"

def ring_prism(name, cx, cy, z0, z1, r, seg, mat):
    verts, faces = [], []
    for z in (z0, z1):
        for k in range(seg):
            a = 2 * math.pi * k / seg
            verts.append((cx + r * sin(a), cy + r * cos(a), z))
    top = list(range(seg)); bot = list(range(seg, 2 * seg))
    for k in range(seg):
        j = (k + 1) % seg
        faces.append((top[k], top[j], bot[j], bot[k]))
    faces.append(tuple(top))
    faces.append(tuple(reversed(bot)))
    return mesh_from(name, verts, faces, mat, (0, 0, 0))

def add_box_verts(verts, faces, dims, center, yaw=0.0):
    dx, dy, dz = dims
    cx, cy, cz = center
    base = len(verts)
    ca, sa = cos(yaw), sin(yaw)
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                lx, ly, lz = sx * dx / 2, sy * dy / 2, sz * dz / 2
                verts.append((cx + lx * ca - ly * sa, cy + lx * sa + ly * ca, cz + lz))
    for off, f in enumerate([(0, 1, 3, 2), (4, 5, 7, 6), (0, 4, 5, 1),
                             (2, 3, 7, 6), (0, 2, 6, 4), (1, 3, 7, 5)]):
        faces.append(tuple(vi + base for vi in f))

def guard_runs():
    guarded = set()
    runs = []
    zones, cur = [], []
    for i in range(N):
        if curvature(i) > 0.0045:
            cur.append(i)
        else:
            if cur:
                zones.append(cur)
            cur = []
    if cur:
        zones.append(cur)
    merged = []
    for z in zones:
        if merged and z[0] - merged[-1][-1] <= 3:
            merged[-1].extend(z)
        else:
            merged.append(z)
    for z in merged:
        if len(z) >= 8:
            cz = sum(cross_z(TAN[(i - 1) % N], TAN[(i + 1) % N]) for i in z)
            runs.append((z, -6.0 if cz > 0 else 6.0))
            guarded.update(z)
    cliff, allz = [], []
    for i in range(N):
        if S[i][0] > 570 and i not in guarded:
            cliff.append(i)
        else:
            if len(cliff) >= 8:
                allz.append(cliff)
            cliff = []
    if len(cliff) >= 8:
        allz.append(cliff)
    for z in allz:
        runs.append((z, -6.0))
    counts = {"full": 0, "lod1": 0, "lod2": 0}
    for z, outer in runs:
        s0 = z[0] * SPACING
        name = "props_guard_" + pad(s0)
        for lod, post_step in (("full", 2), ("lod1", 4), ("lod2", 99)):
            verts, faces = [], []
            idxs = z[::2] if lod != "full" else z
            for i in idxs:
                p, l = S[i], LEFT[i]
                bx, by = p[0] + l[0] * outer, p[1] + l[1] * outer
                verts.extend([(bx, by, p[2] + 0.55), (bx, by, p[2] + 0.80)])
            m = len(idxs)
            for k in range(m - 1):
                faces.append((2 * k, 2 * k + 2, 2 * k + 3, 2 * k + 1))
            if lod != "lod2":
                step = post_step * 2  # posts walk the full-sample grid
                for gi in range(z[0], z[-1] + 1, step):
                    gi = min(gi, z[-1])
                    p, l = S[gi], LEFT[gi]
                    add_box_verts(verts, faces, (0.14, 0.14, 0.62),
                                  (p[0] + l[0] * outer, p[1] + l[1] * outer, p[2] + 0.31))
            nm = name if lod == "full" else name + "_" + lod
            mesh_from(nm, verts, faces, MAT["metal"])
            counts[lod] += 1
        furniture.append({"type": "guard", "s": round(s0, 1),
                          "lateral": round(outer, 2), "node": name})
    print("GUARD runs:", counts)

def poles():
    count = 0
    for k, i in enumerate(range(0, N, 60)):
        p, l = S[i], LEFT[i]
        side = 6.6 if k % 2 == 0 else -6.6
        px, py = p[0] + l[0] * side, p[1] + l[1] * side
        name = "props_pole_" + pad(i * SPACING)
        ring_prism(name, px, py, p[2], p[2] + 7.2, 0.12, 12, MAT["metal"])
        yaw = math.atan2(-l[1] * math.copysign(1, side), -l[0] * math.copysign(1, side))
        verts, faces = [], []
        add_box_verts(verts, faces, (1.8, 0.12, 0.12), (px, py, p[2] + 7.0), -yaw)
        add_box_verts(verts, faces, (0.7, 0.25, 0.18),
                      (px - l[0] * side / abs(side) * 1.4, py - l[1] * side / abs(side) * 1.4, p[2] + 6.8))
        mesh_from(name + "_head", verts, faces, MAT["metal"])
        # lod1: coarse prism, lod2: single column box
        ring_prism(name + "_lod1", px, py, p[2], p[2] + 7.2, 0.14, 6, MAT["metal"])
        lv2, lf2 = [], []
        add_box_verts(lv2, lf2, (0.4, 0.4, 7.2), (px, py, p[2] + 3.6))
        mesh_from(name + "_lod2", lv2, lf2, MAT["metal"])
        furniture.append({"type": "pole", "s": round(i * SPACING, 1),
                          "lateral": round(side, 2), "node": name})
        count += 1
    print("POLES:", count)

def signs():
    peaks = []
    for i in range(N):
        c = curvature(i)
        if c > 0.0065:
            if peaks and i - peaks[-1][0] < 60:
                if c > peaks[-1][1]:
                    peaks[-1] = (i, c)
            else:
                peaks.append((i, c))
    peaks.sort(key=lambda t: -t[1])
    picked = []
    for i, c in peaks:
        if all(abs(i - j) > 60 for j in picked):
            picked.append(i)
        if len(picked) == 4:
            break
    picked.sort()
    for i in picked:
        c = cross_z(TAN[(i - 1) % N], TAN[(i + 1) % N])
        outer = -7.8 if c > 0 else 7.8
        p, l = S[i], LEFT[i]
        px, py = p[0] + l[0] * outer, p[1] + l[1] * outer
        yaw = math.atan2(TAN[i][1], TAN[i][0])
        name = "props_sign_chevron_" + pad(i * SPACING)
        verts, faces = [], []
        add_box_verts(verts, faces, (0.12, 0.12, 2.2), (px, py, p[2] + 1.1))
        add_box_verts(verts, faces, (1.9, 2.2, 0.08), (px, py, p[2] + 2.6), yaw + math.pi / 2)
        mesh_from(name, verts, faces, MAT["white"])
        furniture.append({"type": "sign_chevron", "s": round(i * SPACING, 1),
                          "lateral": round(outer, 2), "node": name})
    print("SIGNS:", len(picked))

def gantry():
    p, l = S[0], LEFT[0]
    yaw = math.atan2(TAN[0][1], TAN[0][0])
    verts, faces = [], []
    for side in (-6.8, 6.8):
        add_box_verts(verts, faces, (0.5, 0.5, 6.8),
                      (p[0] + l[0] * side, p[1] + l[1] * side, p[2] + 3.4), yaw)
    add_box_verts(verts, faces, (14.4, 0.45, 0.5), (p[0], p[1], p[2] + 6.9), yaw)
    add_box_verts(verts, faces, (8.0, 0.15, 1.7), (p[0], p[1] - 0.4, p[2] + 5.7), yaw)
    mesh_from("props_gantry_start", verts, faces, MAT["metal"])
    furniture.append({"type": "gantry", "s": 0.0, "lateral": 0.0,
                      "node": "props_gantry_start"})

def rocks():
    for r in range(14):
        i = random.randrange(0, N)
        p, l = S[i], LEFT[i]
        side = random.choice((-1, 1))
        lat = side * random.uniform(14.0, 38.0)
        if p[0] + l[0] * lat > 700:
            continue
        try:
            bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=1.0,
                                                  location=(0, 0, 0))
            ob = bpy.context.selected_objects[0]
        except Exception:
            continue
        me = ob.data
        sc = random.uniform(1.2, 3.4)
        for v in me.vertices:
            v.co.x += random.uniform(-0.22, 0.22)
            v.co.y += random.uniform(-0.22, 0.22)
            v.co.z += random.uniform(-0.18, 0.30)
        ob.name = "coastal_rock_" + f"{r:02d}"
        me.name = ob.name
        ob.location = (p[0] + l[0] * lat, p[1] + l[1] * lat,
                       p[2] - 1.2 + random.uniform(0, 0.6))
        ob.scale = (sc * random.uniform(0.8, 1.2), sc, sc * random.uniform(0.6, 0.9))
        me.materials.append(MAT["terrain"])
        furniture.append({"type": "rock", "s": round(i * SPACING, 1),
                          "lateral": round(lat, 2), "node": ob.name})
    print("ROCKS placed:", sum(1 for f in furniture if f["type"] == "rock"))

guard_runs()
poles()
signs()
gantry()
rocks()

# ---------------- world + sun ----------------
world = bpy.data.worlds.new("sky")
world.use_nodes = True
nt = world.node_tree
bg = nt.nodes.get("Background")
sky = nt.nodes.new("ShaderNodeTexSky")
try:
    sky.sky_type = "NISHITA"
    sky.sun_elevation = radians(35)
    sky.sun_rotation = radians(90)
    sky.sun_intensity = 1.0
    nt.links.new(sky.outputs[0], bg.inputs[0])
except Exception as exc:
    print("SKY_FALLBACK:", exc)
bg.inputs[1].default_value = 1.0
scene.world = world
sun_data = bpy.data.lights.new("sun", type="SUN")
sun_data.energy = 4.0
sun = bpy.data.objects.new("sun", sun_data)
scene.collection.objects.link(sun)
sun.rotation_euler = (radians(55), 0.0, radians(90))  # sun in the east over the ocean

# ---------------- exports ----------------
set_path = os.path.join(ASSETS, "set.blend")
bpy.ops.wm.save_as_mainfile(filepath=set_path, compress=True)
print("BLEND_OK", set_path)

glb_path = os.path.join(ASSETS, "tracks.glb")
try:
    bpy.ops.export_scene.gltf(filepath=glb_path, export_format="GLB", export_apply=False)
    print("GLB_OK", glb_path)
except Exception as exc:
    print("GLB_FAILED:", exc)

# tracks_data.json — glTF axis mapping: (x, z, -y)
def to_gltf_axes(p):
    return [round(p[0], 3), round(p[2], 3), round(-p[1], 3)]
data = {"tracks": [{
    "id": "coastal", "name": "Coastal Circuit", "closed": True,
    "centerline": [to_gltf_axes(p) for p in S],
    "roadWidth": 10.0,
    "lanes": [-3.6, -1.2, 1.2, 3.6],
    "furniture": furniture,
    "junctions": [],
}]}
json_path = os.path.join(ASSETS, "tracks_data.json")
with open(json_path, "w", encoding="utf-8") as fh:
    json.dump(data, fh)
print("JSON_OK", json_path, "furniture:", len(furniture))

# ---------------- env_coast.jpg (early panorama, Cycles) ----------------
try:
    scene.render.engine = "CYCLES"
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for dev in ("OPTIX", "CUDA"):
            try:
                prefs.compute_device_type = dev
                prefs.get_devices()
                scene.cycles.device = "GPU"
                break
            except Exception:
                continue
    except Exception:
        scene.cycles.device = "CPU"
    scene.cycles.samples = 64
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 2048
    scene.render.resolution_y = 1024
    scene.render.image_settings.file_format = "JPEG"
    scene.render.image_settings.quality = 85
    cam_data = bpy.data.cameras.new("pano")
    cam_data.type = "PANO"
    try:
        cam_data.panorama_type = "EQUIRECTANGULAR"
    except Exception:
        pass
    cam = bpy.data.objects.new("pano", cam_data)
    scene.collection.objects.link(cam)
    loc = (S[0][0], S[0][1], S[0][2] + 3.0)
    tgt = (loc[0] + 1000, loc[1], loc[2] - 15)
    cam.location = loc
    d = (tgt[0] - loc[0], tgt[1] - loc[1], tgt[2] - loc[2])
    dl = math.sqrt(sum(c * c for c in d))
    d = tuple(c / dl for c in d)
    yaw = math.atan2(d[1], d[0]) - math.pi / 2
    pitch = math.pi / 2 + math.asin(max(-1, min(1, d[2])))
    cam.rotation_euler = (pitch, 0.0, yaw)
    scene.camera = cam
    scene.render.filepath = os.path.join(ASSETS, "env_coast.jpg")
    bpy.ops.render.render(write_still=True)
    print("PANO_OK", scene.render.filepath)
except Exception as exc:
    print("PANO_SKIPPED:", exc)

# ---------------- evidence shots (EEVEE) ----------------
def eevee():
    for eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "BLENDER_WORKBENCH"):
        try:
            scene.render.engine = eng
            return True
        except Exception:
            continue
    return False

try:
    if eevee():
        try:
            scene.eevee.taa_render_samples = 16
        except Exception:
            pass
        scene.render.resolution_x = 1280
        scene.render.resolution_y = 720
        scene.render.image_settings.file_format = "PNG"

        top_data = bpy.data.cameras.new("top")
        top_data.type = "ORTHO"
        top_data.ortho_scale = 1800
        top = bpy.data.objects.new("top", top_data)
        scene.collection.objects.link(top)
        top.location = (80, 40, 900)
        top.rotation_euler = (0.0, 0.0, 0.0)
        scene.camera = top
        scene.render.filepath = os.path.join(SHOTS, "track_top.png")
        bpy.ops.render.render(write_still=True)
        print("SHOT_OK", scene.render.filepath)

        start_data = bpy.data.cameras.new("startcam")
        start_data.lens = 40
        startcam = bpy.data.objects.new("startcam", start_data)
        scene.collection.objects.link(startcam)
        from mathutils import Vector
        loc = Vector((560, -760, 10))
        tgt = Vector((640, -200, 26))
        startcam.location = loc
        startcam.rotation_euler = (tgt - loc).to_track_quat("-Z", "Y").to_euler()
        scene.camera = startcam
        scene.render.filepath = os.path.join(SHOTS, "track_start.png")
        bpy.ops.render.render(write_still=True)
        print("SHOT_OK", scene.render.filepath)
except Exception as exc:
    print("SHOTS_SKIPPED:", exc)

print("BUILD_DONE track_length_m:", round(TRACK_LEN, 1), "samples:", N)