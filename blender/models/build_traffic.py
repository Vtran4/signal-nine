# Signal Nine — traffic set BLOCKOUTS (6 civilian types)
# Headless: blender -b -P blender/models/build_traffic.py
# Final node + material naming per the settled contract:
#   civ_<type>_body, civ_<type>_glass, civ_<type>_wheel_* (fl|fr|rl|rr, +2 tail
#   for extra axles), civ_<type>_bumper_f (only traffic detach), lights_f/r.
#   Single shared paint_traffic slot; common glass/lights/tire.
# Blender space: nose toward -Y (glTF exporter maps Blender -Y -> glTF +Z).
# Outputs: ../assets/traffic.glb, ../assets/traffic_blockout_report.json
import bpy
import bmesh
import json
import math
import os
import random
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.normpath(os.path.join(HERE, "..", "..", "assets"))
os.makedirs(ASSETS, exist_ok=True)

try:
    bpy.ops.wm.read_factory_settings(use_empty=True)
except Exception:
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
scene = bpy.context.scene

def pbr(name, color, metallic=0.0, rough=0.6):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (*color, 1.0)
    b.inputs["Metallic"].default_value = metallic
    b.inputs["Roughness"].default_value = rough
    return m

MAT = {
    "paint_traffic": pbr("paint_traffic", (0.72, 0.72, 0.70), 0.05, 0.7),
    "glass": pbr("glass", (0.04, 0.06, 0.08), 0.35, 0.12),
    "lights": pbr("lights", (1.00, 0.97, 0.88), 0.0, 0.25),
    "tire": pbr("tire", (0.03, 0.03, 0.03), 0.0, 0.9),
    "wood": pbr("wood", (0.45, 0.32, 0.18), 0.0, 0.8),
    "metal": pbr("metal", (0.60, 0.62, 0.65), 0.8, 0.4),
}

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

def extruded_profile(name, pts, width, mat, location=(0, 0, 0)):
    """pts: closed loop of (forward, up); forward<0 = nose. Vertex y = forward."""
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

def box_at(name, dims, center, mat):
    dx, dy, dz = dims
    cx, cy, cz = center
    verts = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                verts.append((sx * dx / 2, sy * dy / 2, sz * dz / 2))
    faces = [(0, 1, 3, 2), (4, 5, 7, 6), (0, 4, 5, 1),
             (2, 3, 7, 6), (0, 2, 6, 4), (1, 3, 7, 5)]
    return mesh_from(name, verts, faces, mat, center)

def circle_pts(r, seg=18):
    return [(r * math.sin(2 * math.pi * i / seg), r * math.cos(2 * math.pi * i / seg))
            for i in range(seg)]

# ---------------- WS-Q LOD0: loft machinery (GT3 hull pattern) ----------------
def densify(pts, k):
    """Shape-preserving: insert k linear interpolants per span."""
    out = []
    for a, b in zip(pts, pts[1:]):
        out.append(a)
        for j in range(1, k + 1):
            t = j / (k + 1)
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    out.append(pts[-1])
    return out


def _interp(pts, f):
    """Piecewise-linear value at f over an f-monotone (f, u) list."""
    if f <= pts[0][0]:
        return pts[0][1]
    for a, b in zip(pts, pts[1:]):
        if a[0] <= f <= b[0]:
            t = (f - a[0]) / max(1e-9, b[0] - a[0])
            return a[1] + (b[1] - a[1]) * t
    return pts[-1][1]


def split_profile(profile):
    """Closed silhouette loop -> (upper edge, lower edge), both f-monotone.
    Loop walks nose-floor -> nose-top -> ... -> tail-top -> tail-floor -> ...
    -> floor back to nose; the upper edge = everything up to the max-f point."""
    fmax_i = max(range(len(profile)), key=lambda i: profile[i][0])
    upper = profile[:fmax_i + 1]
    lower = [profile[fmax_i]] + profile[fmax_i + 1:]
    if tuple(lower[-1]) != tuple(profile[0]):
        lower.append(profile[0])
    if upper[0][0] > upper[-1][0]:
        upper = list(reversed(upper))
    if lower[0][0] > lower[-1][0]:
        lower = list(reversed(lower))
    def dd(ps):
        # drop only EXACT duplicate points - same-f different-u pairs are
        # legitimate vertical faces (nose/tail); dropping them collapsed
        # the end rings into degenerate wedges
        out = [ps[0]]
        for q in ps[1:]:
            if q != out[-1]:
                out.append(q)
        return out
    return dd(upper), dd(lower)


