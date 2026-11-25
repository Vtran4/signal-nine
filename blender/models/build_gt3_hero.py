# build_gt3_hero.py — WS-A hero: ONE GT3-class body, 9 palette/livery variants.
# Node contract v2 (coder bd36aeb/5364a94 — frozen):
#   gt3_body, gt3_glass, gt3_bumper_f|_r, gt3_hood(+gt3_hood_louvers),
#   gt3_wing(+gt3_wing_pylon_l|r+gt3_wing_endplate_l|r), gt3_splitter,
#   gt3_wheel_fl|fr|rl|rr + gt3_rim_*, gt3_lights_f, gt3_lights_r_tailrings,
#   gt3_lights_r_rainlight, gt3_diffuser, gt3_deck_louvers, gt3_intake_scoop,
#   gt3_canards, gt3_mirror_l|r.
# Eject list v2: bumper_f|bumper_r|hood|spoiler|wing|splitter + wheel_/rim_.
# Materials: paint_gt3 (variant slot), glass_gt3, lights_f (auto warm-white),
#   lights_r (auto red emissive), carbon_* authored, tire, rim_gunmetal.
# Geometry derived from concept art/ turnaround (carside/carfront/carback):
#   L 4.55m, H 1.22m roof, WB 2.60m (0.57L), wheel dia 0.68m, width 2.0m,
#   cab-forward mid-engine, long deck, swan-neck wing at ~0.93 roof.
# Run: blender -b -P blender/models/build_gt3_hero.py
import bpy
import math
import json
import os
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
ASSETS = os.path.join(ROOT, "assets")
SHOTS = os.path.join(ROOT, "blender", "shots")
os.makedirs(SHOTS, exist_ok=True)

# ---------------- proportions (turnaround-locked) ----------------
SPEC = {
    "display": "GT3 Prototype", "width": 2.00,
    "nose": -2.275, "tail": 2.275, "floor": 0.07,
    # top profile v4: fender PEAKS at the axle stations (the art's "highest
    # body points after the roof" — they must exceed the arch apex), plunging
    # hood valley between them, cab-forward roof 1.14 (locked 4:1 L:H),
    # decisive fastback, Kamm tail
    "top": [(-2.275, 0.36), (-1.80, 0.70), (-1.30, 0.88), (-0.80, 0.80),
            (-0.38, 1.14), (0.05, 1.13), (0.45, 0.96), (0.85, 0.84),
            (1.30, 0.86), (1.85, 0.76), (2.10, 0.70), (2.24, 0.71),
            (2.275, 0.70)],
    # belt = fender/shoulder line: rises to ~arch height at the axles
    "belt": [(-2.275, 0.40), (-1.30, 0.66), (-0.80, 0.62), (-0.30, 0.72),
             (0.30, 0.74), (0.85, 0.70), (1.30, 0.74), (2.275, 0.56)],
    # plan: rear haunch widest (hips at ~f 1.55), boat-tail taper to the tail
        "plan": [(-2.275, 0.86), (-1.45, 0.96), (-0.30, 1.00), (0.80, 0.98),
                 (1.55, 1.03), (2.275, 0.88)],
    "flares": (-1.40, 1.50, 0.055),
    "gh": (-0.95, 0.35, 0.80),          # greenhouse FORWARD of center
    "wheel_r": 0.33, "tire_w": 0.32, "track_half": 0.86, "axles": (-1.30, 1.30),
}

# ---------------- materials ----------------
def pbr(name, color, metallic=0.0, rough=0.5):
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (*color, 1.0)
    b.inputs["Metallic"].default_value = metallic
    b.inputs["Roughness"].default_value = rough
    # Workbench MATERIAL mode renders the VIEWPORT DISPLAY color, not the
    # node tree — without this every review render shows default 0.8 gray
    # (the tailband/rings/endplate colors were silently invisible in clay)
    m.diffuse_color = (*color, 1.0)
    m.metallic = metallic
    m.roughness = rough
    return m


MAT = {
    "paint_gt3": pbr("paint_gt3", (0.92, 0.92, 0.94), 0.0, 0.18),
    "carbon_weave_gloss": pbr("carbon_weave_gloss", (0.035, 0.035, 0.04), 0.0, 0.28),
    "carbon_matte_mesh": pbr("carbon_matte_mesh", (0.02, 0.02, 0.025), 0.0, 0.75),
    "glass_gt3": pbr("glass_gt3", (0.02, 0.02, 0.03), 0.0, 0.08),
    "tire": pbr("tire", (0.015, 0.015, 0.015), 0.0, 0.92),
    "rim_gunmetal": pbr("rim_gunmetal", (0.10, 0.10, 0.115), 0.85, 0.35),
    "rim_redring": pbr("rim_redring", (0.55, 0.03, 0.03), 0.0, 0.35),
    "caliper_red": pbr("caliper_red", (0.45, 0.02, 0.02), 0.0, 0.4),
    "lights_f": pbr("lights_f", (0.85, 0.87, 0.92), 0.0, 0.15),
    "lights_r": pbr("lights_r", (0.55, 0.02, 0.02), 0.0, 0.25),
    "mesh_dark": pbr("mesh_dark", (0.015, 0.015, 0.018), 0.0, 0.85),
}

