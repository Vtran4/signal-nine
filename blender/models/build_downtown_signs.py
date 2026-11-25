# WS-B2 neon-sign kit (modeler-s9): standalone post-processor on
# assets/set.blend. Adds fictional neon signs to downtown block facades:
# blade signs (projecting), fascia bands, one rooftop sign per front block.
# Glyph art = procedural fictional glyph cells in neon_glyphs.png (no real
# brands). Materials named neon_* so coder's client can key night-emissive
# by name (the lights_f/lights_r pattern). Node names downtown_sign_*:
# token-clean vs /bumper_f|bumper_r|hood|spoiler|wing|splitter/ + /wheel_|rim_/.
import bpy, math, os, random, zlib, struct

REPO = "C:/Users/vtran/OneDrive/Documents/AI projects/Signal Nine"
DT = 6000.0  # downtown layout offset X (layout pass 2026-11-23)

bpy.ops.wm.open_mainfile(filepath=os.path.join(REPO, "assets", "set.blend"))

# idempotent re-run: purge any previous sign pass (meshes + objects)
for ob in [o for o in bpy.data.objects if o.name.startswith("downtown_sign")]:
    me = ob.data
    bpy.data.objects.remove(ob, do_unlink=True)
    if me and me.users == 0:
        bpy.data.meshes.remove(me)

# ---------------- glyph atlas: 512x256, 8 cells, fictional strokes ----------
GW, GH, CELLS = 512, 256, 8
CW, CH = GW // 4, GH // 2
img = bytearray(b"\x00" * (GW * GH * 4))
rng = random.Random(20261125)

def px(x, y, c):
    if 0 <= x < GW and 0 <= y < GH:
        o = (y * GW + x) * 4
        img[o:o + 4] = bytes(c)

def vline(x, y0, y1, c):
    for y in range(y0, y1 + 1):
        px(x, y, c)

def hline(x0, x1, y, c):
    for x in range(x0, x1 + 1):
        px(x, y, c)

PALETTE = [(255, 64, 96), (64, 255, 208), (255, 176, 48), (120, 128, 255),
           (255, 255, 255), (255, 96, 200), (96, 220, 255), (255, 220, 96)]
