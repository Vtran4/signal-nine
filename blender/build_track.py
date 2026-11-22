# Signal Nine — track set generator (build_track.py)
# Headless: blender -b -P blender/build_track.py
# Track 1: coastal circuit (closed loop, 3.7 km) — verified layout preserved.
# Track 2: downtown sprint (point-to-point, ~3.1 km) + 4 crash junctions
#          {s, lateral, arm} + overpass deck + procedural city blocks.
# Emits: assets/set.blend, assets/tracks.glb, assets/tracks_data.json,
#        assets/env_coast.jpg (early pano), blender/shots/*.
# Contract: centerline samples every 2 m (closed: no duplicated wrap sample;
# open: exact ends included), furniture {type, s, lateral, node} with node =
# exact glb node name, GLOBALLY unique across both tracks (downtown furniture
# uses props_dt_* stems). JSON/glb world space = glTF axes (x, z_blender, -y).
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
    "terrain": pbr("terrain", (0.47, 0.40, 0.25)),
    "ocean":  pbr("ocean",  (0.05, 0.22, 0.45), 0.0, 0.25),
    "metal":  pbr("metal",  (0.65, 0.67, 0.70), 0.6, 0.45),
    "white":  pbr("white",  (0.85, 0.85, 0.82)),
    "sign_red": pbr("sign_red", (0.75, 0.10, 0.08), 0.0, 0.5),
    "signal_red": pbr("signal_red", (0.80, 0.08, 0.06), 0.0, 0.4),
    "signal_amber": pbr("signal_amber", (0.85, 0.55, 0.05), 0.0, 0.4),
    "signal_green": pbr("signal_green", (0.10, 0.60, 0.15), 0.0, 0.4),
    "concrete": pbr("concrete", (0.46, 0.46, 0.45)),
    "building": pbr("building", (0.42, 0.40, 0.39)),
    "dark":   pbr("dark",   (0.10, 0.10, 0.12)),
    "paint_white": pbr("paint_white", (0.82, 0.82, 0.80), 0.0, 0.6),
    "paint_yellow": pbr("paint_yellow", (0.82, 0.62, 0.10), 0.0, 0.6),
    "fascia": pbr("fascia", (0.30, 0.30, 0.33)),
}

BUILDING_TONES = [(0.50, 0.48, 0.46), (0.42, 0.40, 0.44), (0.55, 0.48, 0.38),
                  (0.36, 0.38, 0.42), (0.58, 0.52, 0.50), (0.30, 0.31, 0.34)]

def grade_asphalt(mat, wear_us):
    """In-bake texture grading: noise-mottled cool-grey asphalt + UV-driven
    wheel-path wear strips at the lane centers + fine bump grain (the LIGHT
    bake picks the grain up as baked relief). Zero engine changes."""
    nt = mat.node_tree
    b = nt.nodes.get("Principled BSDF")
    tex = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 0.5
    noise.inputs["Detail"].default_value = 6.0
    ramp_n = nt.nodes.new("ShaderNodeValToRGB")
    ramp_n.color_ramp.elements[0].color = (0.24, 0.25, 0.28, 1.0)
    ramp_n.color_ramp.elements[1].color = (0.40, 0.41, 0.44, 1.0)
    nt.links.new(tex.outputs["Object"], noise.inputs["Vector"])
    nt.links.new(noise.outputs["Fac"], ramp_n.inputs["Fac"])
    mult = nt.nodes.new("ShaderNodeMixRGB")
    mult.blend_type = "MULTIPLY"
    mult.inputs["Fac"].default_value = 1.0
    mult.inputs["Color1"].default_value = (0.33, 0.34, 0.37, 1.0)
    if wear_us:
        wear = nt.nodes.new("ShaderNodeValToRGB")
        wr = wear.color_ramp
        wr.elements[0].position = 0.0
        wr.elements[0].color = (1.0, 1.0, 1.0, 1.0)
        wr.elements[1].position = 1.0
        wr.elements[1].color = (1.0, 1.0, 1.0, 1.0)
        for u in wear_us:
            e1 = wr.elements.new(max(0.001, u - 0.05))
            e1.color = (0.60, 0.61, 0.65, 1.0)
            e2 = wr.elements.new(u)
            e2.color = (0.52, 0.53, 0.57, 1.0)
            e3 = wr.elements.new(min(0.999, u + 0.05))
            e3.color = (0.60, 0.61, 0.65, 1.0)
        sep2 = nt.nodes.new("ShaderNodeSeparateXYZ")
        nt.links.new(tex.outputs["UV"], sep2.inputs[0])
        nt.links.new(sep2.outputs["X"], wear.inputs["Fac"])
        nt.links.new(ramp_n.outputs["Color"], mult.inputs["Color1"])
        nt.links.new(wear.outputs["Color"], mult.inputs["Color2"])
    else:
        nt.links.new(ramp_n.outputs["Color"], mult.inputs["Color1"])
    nt.links.new(mult.outputs["Color"], b.inputs["Base Color"])
    noise2 = nt.nodes.new("ShaderNodeTexNoise")
    noise2.inputs["Scale"].default_value = 60.0
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.18
    nt.links.new(tex.outputs["Object"], noise2.inputs["Vector"])
    nt.links.new(noise2.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])