# ---------------- curve helpers (build_cars_final conventions) ----------------
def curve(keys, f):
    if f <= keys[0][0]:
        return keys[0][1]
    for i in range(len(keys) - 1):
        a, b = keys[i], keys[i + 1]
        if a[0] <= f <= b[0]:
            t = (f - a[0]) / max(1e-9, b[0] - a[0])
            return a[1] + t * (b[1] - a[1])
    return keys[-1][1]


def gauss(x, s):
    return math.exp(-(x * x) / (2 * s * s))


def halfwidth(f):
    w = curve(SPEC["plan"], f)
    fa, ra, amp = SPEC["flares"]
    return w + amp * (gauss(f - fa, 0.55) + gauss(f - ra, 0.55))


def deck_of(f):
    g0, g1, _ = SPEC["gh"]
    if g0 <= f <= g1:
        return curve(SPEC["belt"], f)
    return curve(SPEC["top"], f)


HULL_RING = [(-1.00, 0.00), (-1.00, 0.45), (-0.96, 0.80), (-0.90, 1.00),
             (-0.45, 1.02), (0.00, 1.03), (0.45, 1.02), (0.90, 1.00),
             (0.96, 0.80), (1.00, 0.45), (1.00, 0.00), (0.50, 0.00), (-0.50, 0.00)]
GH_RING = [(-1.00, 0.00), (-0.88, 0.55), (-0.62, 0.92), (0.00, 1.00),
           (0.62, 0.92), (0.88, 0.55), (1.00, 0.00)]


def mesh_from(name, verts, faces, mat, location=(0, 0, 0), smooth=False):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate()
    bm = __import__("bmesh").new()
    bm.from_mesh(me)
    bm.to_mesh(me)
    bm.free()
    if smooth:
        for p in me.polygons:
            p.use_smooth = True
    ob = bpy.data.objects.new(name, me)
    ob.location = location
    if mat is not None:
        me.materials.append(mat)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def loft(name, rings, mat, smooth=True, cap_start=True, cap_end=True):
    verts, faces = [], []
    n = len(rings[0])
    for ring in rings:
        verts.extend(ring)
    m = len(rings)
    for i in range(m - 1):
        for j in range(n):
            j2 = (j + 1) % n
            faces.append((i * n + j, i * n + j2, (i + 1) * n + j2, (i + 1) * n + j))
    if cap_start:
        faces.append(tuple(range(n - 1, -1, -1)))
    if cap_end:
        base = (m - 1) * n
        faces.append(tuple(range(base, base + n)))
    return mesh_from(name, verts, faces, mat, smooth=smooth)


def hull_ring(f):
    """Hull top = deck_of(f) (fender peaks at the axles). Arch openings =
    the UPPER SEMICIRCLE of the clearance circle (radius tire+5cm centered at
    the wheel center): fl(df) = max(floor, cz + sqrt(r_arch^2 - df^2)) — the
    earlier apex-minus-sqrt form INVERTED the arch (lifted the edges, not the
    crown), pressing the body onto the tire's sides."""
    fa, ra = SPEC["axles"]
    cz = SPEC["wheel_r"]
    r_arch = SPEC["wheel_r"] + 0.05
    fl = SPEC["floor"]
    for ax in (fa, ra):
        df = f - ax
        if abs(df) < r_arch:
            fl = max(fl, cz + math.sqrt(r_arch ** 2 - df ** 2))
    belt = deck_of(f)
    fl = min(fl, belt - 0.03)
    tuck = 0.15 * max(gauss(f - fa, 0.16), gauss(f - ra, 0.16))
    w = halfwidth(f)
    ring = []
    for lf, uf in HULL_RING_D:
        w_eff = w * (1.0 - tuck) if uf <= 0.45 else w
        ring.append((lf * w_eff, f, fl + uf * (belt - fl)))
    return ring


def gh_ring(f):
    g0, g1, gwf = SPEC["gh"]
    belt = curve(SPEC["belt"], f)
    top = curve(SPEC["top"], f)
    gw = halfwidth(f) * gwf
    return [(lf * gw, f, belt + uf * (top - belt)) for lf, uf in GH_RING_D]


# ---------------- build ----------------
def densify(profile, k):
    """Shape-preserving densification: insert k linear interpolants into
    every span of a [(lf, uf), ...] profile. Control points unchanged, so
    the silhouette is identical — only tessellation density rises."""
    out = []
    for i, (a, b) in enumerate(zip(profile, profile[1:])):
        out.append(a)
        for j in range(1, k + 1):
            t = j / (k + 1)
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    out.append(profile[-1])
    return out