CIV_RING = [(-1.00, 0.00), (-1.00, 0.38), (-0.975, 0.72), (-0.90, 0.93),
            (-0.55, 1.00), (0.00, 1.02), (0.55, 1.00), (0.90, 0.93),
            (0.975, 0.72), (1.00, 0.38), (1.00, 0.00), (0.50, -0.03),
            (-0.50, -0.03)]
CIV_RING_D = densify(CIV_RING, 1)  # 13 -> 25 pts


def gauss(x, s):
    return math.exp(-0.5 * (x / s) ** 2)


def civ_ring(f, spec, upper, lower):
    """Cross-section ring at forward station f (GT3 hull_ring pattern)."""
    cz = spec["wheel_r"]
    r_arch = spec["wheel_r"] + 0.09
    fl = _interp(lower, f)
    for ax in spec["axles"]:
        df = f - ax
        if abs(df) < r_arch:
            fl = max(fl, cz + math.sqrt(r_arch ** 2 - df ** 2))
    belt = _interp(upper, f)
    fl = min(fl, belt - 0.04)
    W = spec["width"]
    nose, tail = upper[0][0], upper[-1][0]
    taper = 1.0 - 0.16 * max(gauss(f - nose, 0.55), gauss(f - tail, 0.55))
    tuck = 0.10 * max(gauss(f - spec["axles"][0], 0.22),
                      gauss(f - spec["axles"][-1], 0.22))
    w_eff = W / 2 * taper * (1.0 - tuck)
    return [(lf * w_eff, f, fl + uf * (belt - fl)) for lf, uf in CIV_RING_D]


def loft_smooth(ob):
    for poly in ob.data.polygons:
        poly.use_smooth = True
    return ob


def loft_body(tok, spec):
    """LOD0 body: rings along the length from the silhouette edges."""
    upper, lower = split_profile(spec["profile"])
    f0, f1 = upper[0][0], upper[-1][0]
    n_st = 30
    eps = 0.008 * (f1 - f0)  # skip the degenerate exact-end rings
    rings = [civ_ring(f0 + eps + (f1 - f0 - 2 * eps) * i / (n_st - 1),
                      spec, upper, lower)
             for i in range(n_st)]
    n = len(rings[0])
    verts = [v for ring in rings for v in ring]
    faces = []
    for i in range(len(rings) - 1):
        for j in range(n):
            j2 = (j + 1) % n
            faces.append((i * n + j, i * n + j2, (i + 1) * n + j2, (i + 1) * n + j))
    faces.append(tuple(range(n - 1, -1, -1)))
    base = (len(rings) - 1) * n
    faces.append(tuple(range(base, base + n)))
    return loft_smooth(mesh_from(tok + "_body", verts, faces,
                                 MAT["paint_traffic"]))


CANOPY_RING = [(-1, 0.0), (-0.94, 0.55), (-0.70, 0.93), (0.0, 1.0),
               (0.70, 0.93), (0.94, 0.55), (1, 0.0)]