def grade_surface(mat, mottle_scale=14.0, dark=(0.85, 0.85, 0.85)):
    """Noise mottle multiplier for terrain-style surfaces (object-space)."""
    nt = mat.node_tree
    b = nt.nodes.get("Principled BSDF")
    tex = nt.nodes.new("ShaderNodeTexCoord")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = mottle_scale
    noise.inputs["Detail"].default_value = 5.0
    nt.links.new(tex.outputs["Object"], noise.inputs["Vector"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (*dark, 1.0)
    ramp.color_ramp.elements[1].color = (1.0, 1.0, 1.0, 1.0)
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    mult = nt.nodes.new("ShaderNodeMixRGB")
    mult.blend_type = "MULTIPLY"
    mult.inputs["Fac"].default_value = 1.0
    mult.inputs["Color1"].default_value = tuple(b.inputs["Base Color"].default_value)[:3] + (1.0,)
    nt.links.new(ramp.outputs["Color"], mult.inputs["Color2"])
    nt.links.new(mult.outputs["Color"], b.inputs["Base Color"])

grade_asphalt(MAT["road"], [0.083, 0.25, 0.417, 0.583, 0.75, 0.917])
grade_surface(MAT["terrain"], mottle_scale=14.0, dark=(0.80, 0.78, 0.74))
grade_surface(MAT["concrete"], mottle_scale=10.0, dark=(0.88, 0.88, 0.86))

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

def pad(s):
    return f"{int(round(s)):04d}"

# ---------------- splines ----------------
def catmull(p0, p1, p2, p3, t):
    t2, t3 = t * t, t * t * t
    return tuple(0.5 * ((2 * p1[i]) + (-p0[i] + p2[i]) * t
                        + (2 * p0[i] - 5 * p1[i] + 4 * p2[i] - p3[i]) * t2
                        + (-p0[i] + 3 * p1[i] - 3 * p2[i] + p3[i]) * t3)
                 for i in range(3))

def dense_closed(CTRL, steps=160):
    dense = []
    n = len(CTRL)
    for i in range(n):
        p0, p1 = CTRL[(i - 1) % n], CTRL[i]
        p2, p3 = CTRL[(i + 1) % n], CTRL[(i + 2) % n]
        for j in range(steps):
            dense.append(catmull(p0, p1, p2, p3, j / steps))
    return dense

def dense_open(CTRL, steps=160):
    dense = []
    n = len(CTRL)
    for i in range(n - 1):
        p0 = CTRL[max(i - 1, 0)]
        p1 = CTRL[i]
        p2 = CTRL[i + 1]
        p3 = CTRL[min(i + 2, n - 1)]
        for j in range(steps):
            dense.append(catmull(p0, p1, p2, p3, j / steps))
    dense.append(tuple(CTRL[-1]))
    return dense

SPACING = 2.0

def resample_closed(points, spacing):
    """Uniform arc-length samples over a CLOSED loop: wrap segment == step."""
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

def resample_open(points, spacing):
    """Uniform samples over an OPEN polyline; first/last are the exact ends."""
    total = sum(dist3(points[i], points[i + 1]) for i in range(len(points) - 1))
    n = max(2, int(round(total / spacing)))
    step = total / n
    out = []
    idx, acc = 0, 0.0
    for k in range(n + 1):
        target = min(total, k * step)
        while idx < len(points) - 2:
            seg = dist3(points[idx], points[idx + 1])
            if acc + seg >= target:
                break
            acc += seg
            idx += 1
        a = points[idx]
        b = points[idx + 1]
        seg = dist3(a, b) or 1e-9
        f = max(0.0, min(1.0, (target - acc) / seg))
        out.append(tuple(a[c] + (b[c] - a[c]) * f for c in range(3)))
    out[-1] = tuple(points[-1])
    return out

def tangents_lefts(samples, closed):
    n = len(samples)
    tans, lefts = [], []
    for i in range(n):
        if closed:
            a = samples[(i - 1) % n]
            b = samples[(i + 1) % n]
        else:
            a = samples[max(i - 1, 0)]
            b = samples[min(i + 1, n - 1)]
        t = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        L = math.sqrt(t[0] ** 2 + t[1] ** 2 + t[2] ** 2) or 1.0
        t = (t[0] / L, t[1] / L, t[2] / L)
        tans.append(t)
        lefts.append((-t[1], t[0], 0.0))  # up x tangent (left-positive)
    return tans, lefts

def build_road_mesh(name, S, LEFT, closed):
    """Road ribbon. Closed loops duplicate the seam ring so v stays continuous
    across the wrap (and the wrap quad actually exists — no start-line gap)."""
    n = len(S)
    verts, uvs = [], []
    for i, p in enumerate(S):
        l = LEFT[i]
        verts.append((p[0] + l[0] * HW, p[1] + l[1] * HW, p[2]))
        uvs.append((0.0, i * SPACING / 20.0))
    for i, p in enumerate(S):
        l = LEFT[i]
        verts.append((p[0] - l[0] * HW, p[1] - l[1] * HW, p[2]))
        uvs.append((1.0, i * SPACING / 20.0))
    if closed:
        l0 = LEFT[0]
        verts.append((S[0][0] + l0[0] * HW, S[0][1] + l0[1] * HW, S[0][2]))
        uvs.append((0.0, n * SPACING / 20.0))
        verts.append((S[0][0] - l0[0] * HW, S[0][1] - l0[1] * HW, S[0][2]))
        uvs.append((1.0, n * SPACING / 20.0))
    faces = []
    for i in range(n if closed else n - 1):
        j = (i + 1) % n if closed else i + 1
        if closed and j == 0:
            jL, jR = 2 * n, 2 * n + 1  # duplicated seam ring
        else:
            jL, jR = j, n + j
        faces.append((i, n + i, jR, jL))
    ob = mesh_from(name, verts, faces, MAT["road"])
    uv = ob.data.uv_layers.new(name="UVMap")
    for poly in ob.data.polygons:
        for li in poly.loop_indices:
            vi = ob.data.loops[li].vertex_index
            uv.data[li].uv = uvs[vi]
    return ob

def build_road_paint(name_w, name_y, S, LEFT, closed, skip_fn):
    """Lane paint as geometry 2 cm above the ribbon: solid edge lines + dashed
    lane splits (white mesh) + double-yellow center (yellow mesh). Breaks at
    junction zones; closed loops wrap continuously (seam-safe dashes too)."""
    n = len(S)
    def allowed(i):
        return skip_fn is None or not skip_fn((i % n) * SPACING)
    def all_runs(mask):
        runs, cur = [], []
        for i in range(n):
            if mask(i):
                cur.append(i)
            elif cur:
                runs.append(cur)
                cur = []
        if cur:
            runs.append(cur)
        if closed and len(runs) > 1 and runs[0][0] == 0 and runs[-1][-1] == n - 1:
            head = runs.pop(0)
            runs[-1] = runs[-1] + [i - n for i in head]
        return runs
    def emit(verts, faces, idxs, lat, width):
        base = len(verts)
        for i in idxs:
            p, l = S[i % n], LEFT[i % n]
            for off in (lat - width / 2, lat + width / 2):
                verts.append((p[0] + l[0] * off, p[1] + l[1] * off, p[2] + 0.02))
        for k in range(len(idxs) - 1):
            a = base + 2 * k
            b = base + 2 * k + 2
            faces.append((a, a + 1, b + 1, b))
    def solid(verts, faces, lat, width):
        for run in all_runs(lambda i: allowed(i)):
            idxs = run[::2]
            if closed and run[0] <= 0 and run[-1] >= n - 1 and idxs[-1] != n:
                idxs = idxs + [n]
            emit(verts, faces, idxs, lat, width)
    vw, fw = [], []
    solid(vw, fw, HW - 0.3, 0.14)
    solid(vw, fw, -(HW - 0.3), 0.14)
    for run in all_runs(lambda i: allowed(i) and (i % 9) < 2):
        for lat in (-5.0, -2.5, 2.5, 5.0):
            emit(vw, fw, run, lat, 0.14)
    mesh_from(name_w, vw, fw, MAT["paint_white"])
    vy, fy = [], []
    solid(vy, fy, 0.16, 0.10)
    solid(vy, fy, -0.16, 0.10)
    mesh_from(name_y, vy, fy, MAT["paint_yellow"])

# =====================================================================
# TRACK 1 — COASTAL CIRCUIT (verified layout; call order preserves RNG)
# =====================================================================
CTRL_COASTAL = [(620, -420, 26), (640, -140, 28), (660, 140, 30), (620, 380, 32),
                (480, 560, 36), (260, 620, 42), (0, 600, 46), (-240, 480, 50),
                (-420, 300, 52), (-500, 80, 48), (-420, -100, 42), (-300, -260, 38),
                (-140, -380, 34), (60, -460, 28), (280, -500, 24), (480, -480, 24)]

RW = 15.0  # roadWidth 15 (B3-grade: 6 lanes @ 2.5 m) — all lateral offsets derive from this
HW = RW / 2
S = resample_closed(dense_closed(CTRL_COASTAL), SPACING)
N = len(S)
TRACK_LEN_COASTAL = N * SPACING
TAN, LEFT = tangents_lefts(S, True)
print("TRACK coastal samples:", N, "length_m:", round(TRACK_LEN_COASTAL, 1))

def curvature(i):
    a, b = TAN[(i - 2) % N], TAN[(i + 2) % N]
    dot = max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]))
    return math.acos(dot) / (4 * SPACING)