# WS-Q hi-res: densified ring profiles (shape-preserving; see densify())
HULL_RING_D = densify(HULL_RING, 3)   # 13 -> 49 pts
GH_RING_D = densify(GH_RING, 1)       # 7 -> 13 pts

def clear_scene():
    for ob in list(bpy.context.scene.objects):
        bpy.data.objects.remove(ob, do_unlink=True)


def build_wheels():
    """Hub-local pairs: gt3_wheel_* (tire torus) + gt3_rim_* (disc+spokes),
    origin at hub center; _fl/_fr members steer."""
    fa, ra = SPEC["axles"]
    r, tw = SPEC["wheel_r"], SPEC["tire_w"]
    out = []
    for tag, f_axle, side in (("fl", fa, -1), ("fr", fa, 1),
                              ("rl", ra, -1), ("rr", ra, 1)):
        x = SPEC["track_half"] * side
        # WS-Q tire rebuild: flat-faced cylinder (two rings + two caps) —
        # the torus buried the rim face inside the tube volume (disc radius
        # 0.21 > torus hole 0.13), hiding spokes/ring/hub entirely.
        verts, faces = [], []
        R, rr = r - 0.10, 0.10
        SU = 36
        half = tw / 2
        for xs in (-half, half):
            for i in range(SU):
                a = 2 * math.pi * i / SU
                verts.append((xs, R * math.sin(a), R * math.cos(a)))
        for i in range(SU):
            i2 = (i + 1) % SU
            faces.append((i, i2, SU + i2, SU + i))
        # caps as ANNULI (open centers): a solid cap disc seals the rim face
        # inside the cylinder - the rim/spokes must show through the center
        rin = 0.245  # sidewall covers ~75% of R: ring/barrel/spokes show
        for si, xs in ((0, -half), (1, half)):
            cap_v, cap_f = [], []
            for i in range(SU):
                a = 2 * math.pi * i / SU
                cap_v.append((xs, rin * math.sin(a), rin * math.cos(a)))
            base = len(verts)
            for i in range(SU):
                a = 2 * math.pi * i / SU
                verts.append((xs, R * math.sin(a), R * math.cos(a)))
            for i in range(SU):
                i2 = (i + 1) % SU
                cap_f.append((base + i, base + i2, base + SU + i2, base + SU + i))
            verts.extend(cap_v)
            faces.extend(cap_f)
        wheel = mesh_from("gt3_wheel_" + tag, verts, faces, MAT["tire"],
                          location=(x, f_axle, r), smooth=True)
        rv, rf = [], []
        rr2 = R - 0.02
        # rim = OPEN structure: thin outer barrel band (both x-faces) +
        # 18 spokes + hub face. NO solid caps - a closed barrel face
        # renders as a blank slate disc hiding the spokes behind it.
        for xs in (-tw * 0.5, tw * 0.5):
            for k in range(14):
                a = 2 * math.pi * k / 14
                rv.append((xs, rr2 * math.sin(a), rr2 * math.cos(a)))
            for k in range(14):
                a = 2 * math.pi * k / 14
                rv.append((xs, 0.16 * math.sin(a), 0.16 * math.cos(a)))
        for k in range(14):
            k2 = (k + 1) % 14
            rf.append((k, k2, 14 + k2, 14 + k))
            rf.append((28 + k, 28 + k2, 42 + k2, 42 + k))
                # NO caps: the barrel is open front and back — a solid cap face
                # renders as a blank slate disc that hides the spokes behind it.
        # 18 paired spokes, thin (WS-Q carside.png revision: multi-spoke read)
        for s in range(9):
            a = 2 * math.pi * s / 9 + 0.3
            base = len(rv)
            ca, sa = math.cos(a), math.sin(a)
            for sx in (-1, 1):
                for sy in (-0.009, 0.009):  # 18mm blades: 0.055 half-width overlapped
                    # into a solid disc (18 x 0.11m >> mid-radius circle)
                    for sz in (rr2 * 0.30, rr2 * 0.85):
                        rv.append((sx * tw * 0.46, sy * ca - sz * sa, sy * sa + sz * ca))
            for f in [(0, 1, 3, 2), (4, 5, 7, 6), (0, 4, 5, 1),
                      (2, 3, 7, 6), (0, 2, 6, 4), (1, 3, 7, 5)]:
                rf.append(tuple(vi + base for vi in f))
        rim = mesh_from("gt3_rim_" + tag, rv, rf, MAT["rim_gunmetal"],
                        location=(x, f_axle, r))
        # red rim-ring (WS-Q carside.png): thin red band at the rim barrel's
        # outer edge, both faces — the livery tie-in meshed at last
        # red rim-ring as FLAT ANNULI in the wheel planes (carside.png):
        # a barrel band is edge-on invisible from the side elevation; the
        # read comes from rings lying IN the wheel face (inner radius just
        # inside the barrel band, outer just past it)
        ring_v, ring_f = [], []
        rin_r, rout_r = 0.155, 0.218
        for xs in (-tw * 0.5 + 0.004, tw * 0.5 - 0.004):
            for rad in (rin_r, rout_r):
                for k in range(28):
                    a = 2 * math.pi * k / 28
                    ring_v.append((xs, rad * math.sin(a), rad * math.cos(a)))
        for si in (0, 1):
            b = si * 56
            for k in range(28):
                k2 = (k + 1) % 28
                ring_f.append((b + k, b + k2, b + 28 + k2, b + 28 + k))
        mesh_from("gt3_rimring_" + tag, ring_v, ring_f, MAT["caliper_red"],
                  location=(x, f_axle, r))
        # hub cap: small center-lock disc at the wheel center (radius
        # 0.055 sits inside the spokes' inner ends; the old rr2 radius
        # made a full-face disc that read as a solid rim through the
        # open barrel), flush just outboard of the tire face
        hub_v, hub_f = [], []
        for k in range(14):
            a = 2 * math.pi * k / 14
            hub_v.append((tw * 0.5 + 0.004, 0.055 * math.sin(a), 0.055 * math.cos(a)))
        # WS-Q AO fix: the single-ngon disc's winding gives a -X normal;
        # on the right-side wheels that points INBOARD (the AO bake's ray
        # hemisphere then sits inside the wheel → hub_fr/hub_rr baked
        # black while fl/rl baked gray). Reverse the winding on +X sides.
        hub_face = tuple(range(14)) if side < 0 else tuple(range(13, -1, -1))
        mesh_from("gt3_hub_" + tag, hub_v, [hub_face],
          pbr("gt3_hub_gray", (0.30, 0.30, 0.31), 0.0, 0.6),
          location=(x, f_axle, r))
        # red caliper block behind the spokes: an ARC segment hugging the
        # barrel (12 o'clock, 45 deg span) with real thickness - a flat
        # plate at the hub read as nothing; the arc reads as a caliper
        cal_v, cal_f = [], []
        r_cal_in, r_cal_out = 0.095, 0.155
        cal_seg = 7
        for xs in (-tw * 0.10, tw * 0.10):
            for rad in (r_cal_in, r_cal_out):
                for k in range(cal_seg + 1):
                    a = math.pi / 2 + (math.pi / 4) * k / cal_seg
                    cal_v.append((xs, rad * math.sin(a), rad * math.cos(a)))
        for b in (0, 2 * (cal_seg + 1)):
            for rad_i in (0, 1):
                base = b + rad_i * (cal_seg + 1)
                for k in range(cal_seg):
                    cal_f.append((base + k, base + k + 1,
                                  base + (cal_seg + 1) + k + 1,
                                  base + (cal_seg + 1) + k))
        for b in (0, 2 * (cal_seg + 1)):
            cal_f.append((b, b + cal_seg, b + 2 * (cal_seg + 1) - 1,
                          b + (cal_seg + 1)))
        mesh_from("gt3_caliper_" + tag, cal_v, cal_f, MAT["caliper_red"],
                  location=(x, f_axle, r))
        out.append((wheel, rim))
    return out