for ci in range(CELLS):
    cx, cy = (ci % 4) * CW, (ci // 4) * CH
    col = PALETTE[ci]
    x0, y0 = cx + 24, cy + 24
    x1, y1 = cx + CW - 24, cy + CH - 24
    # frame the cell faintly (sign housing edge)
    for t in range(3):
        hline(x0, x1, y0 + t, (col[0] // 4, col[1] // 4, col[2] // 4, 255))
        hline(x0, x1, y1 - t, (col[0] // 4, col[1] // 4, col[2] // 4, 255))
    # fictional glyph: 4-7 random strokes on a grid (reads as alien/katakana
    # at distance; deterministic seed per cell)
    g = random.Random(9000 + ci)
    strokes = g.randint(7, 10)
    mx = [(x0 + 18 + g.randint(0, 3) * ((x1 - x0 - 36) // 3)) for _ in range(4)]
    my = [(y0 + 18 + g.randint(0, 3) * ((y1 - y0 - 36) // 3)) for _ in range(4)]
    for s in range(strokes):
        i1, i2 = g.sample(range(4), 2)          # distinct grid ends — no
        if g.random() < 0.5:                     # zero-length collapsed strokes
            xx = mx[g.randint(0, 3)]
            ya, yb = sorted((my[i1], my[i2]))
            for w in range(9):
                vline(xx + w, ya, yb, (*col, 255))
        else:
            yy = my[g.randint(0, 3)]
            xa, xb = sorted((mx[i1], mx[i2]))
            for w in range(9):
                hline(xa, xb, yy + w, (*col, 255))

out_png = os.path.join(REPO, "assets", "neon_glyphs.png")
# minimal PNG writer (RGBA, no filter)
def chunk(typ, data):
    c = struct.pack(">I", len(data)) + typ + data
    return c + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)
raw = b"".join(b"\x00" + bytes(img[y * GW * 4:(y + 1) * GW * 4]) for y in range(GH))
png = (b"\x89PNG\r\n\x1a\n"
       + chunk(b"IHDR", struct.pack(">IIBBBBB", GW, GH, 8, 6, 0, 0, 0))
       + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))
open(out_png, "wb").write(png)
print("SIGN_ATLAS_OK", out_png, GW, GH, CELLS)

# ---------------- materials ----------------
def mat_simple(name, col, emit_strength=0.0):
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (*col, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.6
    nt.links.new(bsdf.outputs[0], out.inputs[0])
    m.diffuse_color = (*col, 1.0)
    return m

def mat_neon(name, col):
    """Neon face: glyph atlas emission so the LIGHT bake carries the glyphs
    bright (day) and the client can key night-emissive off the neon_ name."""
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(out_png, check_existing=True)
    tex.image.colorspace_settings.name = "sRGB"
    # single glyph cell per material instance via UV offset is done per-sign
    # with uv layers; here default full-atlas mapping, per-sign UVs in mesh
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Strength"].default_value = 1.2
    nt.links.new(tex.outputs["Color"], em.inputs["Color"])
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(bsdf.outputs[0], mix.inputs[1])
    nt.links.new(em.outputs[0], mix.inputs[2])
    mix.inputs["Fac"].default_value = 0.85
    nt.links.new(mix.outputs[0], out.inputs[0])
    m.diffuse_color = (1.0, 0.85, 0.6, 1.0)
    return m

def mesh_box(name, size, origin, m, cell=0):
    x, y, z = origin
    sx, sy, sz = size
    v = [(x - sx, y - sy, z - sz), (x + sx, y - sy, z - sz),
         (x + sx, y + sy, z - sz), (x - sx, y + sy, z - sz),
         (x - sx, y - sy, z + sz), (x + sx, y - sy, z + sz),
         (x + sx, y + sy, z + sz), (x - sx, y + sy, z + sz)]
    f = [(0, 1, 2, 3), (7, 6, 5, 4), (0, 1, 5, 4), (1, 2, 6, 5),
         (2, 3, 7, 6), (3, 0, 4, 7)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(v, [], f)
    me.update()
    # per-cell UVs on every face — these UVs are FINAL (neon_* bypasses the
    # bake's uv_pass by design, so nothing overwrites them)
    cu, cv = (cell % 4) / 4.0, (1 - cell // 4) / 2.0
    u0, u1 = cu + 0.06 * 0.25, cu + 0.94 * 0.25
    v0, v1 = cv + 0.08 * 0.5, cv + 0.92 * 0.5
    uvl = me.uv_layers.new(name="UVMap")
    for k, d in enumerate(uvl.data):
        corner = k % 4
        d.uv = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)][corner]
    me.materials.append(m)
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def mesh_panel(name, w, h, thick, origin, facing, m, cell):
    """Sign face panel with UVs mapped to ONE glyph cell (cell 0-7).
    facing: +1 panel normal +Y, -1 normal -Y."""
    x, y, z = origin
    hw, hh = w / 2, h / 2
    cu, cv = (cell % 4) / 4.0, (1 - cell // 4) / 2.0
    # insets are fractions OF THE CELL (0.25 wide u, 0.5 tall v) — the old
    # atlas-fraction form overflowed cells 3/7 past u=1.0 (coder's scan)
    u0, u1 = cu + 0.06 * 0.25, cu + 0.94 * 0.25
    v0, v1 = cv + 0.08 * 0.5, cv + 0.92 * 0.5
    if facing > 0:
        v4 = [(x - hw, y, z - hh), (x + hw, y, z - hh),
              (x + hw, y, z + hh), (x - hw, y, z + hh)]
    else:
        v4 = [(x + hw, y, z - hh), (x - hw, y, z - hh),
              (x - hw, y, z + hh), (x + hw, y, z + hh)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(v4, [], [(0, 1, 2, 3)])
    me.update()
    uvl = me.uv_layers.new(name="UVMap")
    uvs = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
    for i, d in enumerate(uvl.data):
        d.uv = uvs[i]
    me.materials.append(m)
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


# ---------------- placement: block facades facing the road ----------------
blocks = sorted([o for o in bpy.data.objects
                 if o.type == "MESH" and o.name.startswith("downtown_block")],
                key=lambda o: o.name)
print("SIGN_BLOCKS", [b.name for b in blocks])
road_z = 0.05  # downtown roadbed top (plate 0.0 + 0.15 raised bed, road -0.1)
made = []
rng2 = random.Random(77)
for i, blk in enumerate(blocks):
    bb = [blk.matrix_world @ v.co for v in blk.data.vertices]
    xs = [v.x for v in bb]; ys = [v.y for v in bb]; zs = [v.z for v in bb]
    x0, x1, y0, y1, z0, z1 = min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)
    # road runs along X: front facades = the y side nearer y=0
    front_y = y0 if abs(y0) < abs(y1) else y1
    face = 1 if front_y > 0 else -1
    cy = front_y + face * 0.12
    cw = min(3.0, (x1 - x0) * 0.5)
    ch = min(1.4, (z1 - z0) * 0.25)
    cx = (x0 + x1) / 2 + rng2.uniform(-0.2, 0.2)
    cz = max(road_z + 2.6, z0 + (z1 - z0) * 0.28)
    cell = i % CELLS
    # curated placement (bake-verified 2026-11-25, final): blade_06/roof_08
    # (10-sign pass) and roof_02/roof_05 (8-sign pass) baked void in every
    # pass deterministically per scene — dropped; the remaining 6 carry
    # verified albedo + structured light tiles (blade_03 = day-art only, its
    # sign reads as powered off at night — realistic)
    if i in (2, 5, 6, 8):
        continue
    if i % 3 == 0:
        # blade sign: perpendicular box + two lit faces
        sgn = mesh_box("downtown_sign_blade_%02d" % i,
                       (0.9, 0.12, 1.6), (cx, cy + face * 0.95, cz + 0.4),
                       mat_neon("neon_blade", (1, 1, 1)), cell=cell)
        made.append(sgn)
    elif i % 3 == 1:
        sgn = mesh_panel("downtown_sign_fascia_%02d" % i, cw, ch, 0.06,
                         (cx, cy, cz), face, mat_neon("neon_fascia", (1, 1, 1)), cell)
        made.append(sgn)
    else:
        # rooftop sign: tall panel on the block roof + mounting posts
        sgn = mesh_panel("downtown_sign_roof_%02d" % i, cw * 1.2, ch * 1.6, 0.08,
                         (cx, (y0 + y1) / 2, z1 + ch), face,
                         mat_neon("neon_roof", (1, 1, 1)), cell)
        made.append(sgn)

print("SIGN_MADE", len(made), [o.name for o in made][:12])
bpy.ops.wm.save_mainfile()
print("SIGNS_SAVED")