def cross_z(a, b):
    return a[0] * b[1] - a[1] * b[0]

build_road_mesh("coastal_road", S, LEFT, closed=True)

TX0, TX1, TY0, TY1 = -700.0, 800.0, -700.0, 860.0
CELL = 15.0
NX = int((TX1 - TX0) / CELL)
NY = int((TY1 - TY0) / CELL)
road_coarse = S[::8]

def terrain_h(x, y):
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
    near = 1.0 - smoothstep(6.0, 22.0, d)
    if d < 22.0:
        h = h * (1 - near) + (bz - 0.6) * near
    h -= 55.0 * smoothstep(0.0, 1.0, (x - 540.0) / 220.0) * (1.0 - near)
    h -= 18.0 * smoothstep(0.0, 1.0, (-y - 560.0) / 240.0)
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

build_terrain()
mesh_from("coastal_ocean",
          [(700, -1800, -0.25), (3200, -1800, -0.25),
           (3200, 1800, -0.25), (700, 1800, -0.25)],
          [(0, 1, 2, 3)], MAT["ocean"])

build_road_paint("coastal_paint_w", "coastal_paint_y", S, LEFT, True, None)

furniture = []

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
            runs.append((z, -(HW + 1.0) if cz > 0 else HW + 1.0))
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
        runs.append((z, -(HW + 1.0)))
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
                step = post_step * 2
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
        side = (HW + 1.6) if k % 2 == 0 else -(HW + 1.6)
        px, py = p[0] + l[0] * side, p[1] + l[1] * side
        name = "props_pole_" + pad(i * SPACING)
        ring_prism(name, px, py, p[2], p[2] + 7.2, 0.12, 12, MAT["metal"])
        yaw = math.atan2(-l[1] * math.copysign(1, side), -l[0] * math.copysign(1, side))
        verts, faces = [], []
        add_box_verts(verts, faces, (1.8, 0.12, 0.12), (px, py, p[2] + 7.0), -yaw)
        add_box_verts(verts, faces, (0.7, 0.25, 0.18),
                      (px - l[0] * side / abs(side) * 1.4, py - l[1] * side / abs(side) * 1.4, p[2] + 6.8))
        mesh_from(name + "_head", verts, faces, MAT["metal"])
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
        outer = -(HW + 2.8) if c > 0 else HW + 2.8
        p, l = S[i], LEFT[i]
        px, py = p[0] + l[0] * outer, p[1] + l[1] * outer
        yaw = math.atan2(TAN[i][1], TAN[i][0])
        name = "props_sign_chevron_" + pad(i * SPACING)
        verts, faces = [], []
        add_box_verts(verts, faces, (0.12, 0.12, 2.2), (px, py, p[2] + 1.1))
        add_box_verts(verts, faces, (1.9, 0.08, 2.2), (px, py, p[2] + 1.35), yaw + math.pi / 2)
        mesh_from(name, verts, faces, MAT["white"])
        sv, sf = [], []
        wx, wy = -math.sin(yaw), math.cos(yaw)
        fx, fy = -math.cos(yaw), -math.sin(yaw)
        for off in (-0.62, 0.0, 0.62):
            add_box_verts(sv, sf, (0.26, 0.10, 1.70),
                          (px + wx * off + fx * 0.05, py + wy * off + fy * 0.05, p[2] + 1.35),
                          yaw + math.pi / 2)
        mesh_from(name + "_stripes", sv, sf, MAT["sign_red"])
        furniture.append({"type": "sign_chevron", "s": round(i * SPACING, 1),
                          "lateral": round(outer, 2), "node": name})
    print("SIGNS:", len(picked))