def build_body():
    """Hull loft + greenhouse. The canopy splits into a GLASS band (f -0.95
    to -0.38: raked windshield + side windows) and a PAINT roof cap (f -0.38
    to +0.35, upper canopy) — the break is what makes cab-forward read."""
    # WS-Q hi-res round: shape-preserving densification (densify() keeps
    # every control point; only tessellation density rises) — target ~21k
    # tris on the REVISED silhouette for the 2048^2 body maps
    n_st = 160
    f0, f1 = SPEC["nose"], SPEC["tail"]
    rings = [hull_ring(f0 + (f1 - f0) * i / (n_st - 1)) for i in range(n_st)]
    body = loft("gt3_body", rings, MAT["paint_gt3"], smooth=True)
    g0, g1, _ = SPEC["gh"]
    gn = 28
    grings = [gh_ring(g0 + (g1 - g0) * i / (gn - 1)) for i in range(gn)]
    glass = loft("gt3_glass", grings, MAT["glass_gt3"], smooth=True)
    # paint roof cap over the rear canopy: FLATTER fall than the glass slope
    # so the header reads as an angle break, front edge slightly proud;
    # extends PAST the greenhouse end (0.42) so it merges into the deck and
    # the junction crease softens
    f_cap0, f_cap1 = -0.38, 0.42
    cn = 24
    cap_rings = []
    for i in range(cn):
        f = f_cap0 + (f_cap1 - f_cap0) * i / (cn - 1)
        ring = gh_ring(f)
        belt = ring[0][2]
        top = ring[3][2]  # GH_RING peak index 3
        # cap top: fastback FALL from the roof (1.14 at the header) into the rear
        # deck — the old flat cap ended 0.35m above the deck (a visible cliff)
        t01 = (f - f_cap0) / max(1e-9, f_cap1 - f_cap0)
        cap_top = 1.14 - (1.14 - top) * (t01 ** 0.85)
        cap_rings.append([(px, py, belt + (0.45 + 0.55 * uf) * (cap_top - belt))
                  for px, py, uf, *_ in
                  [(p[0], p[1], (p[2] - belt) / max(1e-9, top - belt)) for p in ring]])
    roof = loft("gt3_roof", cap_rings, MAT["paint_gt3"], smooth=True)
    # inner arch liners: closed dark cylinders INSIDE the body (two-sided
    # barrel + end caps, clipped to the arch zone so nothing pokes below the
    # rocker), closing the arch see-through without backface artifacts
    fa, ra = SPEC["axles"]
    rr_w = SPEC["wheel_r"] + 0.03
    for tag, ax in (("fl", fa), ("fr", fa), ("rl", ra), ("rr", ra)):
        side = -1 if tag.endswith("l") else 1
        x = SPEC["track_half"] * side * 0.62
        z0, z1 = 0.04, rr_w + 0.06
        wv, wf = [], []
        seg = 16
        for xf in (x - 0.13, x + 0.13):
                    for j in range(seg):
                        a = math.pi * j / (seg - 1)   # half-circle arch (z0..z1)
                        wv.append((xf, ax + rr_w * math.cos(a), z0 + (z1 - z0) * math.sin(a)))
        wf.append(tuple(range(seg)))                     # cap -x
        wf.append(tuple(range(seg, 2 * seg)))            # cap +x
        for j in range(seg - 1):                         # barrel wall
            wf.append((j, j + 1, seg + j + 1, seg + j))
        mesh_from("gt3_archliner_" + tag, wv, wf,
          pbr("gt3_well_black", (0.012, 0.012, 0.014), 0.0, 0.95))
    return body, glass, roof