def loft_canopy(tok, spec):
    """Canopy glass loft: band from the body's belt line up to the canopy
    roofline, narrower than the body (canopy_w)."""
    upper, _ = split_profile(spec["profile"])
    up = spec["canopy"]
    f0, f1 = up[0][0], up[-1][0]
    n_st = 12
    gw = spec["width"] * spec["canopy_w"] / 2.0
    rings = []
    for i in range(n_st):
        f = f0 + (f1 - f0) * i / (n_st - 1)
        b = _interp(upper, f)            # belt (body top edge) at f
        t = _interp(up, f)               # canopy roofline at f
        rings.append([(lf * gw, f, b + uf * max(0.05, t - b))
                      for lf, uf in CANOPY_RING])
    n = len(rings[0])
    verts = [v for ring in rings for v in ring]
    faces = []
    for i in range(len(rings) - 1):
        for j in range(n):
            j2 = (j + 1) % n
            faces.append((i * n + j, i * n + j2, (i + 1) * n + j2, (i + 1) * n + j))
    faces.append(tuple(range(n - 1, -1, -1)))
    base = (len(rings) - 1) * n
    faces.append(tuple(range(base, base + n)))
    return loft_smooth(mesh_from(tok + "_glass", verts, faces, MAT["glass"]))


def make_wheel(name, spec, x, axle):
    """24-seg cylinder tire with annulus caps (GT3 tire pattern)."""
    R = spec["wheel_r"]
    tw = spec["tire_w"]
    SU = 24
    half = tw / 2
    rin = R * 0.62
    verts, faces = [], []
    for xs in (-half, half):
        for i in range(SU):
            a = 2 * math.pi * i / SU
            verts.append((xs, R * math.sin(a), R * math.cos(a)))
    for i in range(SU):
        i2 = (i + 1) % SU
        faces.append((i, i2, SU + i2, SU + i))
    for si, xs in ((0, -half), (1, half)):
        base = len(verts)
        for i in range(SU):
            a = 2 * math.pi * i / SU
            verts.append((xs, R * math.sin(a), R * math.cos(a)))
        for i in range(SU):
            a = 2 * math.pi * i / SU
            verts.append((xs, rin * math.sin(a), rin * math.cos(a)))
        for i in range(SU):
            i2 = (i + 1) % SU
            faces.append((base + i, base + i2, base + SU + i2, base + SU + i))
    return mesh_from(name, verts, faces, MAT["tire"], location=(x, axle, R))