def gantry():
    p, l = S[0], LEFT[0]
    yaw = math.atan2(TAN[0][1], TAN[0][0])
    verts, faces = [], []
    for side in (-(HW + 1.8), HW + 1.8):
        add_box_verts(verts, faces, (0.5, 0.5, 6.8),
                      (p[0] + l[0] * side, p[1] + l[1] * side, p[2] + 3.4), yaw)
    add_box_verts(verts, faces, (2 * HW + 4.4, 0.45, 0.5), (p[0], p[1], p[2] + 6.9), yaw)
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
coastal_furniture = furniture
furniture = []

# =====================================================================
# TRACK 2 — DOWNTOWN SPRINT (point-to-point) + 4 crash junctions
# =====================================================================
CTRL_DT = [(-40, 0, 0.2), (300, 0, 0.2), (520, 60, 0.2), (640, 220, 0.2),
           (600, 420, 0.2), (460, 540, 0.3), (240, 580, 0.3), (60, 540, 0.4),
           (-60, 440, 6.0), (-140, 300, 9.5), (-160, 140, 9.5), (-140, -20, 9.0),
           (-60, -140, 4.5), (80, -200, 0.2), (320, -240, 0.2), (560, -260, 0.2)]

S2 = resample_open(dense_open(CTRL_DT), SPACING)
N2 = len(S2)
TRACK_LEN_DT = (N2 - 1) * SPACING
T2, L2 = tangents_lefts(S2, False)
print("TRACK downtown samples:", N2, "length_m:", round(TRACK_LEN_DT, 1))

build_road_mesh("downtown_road", S2, L2, closed=False)

furniture_dt = []
junctions = []
JUNCTIONS = [(0.10, 44.0), (0.30, 52.0), (0.47, 56.0), (0.86, 64.0)]
JZ = [(int(round(f * (N2 - 1))), arm, int(round(f * (N2 - 1))) * SPACING)
      for f, arm in JUNCTIONS]

def in_junction_zone(s_val, margin):
    for si, arm, sj in JZ:
        if abs(s_val - sj) < arm / 2 + margin:
            return True
    return False

def on_deck(i):
    return S2[i][2] > 5.5

mesh_from("downtown_ground",
          [(-800, -800, 0.0), (1200, -800, 0.0), (1200, 1000, 0.0), (-800, 1000, 0.0)],
          [(0, 1, 2, 3)], MAT["concrete"])

# underpass: the start avenue visually continues west beneath the overpass deck
mesh_from("downtown_underpass",
          [(-280, -5, 0.02), (-40, -5, 0.02), (-40, 5, 0.02), (-280, 5, 0.02)],
          [(0, 1, 2, 3)], MAT["road"])

def build_junctions():
    for si, arm, sj in JZ:
        p, l, t = S2[si], L2[si], T2[si]
        yaw = math.atan2(t[1], t[0])
        verts, faces = [], []
        add_box_verts(verts, faces, (RW, arm, 0.05), (p[0], p[1], p[2] + 0.03), yaw)
        mesh_from("downtown_cross_" + pad(sj), verts, faces, MAT["road"])
        junctions.append({"s": round(sj, 1), "lateral": 0.0, "arm": round(arm, 1)})
        for band in (si - int((HW + 1.5) / SPACING), si + int((HW + 1.5) / SPACING)):
            if band < 0 or band > N2 - 1:
                continue
            cv, cf = [], []
            for k in range(5):
                bi = max(0, min(N2 - 1, band + (k - 2)))
                bp = S2[bi]
                add_box_verts(cv, cf, (0.6, RW, 0.02), (bp[0], bp[1], bp[2] + 0.02), yaw)
            mesh_from("props_dt_crosswalk_" + pad(band * SPACING), cv, cf, MAT["white"])
        for corner in (1, -1):
            cx = p[0] + (l[0] * (HW + 2.5) + t[0] * (HW + 2.5)) * corner
            cy = p[1] + (l[1] * (HW + 2.5) + t[1] * (HW + 2.5)) * corner
            name = "props_dt_signal_" + pad(sj) + ("a" if corner > 0 else "b")
            dirx, diry = -t[0] * corner, -t[1] * corner
            ayaw = math.atan2(diry, dirx)
            ring_prism(name, cx, cy, p[2], p[2] + 5.5, 0.10, 8, MAT["metal"])
            sv, sf = [], []
            add_box_verts(sv, sf, (5.0, 0.12, 0.12),
                          (cx + dirx * 2.5, cy + diry * 2.5, p[2] + 5.3), ayaw)
            add_box_verts(sv, sf, (0.35, 0.25, 0.85),
                          (cx + dirx * 5.0, cy + diry * 5.0, p[2] + 4.9), ayaw)
            mesh_from(name + "_arm", sv, sf, MAT["dark"])
            hx, hy = cx + dirx * 5.0, cy + diry * 5.0
            for li, (lz, lmat) in enumerate(((0.24, "signal_red"), (0.0, "signal_amber"),
                                             (-0.24, "signal_green"))):
                lv2, lf2 = [], []
                add_box_verts(lv2, lf2, (0.05, 0.20, 0.16),
                              (hx + dirx * 0.14, hy + diry * 0.14, p[2] + 4.9 + lz), ayaw)
                mesh_from(name + "_lens_" + "rgb"[li], lv2, lf2, MAT[lmat])
            furniture_dt.append({"type": "signal", "s": round(sj, 1),
                                 "lateral": round((HW + 2.5) * corner, 2), "node": name})
    print("JUNCTIONS:", len(junctions), [j["arm"] for j in junctions])