def build_wing():
    """Single-element swan-neck wing: plane + gurney + 2 pylons + red endplates.
    Plane at ~0.90 of the CURRENT roof height (1.14), span = body width,
    chord 0.42; endplate tops land at ~roof height per the reference."""
    top_roof = 1.14
    plane_z = 0.90 * top_roof
    span = SPEC["width"] - 0.06
    chord = 0.42
    cy = 1.95  # wing chord center ahead of the tail
    thick = 0.055  # 13% of chord — 0.035 read paper-thin in clay
    # plane: simple airfoil-ish slab (12 verts around the chord x section)
    verts, faces = [], []
    prof = [(0.0, 0.0), (0.30, 0.012), (0.42, -0.008), (0.30, -0.024),
            (0.10, -0.032), (0.0, -0.02)]
    for s in (-span / 2, span / 2):
        for px, pz in prof:
            verts.append((s, cy + px, plane_z + pz))
    m = len(prof)
    for j in range(m - 1):
        faces.append((j, j + m, j + m + 1, j + 1))
    faces.append(tuple(range(m)))            # top surface (was open!)
    faces.append(tuple(range(m, 2 * m)))     # bottom surface (was open!)
    # gurney flap
    faces.append((m + 1, 2 * m + 1, 2 * m + 2, m + 2))
    plane = mesh_from("gt3_wing", verts, faces, MAT["carbon_weave_gloss"])
    parts = [plane]
    # pylons: swan-neck blades — deck foot, rise, over-curve, and down onto the
    # plane's top (4-point profile so the neck reads, not a stick)
    for side, tag in ((-0.30, "l"), (0.30, "r")):
        pts = [(side - 0.09, 1.46, 0.775), (side - 0.09, 1.66, 0.94),
               (side - 0.09, 1.84, plane_z + 0.06),
               (side - 0.09, 1.92, plane_z + 0.012),
               (side + 0.09, 1.46, 0.775),
               (side + 0.09, 1.66, 0.94),
               (side + 0.09, 1.84, plane_z + 0.06),
               (side + 0.09, 1.92, plane_z + 0.012)]
        verts2, faces2 = [], []
        verts2.extend(pts)
        n2 = 4
        for i in range(n2 - 1):
            faces2.append((i, i + 1, n2 + i + 1, n2 + i))
        faces2.append((0, n2 - 1, 2 * n2 - 1, n2))
        faces2.append(tuple(range(n2, 2 * n2)))
        py_ = mesh_from("gt3_wing_pylon_" + tag, verts2, faces2,
                MAT["carbon_weave_gloss"])
        parts.append(py_)
    # endplates: red swept slabs at the plane tips — tapered bottom-rear
    # (the plain rectangle read as a floating plaque in clay renders)
    for side, tag in ((-span / 2, "l"), (span / 2, "r")):
        x0 = side - (0.012 if side < 0 else -0.012)
        x1 = x0 + 0.024
        prof = [(cy - 0.16, plane_z - 0.10), (cy + 0.06, plane_z - 0.13),
        (cy + 0.22, plane_z - 0.05), (cy + 0.22, plane_z + 0.06),
        (cy + 0.02, plane_z + 0.11), (cy - 0.16, plane_z + 0.12)]
        v10 = [(x0, py, pz) for py, pz in prof] + \
              [(x1, py, pz) for py, pz in prof]
        np_ = len(prof)
        fes = [(j, j + 1, np_ + j + 1, np_ + j) for j in range(np_ - 1)]
        fes.append(tuple(range(np_)))                       # front cap ngon
        fes.append(tuple(range(np_, 2 * np_)))              # rear cap ngon
        ep = mesh_from("gt3_wing_endplate_" + tag, v10, fes,
               pbr("gt3_endplate_red", (0.55, 0.03, 0.03), 0.0, 0.35))
        parts.append(ep)
    return parts