# ---------------- specs (blockout massing, meters; forward<0 = nose) ----------------
CIVS = {
    "sedan": {
        "width": 1.85, "wheel_r": 0.33, "tire_w": 0.24, "track_half": 0.80,
        "axles": [-1.45, 1.35],
        "profile": [(-2.40, 0.30), (-2.40, 0.62), (-1.60, 0.78), (-0.90, 0.82),
                    (-0.15, 1.42), (0.85, 1.40), (1.70, 1.02), (2.40, 0.92),
                    (2.40, 0.32), (1.20, 0.20), (-1.20, 0.20)],
        "canopy": [(-0.90, 0.80), (-0.15, 1.44), (0.85, 1.42), (1.45, 1.02)],
        "canopy_w": 0.82, "bump_u": 0.45, "extra_axle": None,
    },
    "hatch": {
        "width": 1.75, "wheel_r": 0.31, "tire_w": 0.24, "track_half": 0.76,
        "axles": [-1.30, 1.20],
        "profile": [(-2.05, 0.30), (-2.05, 0.62), (-1.35, 0.80), (-0.65, 0.84),
                    (0.05, 1.46), (0.75, 1.44), (1.35, 1.20), (2.05, 0.98),
                    (2.05, 0.32), (1.00, 0.20), (-1.00, 0.20)],
        "canopy": [(-0.65, 0.82), (0.05, 1.48), (0.75, 1.46), (1.15, 1.22)],
        "canopy_w": 0.82, "bump_u": 0.44, "extra_axle": None,
    },
    "pickup": {
        "width": 1.95, "wheel_r": 0.37, "tire_w": 0.28, "track_half": 0.82,
        "axles": [-1.65, 1.55],
        "profile": [(-2.70, 0.36), (-2.70, 0.72), (-1.90, 0.88), (-1.10, 0.92),
                    (-0.35, 1.72), (0.35, 1.70), (0.75, 1.30), (2.70, 1.24),
                    (2.70, 0.40), (1.30, 0.26), (-1.30, 0.26)],
        "canopy": [(-1.10, 0.90), (-0.35, 1.74), (0.35, 1.72), (0.60, 1.32)],
        "canopy_w": 0.82, "bump_u": 0.52, "extra_axle": None,
    },
    "boxvan": {
        "width": 2.05, "wheel_r": 0.38, "tire_w": 0.28, "track_half": 0.85,
        "axles": [-1.70, 1.60],
        "profile": [(-2.90, 0.38), (-2.90, 0.80), (-2.20, 0.95), (-1.50, 1.00),
                    (-1.10, 2.45), (2.90, 2.45), (2.90, 0.42), (1.40, 0.28),
                    (-1.40, 0.28)],
        "canopy": [(-1.50, 0.98), (-1.15, 2.30), (-0.95, 2.32), (-0.90, 1.05)],
        "canopy_w": 0.86, "bump_u": 0.55, "extra_axle": None,
    },
    "bus": {
        "width": 2.50, "wheel_r": 0.52, "tire_w": 0.30, "track_half": 1.05,
        "axles": [-3.00, 3.00],
        "profile": [(-5.50, 0.45), (-5.50, 2.85), (5.50, 2.85), (5.50, 0.50),
                    (3.50, 0.30), (-3.50, 0.30)],
        "canopy": [(-5.50, 1.60), (-5.48, 2.55), (-5.28, 2.55), (-5.28, 1.60)],
        "canopy_w": 0.86, "bump_u": 0.62, "extra_axle": None,
    },
    "semi": {
        "width": 2.45, "wheel_r": 0.52, "tire_w": 0.30, "track_half": 1.02,
        "axles": [-6.50, -3.20, 6.50],
        "cab": [(-8.00, 0.40), (-8.00, 1.15), (-7.00, 1.45), (-6.20, 1.50),
                (-5.70, 3.35), (-2.20, 3.35), (-2.20, 0.90), (-6.90, 0.90)],
        "trailer": [(-1.90, 1.20), (-1.90, 3.60), (8.00, 3.60), (8.00, 1.20)],
        "canopy": [(-7.00, 1.45), (-6.30, 1.52), (-6.15, 2.90), (-5.85, 2.95)],
        "canopy_w": 0.84, "bump_u": 0.66, "extra_axle": "rl2",
    },
}

CIVS["semi"]["profile"] = CIVS["semi"]["cab"] + CIVS["semi"]["trailer"]  # combined extents for the report