build_junctions()
build_road_paint("downtown_paint_w", "downtown_paint_y", S2, L2, False,
                 lambda s: in_junction_zone(s, 4.0))

def build_deck():
    spans = []
    cur = None
    for i in range(N2):
        if on_deck(i):
            if cur is None:
                cur = [i, i]
            else:
                cur[1] = i
        else:
            if cur:
                spans.append(cur)
            cur = None
    if cur:
        spans.append(cur)
    spans = [sp for sp in spans if sp[1] - sp[0] > 6]
    if not spans:
        print("DECK: none")
        return
    verts, faces = [], []
    for a, b in spans:
        for side in (-1, 1):
            base = len(verts)
            for i in range(a, b + 1):
                p, l = S2[i], L2[i]
                bx, by = p[0] + l[0] * (HW + 0.35) * side, p[1] + l[1] * (HW + 0.35) * side
                verts.extend([(bx, by, p[2] + 0.45), (bx, by, p[2] + 0.95)])
            m = b - a + 1
            for k in range(m - 1):
                o = base + 2 * k
                faces.append((o, o + 2, o + 3, o + 1))
    mesh_from("downtown_deckbar", verts, faces, MAT["concrete"])
    fv, ff = [], []
    for a, b in spans:
        for side in (-1, 1):
            base = len(fv)
            for i in range(a, b + 1):
                p, l = S2[i], L2[i]
                bx, by = p[0] + l[0] * (HW + 0.35) * side, p[1] + l[1] * (HW + 0.35) * side
                fv.extend([(bx, by, p[2] - 0.05), (bx, by, p[2] - 1.35)])
            m = b - a + 1
            for k in range(m - 1):
                o = base + 2 * k
                ff.append((o, o + 2, o + 3, o + 1))
        base = len(fv)
        for i in range(a, b + 1):
            p, l = S2[i], L2[i]
            fv.extend([(p[0] + l[0] * (HW + 0.35), p[1] + l[1] * (HW + 0.35), p[2] - 1.35),
                       (p[0] - l[0] * (HW + 0.35), p[1] - l[1] * (HW + 0.35), p[2] - 1.35)])
        m = b - a + 1
        for k in range(m - 1):
            o = base + 2 * k
            ff.append((o, o + 1, o + 3, o + 2))
    mesh_from("downtown_fascia", fv, ff, MAT["fascia"])
    count = 0
    for a, b in spans:
        for i in range(a + 4, b - 3, 15):
            p, l = S2[i], L2[i]
            verts, faces = [], []
            for side in (-1, 1):
                add_box_verts(verts, faces, (1.3, 1.3, p[2]),
                              (p[0] + l[0] * 8.0 * side, p[1] + l[1] * 8.0 * side, p[2] / 2))
            mesh_from("downtown_pylon_" + pad(i * SPACING), verts, faces, MAT["concrete"])
            count += 1
    print("DECK spans:", spans, "pylons:", count)

build_deck()

def build_blocks():
    placed = []
    chunk = {"verts": [], "faces": [], "n": 0}
    def flush():
        if chunk["faces"]:
            tone = random.choice(BUILDING_TONES)
            mesh_from("downtown_block_" + f"{chunk['n']:02d}", chunk["verts"],
                      chunk["faces"], pbr("building_t" + f"{chunk['n']:02d}", tone))
            chunk["n"] += 1
            chunk["verts"] = []
            chunk["faces"] = []
    for i in range(6, N2 - 6, 16):
        p, l, t = S2[i], L2[i], T2[i]
        for side in (-1, 1):
            lat = side * (HW + 9.0 + random.uniform(0.0, 14.0))
            bx, by = p[0] + l[0] * lat, p[1] + l[1] * lat
            s_val = i * SPACING
            if in_junction_zone(s_val, 14.0):
                continue
            if -290.0 < bx < -25.0 and abs(by) < 14.0:
                continue  # underpass corridor
            if on_deck(i) and abs(lat) < 26.0:
                continue  # keep the deck flight corridor clear
            if any(dist3((bx, by, 0.0), q) < 20.0 for q in placed):
                continue
            placed.append((bx, by, 0.0))
            w = random.uniform(14.0, 26.0)
            dpth = random.uniform(14.0, 26.0)
            hgt = random.uniform(8.0, 34.0)
            yaw = math.atan2(t[1], t[0])
            add_box_verts(chunk["verts"], chunk["faces"], (w, dpth, hgt),
                          (bx, by, hgt / 2), yaw)
            if len(chunk["faces"]) >= 80:
                flush()
    flush()
    print("BLOCKS:", chunk["n"], "buildings:", len(placed))