def build_splitter():
    """Full-width carbon splitter, protrudes ahead of the bumper, red edge,
    plus a body-color lower lip band tying it into the nose (kills the
    'detached plane' read). Lip node is token-clean (no bumper_f/_r match)."""
    n = SPEC["nose"]
    y0 = n - 0.14
    y1 = n + 0.10
    w0 = halfwidth(n) + 0.03
    # AXIS CONVENTION (coder's red-plane diagnosis, 2026-11-25): the gt3
    # builder convention is (x=width, y=length, z=height) — these two parts
    # had their tuples written (length, width, height) on (X, Y, Z), so the
    # glTF Yup conversion exported them sideways (a 2.4m red plane off the
    # flank). Swapped to width/length/height like every other part.
    verts = [(-w0, y0, 0.072), (w0, y0, 0.072), (w0 * 0.92, y1, 0.068),
             (-w0 * 0.92, y1, 0.068), (w0 * 0.92, y1, 0.048), (-w0 * 0.92, y1, 0.048),
             (w0, y0, 0.062), (-w0, y0, 0.062)]
    faces = [(0, 1, 2, 3), (7, 6, 4, 5), (0, 3, 5, 7), (1, 0, 7, 6), (2, 1, 6, 4)]
    out = [mesh_from("gt3_splitter", verts, faces, MAT["carbon_weave_gloss"])]
    # lower lip band: wraps the nose bottom, leading edge shares the
    # splitter's (no step notch at the join)
    ly0, ly1 = n - 0.14, n + 0.55
    lw = halfwidth(ly1) + 0.01
    out.append(mesh_from("gt3_bumperlip", [
        (-lw, ly0, 0.040), (lw, ly0, 0.040), (lw, ly0, 0.075), (-lw, ly0, 0.075),
        (-lw, ly1, 0.040), (lw, ly1, 0.040), (lw, ly1, 0.078), (-lw, ly1, 0.078)],
        [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
         (2, 3, 7, 6), (3, 0, 4, 7)], MAT["paint_gt3"]))
    return out


def build_tail():
    """Rear fascia panel with the quad red-ring taillights EMBEDDED
    (lights_r -> auto emissive) + center rain light. Rings: cylindrical
    housings, pair per side, at the tail panel's top edge."""
    parts = []
    # tail fascia: PROUD of the hull's end cap (y 2.275) — the first version
    # sat at 2.245 and the loft's end cap occluded panel/band/inner rings
    # entirely (only the outer pair peeked past the cap flanks). Fascia at
    # 2.282, band 2.286, rings 2.289/2.275; quad layout pulled inward so all
    # four rings sit on the dark band (emissive contrast on ANY body color).
    parts.append(mesh_from("gt3_tail_panel", [
        (-0.72, 2.282, 0.44), (0.72, 2.282, 0.44), (0.72, 2.282, 0.70),
        (-0.72, 2.282, 0.70)], [(0, 1, 2, 3)], MAT["paint_gt3"]))
    parts.append(mesh_from("gt3_tailband", [
        (-0.78, 2.286, 0.48), (0.78, 2.286, 0.48), (0.78, 2.286, 0.69),
        (-0.78, 2.286, 0.69)], [(0, 1, 2, 3)],
        pbr("gt3_tailband_dark", (0.015, 0.015, 0.018), 0.0, 0.85)))
    for side in (-1, 1):
        for k in (0, 1):
            cy = side * (0.32 + k * 0.26)
            cz = 0.60
            ring_v, ring_f = [], []
            seg = 20
            for j in range(seg):
                a = 2 * math.pi * j / seg
                ring_v.append((cy + 0.085 * math.cos(a), 2.289, cz + 0.085 * math.sin(a)))
            for j in range(seg):
                a = 2 * math.pi * j / seg
                ring_v.append((cy + 0.05 * math.cos(a), 2.275, cz + 0.05 * math.sin(a)))
            for j in range(seg):
                j2 = (j + 1) % seg
                ring_f.append((j, j2, seg + j2, seg + j))
            ring_f.append(tuple(range(seg)))
            ring_f.append(tuple(range(seg, 2 * seg)))
            parts.append(mesh_from("gt3_lights_r_tailring_%d%d" % (1 if side < 0 else 2, k + 1),
                           ring_v, ring_f, MAT["lights_r"]))
    # center rain light: vertical red strip on the crash structure
    parts.append(mesh_from("gt3_lights_r_rainlight", [
        (-0.025, 2.289, 0.50), (0.025, 2.289, 0.50), (0.025, 2.289, 0.34),
        (-0.025, 2.289, 0.34)], [(0, 1, 2, 3)], MAT["lights_r"]))
    return parts