# ---------------- builder ----------------
def build_civ(tok, spec):
    parts = []
    if "cab" in spec:
        # semi: cab+trailer combined profile is not a closed loop - loft
        # the cab, keep the box trailer as a prism
        cab_spec = dict(spec)
        cab_spec["profile"] = spec["cab"]
        body = loft_body(tok + "_cab", cab_spec)
        body.name = tok + "_body"  # contract: civ-type_body
        trl = extruded_profile(tok + "_trailer", spec["trailer"],
                               spec["width"] * 0.98, MAT["paint_traffic"])
        parts.append(trl)
    else:
        body = loft_body(tok, spec)
    parts.append(loft_canopy(tok, spec))
    keys = ("fl", "fr", "rl", "rr")
    axles = [spec["axles"][0], spec["axles"][-1]]
    if spec["extra_axle"]:
        axles.insert(1, spec["axles"][1])
        keys = ("fl", "fr", "rl", "rr", "rl2", "rr2")
    for key, axle in zip(keys, axles):
        x = -spec["track_half"] if key.startswith(("fl", "rl")) else spec["track_half"]
        parts.append(make_wheel(tok + "_wheel_" + key, spec, x, axle))
    nose = spec["profile"][0][0]
    tail = max(p[0] for p in spec["profile"])
    parts.append(box_at(tok + "_bumper_f",
                        (spec["width"] * 0.96, 0.14, 0.28),
                        (0.0, nose - 0.04, spec["bump_u"]), MAT["paint_traffic"]))
    parts.append(box_at(tok + "_lights_f",
                        (spec["width"] * 0.55, 0.06, 0.10),
                        (0.0, nose + 0.01, spec["bump_u"] + 0.22), MAT["lights"]))
    parts.append(box_at(tok + "_lights_r",
                        (spec["width"] * 0.55, 0.06, 0.10),
                        (0.0, tail - 0.02, spec["bump_u"] + 0.22), MAT["lights"]))
    # E7: real seams — ejectable panels at natural body lines (bumper_r on all,
    # hood where the shape has one, pickup tailgate). Panels EJECT on shatter,
    # so the crumple hull never has to match a panel that stayed behind.
    parts.append(box_at(tok + "_bumper_r",
                        (spec["width"] * 0.96, 0.14, 0.28),
                        (0.0, tail + 0.04, spec["bump_u"]), MAT["paint_traffic"]))
    if tok in ("sedan", "hatch", "pickup", "boxvan"):
        hood_f0, hood_f1 = spec["profile"][0][0] + 0.12, spec["canopy"][0][0] - 0.06
        hood_u = max(u for f, u in spec["profile"] if hood_f0 <= f <= hood_f1)
        parts.append(box_at(tok + "_hood",
                            (spec["width"] * 0.86, max(0.5, hood_f1 - hood_f0), 0.035),
                            (0.0, (hood_f0 + hood_f1) / 2, hood_u + 0.02),
                            MAT["paint_traffic"]))
    if tok == "pickup":
        parts.append(box_at(tok + "_bedpanel",
                            (spec["width"] * 0.88, 0.06, 0.45),
                            (0.0, tail - 0.05, 1.02), MAT["paint_traffic"]))
    # dressing (deterministic per type): mirrors, exhaust, dents, type kit
    rng = random.Random(zlib.crc32(tok.encode("utf-8")))
    W = spec["width"]
    mf = spec["canopy"][0][0]
    mu = spec["canopy"][0][1] + 0.12
    for sx in (-1, 1):
        parts.append(box_at(tok + "_mirror_stalk_" + ("l" if sx < 0 else "r"),
                            (0.16, 0.03, 0.03), (sx * (W / 2 + 0.08), mf, mu), MAT["tire"]))
        parts.append(box_at(tok + "_mirror_" + ("l" if sx < 0 else "r"),
                            (0.06, 0.09, 0.13), (sx * (W / 2 + 0.18), mf, mu), MAT["tire"]))
    parts.append(box_at(tok + "_exhaust", (0.06, 0.20, 0.06),
                        (W / 2 - 0.28, tail - 0.18, 0.26), MAT["tire"]))
    amp = 0.020 if tok in ("bus", "semi", "boxvan") else 0.011
    for p in parts:
        if p.name in (tok + "_body", tok + "_cab", tok + "_trailer"):
            for v in p.data.vertices:
                v.co.x += rng.uniform(-amp, amp)
                v.co.y += rng.uniform(-amp, amp)
                v.co.z += rng.uniform(-amp, amp)
    if tok == "sedan":
        parts.append(box_at(tok + "_antenna", (0.02, 0.02, 0.42),
                            (0.55, 1.55, 1.16), MAT["tire"]))
    if tok == "hatch":
        parts.append(box_at(tok + "_spoiler", (1.15, 0.16, 0.05),
                            (0.0, spec["profile"][7][0] - 0.05,
                             spec["profile"][7][1] + 0.06), MAT["paint_traffic"]))
    if tok == "pickup":
        for k, (bx, bf) in enumerate(((-0.38, 1.30), (0.30, 1.75), (-0.05, 2.25))):
            parts.append(box_at(tok + "_bedload_" + str(k), (0.55, 0.55, 0.42),
                                (bx, bf, 1.42), MAT["wood"]))
    if tok == "boxvan":
        for sx in (-1, 1):
            parts.append(box_at(tok + "_rack_rail_" + ("l" if sx < 0 else "r"),
                                (0.06, 3.2, 0.09), (sx * 0.72, 0.4, 2.56), MAT["metal"]))
        for k in range(4):
            parts.append(box_at(tok + "_rack_bar_" + str(k), (1.56, 0.06, 0.07),
                                (0.0, -0.9 + k * 0.9, 2.60), MAT["metal"]))
    if tok == "bus":
        parts.append(box_at(tok + "_acpod", (2.2, 1.7, 0.35),
                            (0.0, 1.4, 3.02), MAT["paint_traffic"]))
        parts.append(box_at(tok + "_grille", (2.0, 0.06, 0.5),
                            (0.0, 5.44, 1.6), MAT["tire"]))
    if tok == "semi":
        # trailer running gear: landing gear struts + rear underride bar
        parts.append(box_at(tok + "_landinggear_l", (0.10, 0.30, 0.85),
                            (-0.55, 0.20, 0.60), MAT["metal"]))
        parts.append(box_at(tok + "_landinggear_r", (0.10, 0.30, 0.85),
                            (0.55, 0.20, 0.60), MAT["metal"]))
        parts.append(box_at(tok + "_underride_r", (spec["width"] * 0.9, 0.08, 0.12),
                            (0.0, tail - 0.25, 0.55), MAT["metal"]))
        for sx in (-1, 1):
            parts.append(box_at(tok + "_stack_" + ("l" if sx < 0 else "r"),
                                (0.14, 0.14, 2.5), (sx * 0.82, -2.75, 2.1), MAT["metal"]))
            parts.append(box_at(tok + "_mudflap_" + ("l" if sx < 0 else "r"),
                                (0.42, 0.03, 0.42), (sx * 0.95, 7.35, 0.42), MAT["tire"]))
            for k in range(4):
                parts.append(box_at(tok + "_rib_" + ("l" if sx < 0 else "r") + "_" + str(k),
                                    (0.05, 0.12, 2.2),
                                    (sx * (W * 0.49), -0.8 + k * 2.2, 2.4), MAT["tire"]))
    for p in parts:
        if p is not body:
            p.parent = body
    return body