build_blocks()

def make_pole(name, px, py, pz, dirx, diry):
    ring_prism(name, px, py, pz, pz + 7.2, 0.12, 12, MAT["metal"])
    verts, faces = [], []
    ayaw = math.atan2(diry, dirx)
    add_box_verts(verts, faces, (1.8, 0.12, 0.12),
                  (px + dirx * 0.9, py + diry * 0.9, pz + 7.0), ayaw)
    add_box_verts(verts, faces, (0.7, 0.25, 0.18),
                  (px + dirx * 1.4, py + diry * 1.4, pz + 6.8), ayaw)
    mesh_from(name + "_head", verts, faces, MAT["metal"])
    ring_prism(name + "_lod1", px, py, pz, pz + 7.2, 0.14, 6, MAT["metal"])
    lv2, lf2 = [], []
    add_box_verts(lv2, lf2, (0.4, 0.4, 7.2), (px, py, pz + 3.6))
    mesh_from(name + "_lod2", lv2, lf2, MAT["metal"])

def poles_dt():
    count = 0
    for k, i in enumerate(range(0, N2, 40)):
        if in_junction_zone(i * SPACING, 10.0) or on_deck(i):
            continue
        p, l = S2[i], L2[i]
        side = 6.6 if k % 2 == 0 else -6.6
        px, py = p[0] + l[0] * side, p[1] + l[1] * side
        name = "props_dt_pole_" + pad(i * SPACING)
        make_pole(name, px, py, p[2],
                  -l[0] * (1 if side > 0 else -1), -l[1] * (1 if side > 0 else -1))
        furniture_dt.append({"type": "pole", "s": round(i * SPACING, 1),
                             "lateral": round(side, 2), "node": name})
        count += 1
    print("POLES_DT:", count)

poles_dt()

def gantry_dt():
    p, l, t = S2[0], L2[0], T2[0]
    yaw = math.atan2(t[1], t[0])
    verts, faces = [], []
    for side in (-(HW + 1.8), HW + 1.8):
        add_box_verts(verts, faces, (0.5, 0.5, 6.8),
                      (p[0] + l[0] * side, p[1] + l[1] * side, p[2] + 3.4), yaw)
    add_box_verts(verts, faces, (2 * HW + 4.4, 0.45, 0.5), (p[0], p[1], p[2] + 6.9), yaw)
    add_box_verts(verts, faces, (8.0, 0.15, 1.7), (p[0], p[1] - 0.4, p[2] + 5.7), yaw)
    mesh_from("props_dt_gantry_start", verts, faces, MAT["metal"])
    furniture_dt.append({"type": "gantry", "s": 0.0, "lateral": 0.0,
                         "node": "props_dt_gantry_start"})

gantry_dt()
print("FURNITURE_DT:", len(furniture_dt))

# =====================================================================
# TRACK 3 — CANYON CIRCUIT (closed loop, switchback ladders, rim exposure)
# =====================================================================
CTRL_CN = [(0, -520, 10), (10, -300, 11), (-10, -140, 13), (30, -40, 15),
           (-60, 40, 26), (-160, 100, 40), (-60, 170, 55), (30, 250, 70),
           (-40, 340, 82), (-200, 400, 88), (-380, 380, 90), (-460, 260, 88),
           (-420, 120, 82), (-500, 20, 70), (-420, -60, 56), (-520, -140, 44),
           (-440, -240, 30), (-330, -320, 20), (-180, -420, 12), (-40, -480, 10)]

S3 = resample_closed(dense_closed(CTRL_CN), SPACING)
N3 = len(S3)
TRACK_LEN_CN = N3 * SPACING
T3, L3 = tangents_lefts(S3, True)
print("TRACK canyon samples:", N3, "length_m:", round(TRACK_LEN_CN, 1))

build_road_mesh("canyon_road", S3, L3, closed=True)
build_road_paint("canyon_paint_w", "canyon_paint_y", S3, L3, True, None)

furniture_cn = []
RIM_LO, RIM_HI = 0.37, 0.62  # loop fractions where the OUTER side drops away

def rim_weight(i):
    frac = i / (N3 - 1)
    return (smoothstep(RIM_LO - 0.04, RIM_LO + 0.01, frac)
            * (1.0 - smoothstep(RIM_HI - 0.01, RIM_HI + 0.04, frac)))

def cn_curvature(i):
    a, b = T3[(i - 2) % N3], T3[(i + 2) % N3]
    dot = max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]))
    return math.acos(dot) / (4 * SPACING)

CN_TX0, CN_TX1, CN_TY0, CN_TY1 = -620.0, 140.0, -640.0, 520.0
CN_CELL = 10.0
CN_NX = int((CN_TX1 - CN_TX0) / CN_CELL)
CN_NY = int((CN_TY1 - CN_TY0) / CN_CELL)
cn_coarse = [(i, S3[i]) for i in range(0, N3, 8)]

def cn_terrain_h(x, y):
    """Gorge carve: corridor hugs the road; walls rise 45 m above LOCAL road
    level; on the rim arc the outer (right) side drops into a basin instead."""
    best, bz, gi = 1e9, 0.0, 0
    for ki, p in cn_coarse:
        d2 = (p[0] - x) ** 2 + (p[1] - y) ** 2
        if d2 < best:
            best, bz, gi = d2, p[2], ki
    d = math.sqrt(best)
    noise = (sin(x * 0.0031 + 2.1) * cos(y * 0.0027 + 0.4) * 4.0
             + sin(x * 0.0061) * sin(y * 0.0053) * 2.0)
    if d < 12.0:
        w = 1.0 - smoothstep(6.0, 12.0, d)
        return (bz - 0.6) * w + (bz - 0.6 + noise * 0.25) * (1.0 - w)
    wall_h = bz - 0.6 + 45.0 * smoothstep(12.0, 55.0, d)
    dw = rim_weight(gi)
    if dw > 0.0:
        p, t = S3[gi], T3[gi]
        if cross_z(t, (x - p[0], y - p[1])) < 0.0:  # outer (right) = drop side
            drop_h = bz - 0.6 - 35.0 * smoothstep(12.0, 60.0, d)
            return (wall_h * (1.0 - dw) + drop_h * dw) + noise * 0.4
    return wall_h + noise * 0.4