def build_diffuser():
    """Full-width carbon diffuser: a VISIBLE upsweep wedge under the tail
    (the old flat plate was invisible edge-on, leaving a blank tail slab),
    5 strakes, deep rake."""
    verts = [(-0.94, 1.72, 0.075), (0.94, 1.72, 0.075), (0.94, 2.31, 0.34),
             (-0.94, 2.31, 0.34), (-0.94, 2.31, 0.06), (0.94, 2.31, 0.06)]
    faces = [(0, 1, 2, 3), (4, 5, 1, 0), (3, 2, 5, 4)]
    ob = mesh_from("gt3_diffuser", verts, faces, MAT["carbon_weave_gloss"])
    parts = [ob]
    for k in range(5):
        x = -0.75 + k * 0.375
        parts.append(mesh_from("gt3_diffuser_strake_%d" % k, [
            (x - 0.012, 1.74, 0.09), (x + 0.012, 1.74, 0.09),
            (x + 0.012, 2.26, 0.32), (x - 0.012, 2.26, 0.32)],
            [(0, 1, 2, 3)], MAT["carbon_weave_gloss"]))
    return parts


def build_lights_f():
    """Teardrop headlight clusters (lights_f material)."""
    parts = []
    for side in (-1, 1):
        verts = [(side * 0.52, -2.16, 0.52), (side * 0.78, -2.06, 0.56),
         (side * 0.86, -1.94, 0.54), (side * 0.60, -2.02, 0.46)]
        parts.append(mesh_from("gt3_lights_f_%d" % (1 if side < 0 else 2),
                       verts, [(0, 1, 2, 3)], MAT["lights_f"]))
    return parts


def tri_count(ob):
    me = ob.data
    me.calc_loop_triangles()
    return len(me.loop_triangles)


def build_deck_louvers():
    """Two recessed engine-deck louver panels behind the canopy (the node
    map's gt3_deck_louvers slot — non-eject, token-clean)."""
    parts = []
    for side in (-1, 1):
        x0, x1 = sorted((side * 0.18, side * 0.52))
        parts.append(mesh_from("gt3_deck_louvers_%d" % (1 if side < 0 else 2), [
            (x0, 0.55, 0.795), (x1, 0.55, 0.795), (x1, 1.05, 0.755),
            (x0, 1.05, 0.755), (x0, 0.55, 0.775), (x1, 0.55, 0.775),
            (x1, 1.05, 0.735), (x0, 1.05, 0.735)],
            [(0, 1, 2, 3), (7, 6, 5, 4), (0, 1, 5, 4), (1, 2, 6, 5),
             (2, 3, 7, 6), (3, 0, 4, 7)],
            pbr("gt3_louver_dark", (0.05, 0.05, 0.055), 0.0, 0.7)))
    return parts


def export_glb():
    """First GT3 glb export against the frozen node contract. Blender's glTF
    exporter converts Z-up->Y-up, which maps my length axis (Y) to glb -Z —
    the nose at -Y lands at +Z per the car-glb convention, no extra
    transform. Hub-local wheels keep their origins for the spin arrays."""
    out = os.path.join(ASSETS, "gt3.glb")
    sel = [ob for ob in bpy.data.objects
           if ob.type == "MESH" and ob.name.startswith("gt3_")
           and ob.name != "gt3_ground"]
    bpy.ops.object.select_all(action="DESELECT")
    for ob in sel:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = sel[0]
    bpy.ops.export_scene.gltf(filepath=out, export_format="GLB",
                      export_apply=True, export_yup=True,
                      use_selection=True)
    mats = sorted({s.name for ob in sel for s in ob.data.materials if s})
    report = {"file": "gt3.glb", "nodes": [o.name for o in sel],
              "tris": sum(tri_count(o) for o in sel), "materials": mats,
              "emissive_keys": [m for m in mats if m.startswith("lights_")],
              "paint_slot": "paint_gt3"}
    with open(os.path.join(ASSETS, "gt3_report.json"), "w") as f:
        json.dump(report, f, indent=1)
    print("GT3_GLB_OK", out, report["tris"], "tris", len(report["nodes"]), "nodes")
    print("GT3_GLB_MATS", json.dumps(mats))


def subtree(root):
    out = [root]
    for c in root.children:
        out.extend(subtree(c))
    return out


# ---------------- main ----------------
clear_scene()
body, glass, roof = build_body()
wheels = build_wheels()
wing = build_wing()
splitter = build_splitter()
tail = build_tail()
diffuser = build_diffuser()
lights_f = build_lights_f()