offsets = {"sedan": -14.0, "hatch": -7.0, "pickup": 0.0,
           "boxvan": 8.0, "bus": 19.0, "semi": 33.0}
bodies = {}
for tok, spec in CIVS.items():
    bodies[tok] = build_civ(tok, spec)
    bodies[tok].location.x = offsets[tok]

# ---------------- report ----------------
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

report = {"generated_by": "build_traffic.py (blockout)", "units": "meters",
          "note": "Blockout massing, final node/material naming. Forward = glTF +Z after export. Shared paint_traffic slot; detach = civ_*_bumper_f only.",
          "materials": list(MAT.keys()), "dressed": True, "vehicles": []}
for tok, spec in CIVS.items():
    objs = subtree(bodies[tok])
    tris = sum(tri_count(o) for o in objs)
    fs = [p[0] for p in spec["profile"]]
    us = [p[1] for p in spec["profile"]]
    report["vehicles"].append({
        "type": "civ_" + tok, "tri_count": tris,
        "dims": {"length": round(max(fs) - min(fs), 2), "width": spec["width"],
                 "height": round(max(us), 2)},
        "axles_forward": spec["axles"],
        "wheelbase": round(spec["axles"][-1] - spec["axles"][0], 2),
        "track": round(2 * spec["track_half"], 2),
        "wheel_radius": spec["wheel_r"],
        "nodes": sorted(o.name for o in objs),
    })
report_path = os.path.join(ASSETS, "traffic_blockout_report.json")
with open(report_path, "w", encoding="utf-8") as fh:
    json.dump(report, fh, indent=2)
for v in report["vehicles"]:
    print("CIV", v["type"], "tris:", v["tri_count"], "dims:", v["dims"],
          "axles:", v["axles_forward"], "track:", v["track"])

# ---------------- export (centered) ----------------
for tok in CIVS:
    bodies[tok].location.x = 0.0
glb_path = os.path.join(ASSETS, "traffic.glb")
try:
    bpy.ops.export_scene.gltf(filepath=glb_path, export_format="GLB", export_apply=False)
    print("GLB_OK", glb_path)
except Exception as exc:
    print("GLB_FAILED:", exc)
print("REPORT_OK", report_path)