def build_canyon_terrain():
    verts = []
    for iy in range(CN_NY + 1):
        for ix in range(CN_NX + 1):
            x = CN_TX0 + ix * CN_CELL
            y = CN_TY0 + iy * CN_CELL
            verts.append((x, y, cn_terrain_h(x, y)))
    faces = []
    def v(ix, iy):
        return iy * (CN_NX + 1) + ix
    for iy in range(CN_NY):
        for ix in range(CN_NX):
            faces.append((v(ix, iy), v(ix + 1, iy), v(ix + 1, iy + 1), v(ix, iy + 1)))
    return mesh_from("canyon_terrain", verts, faces, MAT["terrain"])

build_canyon_terrain()

def cn_guard_runs():
    guarded = set()
    runs = []
    zones, cur = [], []
    for i in range(N3):
        if cn_curvature(i) > 0.0045:
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
            cz = sum(cross_z(T3[(i - 1) % N3], T3[(i + 1) % N3]) for i in z)
            runs.append((z, -(HW + 1.0) if cz > 0 else HW + 1.0))
            guarded.update(z)
    rim, allr = [], []
    for i in range(N3):
        if rim_weight(i) > 0.5 and i not in guarded:
            rim.append(i)
        else:
            if len(rim) >= 8:
                allr.append(rim)
            rim = []
    if len(rim) >= 8:
        allr.append(rim)
    for z in allr:
        runs.append((z, -(HW + 1.0)))
    counts = {"full": 0, "lod1": 0, "lod2": 0}
    for z, outer in runs:
        s0 = z[0] * SPACING
        name = "props_cn_guard_" + pad(s0)
        for lod, post_step in (("full", 2), ("lod1", 4), ("lod2", 99)):
            verts, faces = [], []
            idxs = z[::2] if lod != "full" else z
            for i in idxs:
                p, l = S3[i], L3[i]
                bx, by = p[0] + l[0] * outer, p[1] + l[1] * outer
                verts.extend([(bx, by, p[2] + 0.55), (bx, by, p[2] + 0.80)])
            m = len(idxs)
            for k in range(m - 1):
                faces.append((2 * k, 2 * k + 2, 2 * k + 3, 2 * k + 1))
            if lod != "lod2":
                step = post_step * 2
                for gi in range(z[0], z[-1] + 1, step):
                    gi = min(gi, z[-1])
                    p, l = S3[gi], L3[gi]
                    add_box_verts(verts, faces, (0.14, 0.14, 0.62),
                                  (p[0] + l[0] * outer, p[1] + l[1] * outer, p[2] + 0.31))
            nm = name if lod == "full" else name + "_" + lod
            mesh_from(nm, verts, faces, MAT["metal"])
            counts[lod] += 1
        furniture_cn.append({"type": "guard", "s": round(s0, 1),
                             "lateral": round(outer, 2), "node": name})
    print("GUARD_CN runs:", counts)

def cn_signs():
    peaks = []
    for i in range(N3):
        c = cn_curvature(i)
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
        if len(picked) == 6:
            break
    picked.sort()
    for i in picked:
        c = cross_z(T3[(i - 1) % N3], T3[(i + 1) % N3])
        outer = -(HW + 2.8) if c > 0 else HW + 2.8
        p, l = S3[i], L3[i]
        px, py = p[0] + l[0] * outer, p[1] + l[1] * outer
        yaw = math.atan2(T3[i][1], T3[i][0])
        name = "props_cn_sign_chevron_" + pad(i * SPACING)
        verts, faces = [], []
        add_box_verts(verts, faces, (0.12, 0.12, 2.2), (px, py, p[2] + 1.1))
        add_box_verts(verts, faces, (1.9, 0.08, 2.2), (px, py, p[2] + 1.35), yaw + math.pi / 2)
        mesh_from(name, verts, faces, MAT["white"])
        sv, sf = [], []
        wx, wy = -math.sin(yaw), math.cos(yaw)
        fx, fy = -math.cos(yaw), -math.sin(yaw)
        for off in (-0.62, 0.0, 0.62):
            add_box_verts(sv, sf, (0.26, 0.10, 1.70),
                          (px + wx * off + fx * 0.05, py + wy * off + fy * 0.05, p[2] + 1.35),
                          yaw + math.pi / 2)
        mesh_from(name + "_stripes", sv, sf, MAT["sign_red"])
        furniture_cn.append({"type": "sign_chevron", "s": round(i * SPACING, 1),
                             "lateral": round(outer, 2), "node": name})
    print("SIGNS_CN:", len(picked))

def gantry_cn():
    p, l = S3[0], L3[0]
    yaw = math.atan2(T3[0][1], T3[0][0])
    verts, faces = [], []
    for side in (-(HW + 1.8), HW + 1.8):
        add_box_verts(verts, faces, (0.5, 0.5, 6.8),
                      (p[0] + l[0] * side, p[1] + l[1] * side, p[2] + 3.4), yaw)
    add_box_verts(verts, faces, (2 * HW + 4.4, 0.45, 0.5), (p[0], p[1], p[2] + 6.9), yaw)
    add_box_verts(verts, faces, (8.0, 0.15, 1.7), (p[0], p[1] - 0.4, p[2] + 5.7), yaw)
    mesh_from("props_cn_gantry_start", verts, faces, MAT["metal"])
    furniture_cn.append({"type": "gantry", "s": 0.0, "lateral": 0.0,
                         "node": "props_cn_gantry_start"})