# ---------------- evidence: tri counts + turnaround shot ----------------
# scene walk (not the manual build list): catches hub caps, calipers and
# arch liners meshed inside the part builders — no part silently uncounted
all_obs = sorted([ob for ob in bpy.data.objects
          if ob.type == "MESH" and ob.name.startswith("gt3_")
          and ob.name != "gt3_ground"],
         key=lambda o: o.name)
total = sum(tri_count(o) for o in all_obs)
print("GT3_TRIS", json.dumps({"total": total,
      "per_part": {o.name: tri_count(o) for o in all_obs if tri_count(o) > 0}}))

scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
try:
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
except Exception:
    pass
# ground plane: stance/ride-height must be judgeable
mesh_from("gt3_ground", [(-8, -8, 0), (8, -8, 0), (8, 8, 0), (-8, 8, 0)],
          [(0, 1, 2, 3)], pbr("gt3_ground_gray", (0.30, 0.30, 0.31), 0.0, 0.85))
# 5-view sheet: side/front/rear/top + 3/4 hero (every review target gradeable)
VIEWS = [
    ("gt3_v_side", (9.0, 0.0, 0.72), (math.pi / 2, 0.0, math.pi / 2), 5.4, (1600, 500)),
    ("gt3_v_front", (0.0, -9.0, 0.72), (math.pi / 2, 0.0, 0.0), 3.4, (900, 620)),
    ("gt3_v_rear", (0.0, 9.0, 0.72), (math.pi / 2, 0.0, math.pi), 3.4, (900, 620)),
    ("gt3_v_top", (0.0, 0.0, 9.0), (0.0, 0.0, 0.0), 5.6, (900, 900)),
    # arch close-ups (pm-s9 ask: prove cut-vs-swallowed at readable scale)
    ("gt3_v_arch_f", (9.0, -1.30, 0.40), (math.pi / 2, 0.0, math.pi / 2), 1.7, (700, 700)),
    ("gt3_v_arch_r", (9.0, 1.30, 0.40), (math.pi / 2, 0.0, math.pi / 2), 1.7, (700, 700)),
]
for vname, loc, rot, scale, res in VIEWS:
    cd = bpy.data.cameras.new(vname)
    cd.type = "ORTHO"
    cd.ortho_scale = scale
    cam = bpy.data.objects.new(vname, cd)
    scene.collection.objects.link(cam)
    cam.location = loc
    cam.rotation_euler = rot
    scene.camera = cam
    scene.render.resolution_x, scene.render.resolution_y = res
    scene.render.filepath = os.path.join(SHOTS, vname + ".png")
    bpy.ops.render.render(write_still=True)
    print("GT3_VIEW_OK", vname)
# wireframe overlay pass: same side + arch crops, edges over shading — the
# definitive cut-vs-interpenetration record
try:
    scene.display.shading.show_wire = True
    scene.display.shading.wire_color_type = "OBJECT"
except Exception:
    pass
for vname, loc, rot, scale, res in [
        ("gt3_v_side_wire", (9.0, 0.0, 0.72), (math.pi / 2, 0.0, math.pi / 2), 5.4, (1600, 500)),
        ("gt3_v_arch_f_wire", (9.0, -1.30, 0.40), (math.pi / 2, 0.0, math.pi / 2), 1.7, (700, 700)),
        ("gt3_v_arch_r_wire", (9.0, 1.30, 0.40), (math.pi / 2, 0.0, math.pi / 2), 1.7, (700, 700))]:
    cd = bpy.data.cameras.new(vname)
    cd.type = "ORTHO"
    cd.ortho_scale = scale
    cam = bpy.data.objects.new(vname, cd)
    scene.collection.objects.link(cam)
    cam.location = loc
    cam.rotation_euler = rot
    scene.camera = cam
    scene.render.resolution_x, scene.render.resolution_y = res
    scene.render.filepath = os.path.join(SHOTS, vname + ".png")
    bpy.ops.render.render(write_still=True)
    print("GT3_VIEW_OK", vname)
try:
    scene.display.shading.show_wire = False
except Exception:
    pass
cd = bpy.data.cameras.new("gt3_v_hero")
cd.lens = 50
cam = bpy.data.objects.new("gt3_v_hero", cd)
scene.collection.objects.link(cam)
cam.location = (-6.3, 6.6, 1.7)     # rear-3/4, whole car + margin
tgt = Vector((0.1, 0.2, 0.55))
cam.rotation_euler = (tgt - Vector(cam.location)).to_track_quat("-Z", "Y").to_euler()
scene.camera = cam
scene.render.resolution_x, scene.render.resolution_y = 1280, 850
scene.render.filepath = os.path.join(SHOTS, "gt3_v_hero.png")
bpy.ops.render.render(write_still=True)
print("GT3_VIEW_OK gt3_v_hero")
# first glb export (frozen node contract) + deck louvers
louvers = build_deck_louvers()
export_glb()
print("GT3_BUILD_DONE")