def rocks_cn():
    for r in range(20):
        i = random.randrange(0, N3)
        p, l = S3[i], L3[i]
        side = random.choice((-1, 1))
        lat = side * random.uniform(HW + 10.5, HW + 38.5)
        bx, by = p[0] + l[0] * lat, p[1] + l[1] * lat
        try:
            bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=1.0,
                                                  location=(0, 0, 0))
            ob = bpy.context.selected_objects[0]
        except Exception:
            continue
        me = ob.data
        sc = random.uniform(1.8, 4.2)
        for v in me.vertices:
            v.co.x += random.uniform(-0.24, 0.24)
            v.co.y += random.uniform(-0.24, 0.24)
            v.co.z += random.uniform(-0.20, 0.34)
        ob.name = "canyon_rock_" + f"{r:02d}"
        me.name = ob.name
        ob.location = (bx, by, cn_terrain_h(bx, by) - 1.0)
        ob.scale = (sc * random.uniform(0.8, 1.2), sc, sc * random.uniform(0.7, 1.0))
        me.materials.append(MAT["terrain"])
        furniture_cn.append({"type": "rock", "s": round(i * SPACING, 1),
                             "lateral": round(lat, 2), "node": ob.name})
    print("ROCKS_CN:", sum(1 for f in furniture_cn if f["type"] == "rock"))

cn_guard_runs()
cn_signs()
gantry_cn()
rocks_cn()

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
def to_gltf_axes(p):
    return [round(p[0], 3), round(p[2], 3), round(-p[1], 3)]

data = {"tracks": [
    {"id": "coastal", "name": "Coastal Circuit", "closed": True,
     "centerline": [to_gltf_axes(p) for p in S],
     "roadWidth": 15.0, "lanes": [-6.25, -3.75, -1.25, 1.25, 3.75, 6.25],
     "furniture": coastal_furniture, "junctions": []},
    {"id": "downtown", "name": "Downtown Sprint", "closed": False,
     "centerline": [to_gltf_axes(p) for p in S2],
     "roadWidth": 15.0, "lanes": [-6.25, -3.75, -1.25, 1.25, 3.75, 6.25],
     "furniture": furniture_dt, "junctions": junctions},
    {"id": "canyon", "name": "Canyon Circuit", "closed": True,
     "centerline": [to_gltf_axes(p) for p in S3],
     "roadWidth": 15.0, "lanes": [-6.25, -3.75, -1.25, 1.25, 3.75, 6.25],
     "furniture": furniture_cn, "junctions": []},
]}
json_path = os.path.join(ASSETS, "tracks_data.json")
with open(json_path, "w", encoding="utf-8") as fh:
    json.dump(data, fh)
print("JSON_OK", json_path, "furniture:", len(coastal_furniture), "+",
      len(furniture_dt), "+", len(furniture_cn), "junctions:", len(junctions))

set_path = os.path.join(ASSETS, "set.blend")
bpy.ops.wm.save_as_mainfile(filepath=set_path, compress=True)
print("BLEND_OK", set_path)

glb_path = os.path.join(ASSETS, "tracks.glb")
try:
    bpy.ops.export_scene.gltf(filepath=glb_path, export_format="GLB", export_apply=False)
    print("GLB_OK", glb_path)
except Exception as exc:
    print("GLB_FAILED:", exc)

# ---------------- env_coast.jpg (early pano, Cycles) ----------------
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
        from mathutils import Vector

        def shot(cam_name, loc, tgt, ortho_scale, filepath):
            cd = bpy.data.cameras.new(cam_name)
            if ortho_scale:
                cd.type = "ORTHO"
                cd.ortho_scale = ortho_scale
            else:
                cd.lens = 40
            ob = bpy.data.objects.new(cam_name, cd)
            scene.collection.objects.link(ob)
            loc = Vector(loc)
            tgt = Vector(tgt)
            ob.location = loc
            ob.rotation_euler = (tgt - loc).to_track_quat("-Z", "Y").to_euler()
            scene.camera = ob
            scene.render.filepath = filepath
            bpy.ops.render.render(write_still=True)
            print("SHOT_OK", filepath)

        shot("top", (80, 40, 900), (80, 40, 0), 1800, os.path.join(SHOTS, "track_top.png"))
        shot("startcam", (560, -760, 10), (640, -200, 26), None,
             os.path.join(SHOTS, "track_start.png"))
        shot("dt_top", (200, 180, 950), (200, 180, 0), 1700,
             os.path.join(SHOTS, "track_dt_top.png"))
        shot("dt_start", (-220, -320, 8), (240, 40, 4), None,
             os.path.join(SHOTS, "track_dt_start.png"))
        shot("cn_top", (-240, -60, 1050), (-240, -60, 0), 1750,
             os.path.join(SHOTS, "track_cn_top.png"))
        shot("cn_start", (80, -700, 16), (-20, -260, 14), None,
             os.path.join(SHOTS, "track_cn_start.png"))
except Exception as exc:
    print("SHOTS_SKIPPED:", exc)

print("BUILD_DONE coastal_m:", round(TRACK_LEN_COASTAL, 1), "downtown_m:",
      round(TRACK_LEN_DT, 1), "canyon_m:", round(TRACK_LEN_CN, 1),
      "samples:", N, "+", N2, "+", N3)