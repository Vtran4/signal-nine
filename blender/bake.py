# Signal Nine — Cycles atlas bake (port of the proven Cork Gallery pipeline)
# Usage:
#   blender -b assets/set.blend -P blender/bake.py -- --export-only   (re-UV + glb, no bake)
#   blender -b assets/set.blend -P blender/bake.py -- --test          (512px probe)
#   blender -b assets/set.blend -P blender/bake.py -- --full          (production + pano)
# Contract: bake.py EMITS manifest.json (group prefix -> atlas, node lists).
# Groups by name prefix: coastal_*/downtown_* -> layer atlases, props_* -> props atlas.
# LOD variants (_lod1/_lod2) get their own tile in the SAME atlas -> LOD swap stays
# material-neutral (single texture pair per layer) without identical-UV welding.
# Settings mirrored from Cork: Standard view transform (un-tonemapped), adaptive
# sampling off, max_bounces 4, sample_clamp_indirect 2.0, denoising off,
# OPTIX/CUDA GPU w/ CPU fallback, verify every baked image before saving.
import bpy
import sys
import os
import math

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
ASSETS = os.path.join(ROOT, "assets")
os.makedirs(ASSETS, exist_ok=True)

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
MODE = argv[0] if argv else "--test"
ENV_NAME = next((a.split("=", 1)[1] for a in argv if a.startswith("--env=")), None)
# WS-B3 golden-hour panos: --pano-time=goldenhour renders the pano camera
# under a warm low-sun rig variant and writes a SUFFIXED env asset
# (env_coast_goldenhour.jpg) — the certified daytime env_coast.jpg is never
# touched. Set-pieces per Coder's rig slots (night waits on WS-B2 content).
PANO_TIME = next((a.split("=", 1)[1] for a in argv if a.startswith("--pano-time=")), None)
# WS-B3 golden-hour LIGHTMAP round (pm's fired branch, 2026-11-25): --warm
# bakes each group's LIGHT pass under the graded golden-hour rig (qwantani
# dome at reduced strength + a warm 2500K low sun) and writes SUFFIXED
# atlases (light_<g>_golden.png) + a side-car manifest_golden.json. The
# mode-side-effect contract: --warm must NOT touch the certified
# light_<g>.png files, manifest.json, tracks.glb, the blend, or any UV
# assignment (the statics are env-agnostic baked light; the golden-hour
# set is a VARIANT the ?env= consumer selects, exactly like the env panos).
WARM = "--warm" in argv
WARM_HDRI = "qwantani_sunset_puresky_4k.hdr"   # the graded A/B dome (615dbe2)
WARM_STRENGTH = 0.22                            # the A/B graded rig value
WARM_SUN_RGB = (1.0, 0.62, 0.28)                # 2500K
WARM_SUN_ENERGY = 1.8                           # the A/B lamp energy
GROUPS = {"coastal": 2048, "downtown": 2048, "props": 1024, "canyon": 2048}
TEST_RES_SCALE = {"coastal": 512, "downtown": 512, "props": 512, "canyon": 512}
SAMPLES = {"--test": 64, "--full": 384}
MARGIN = {"--test": 4, "--full": 8}
# Bake-rig fill lighting (2026-11-23 sun-only-bake defect fix): every --full
# bake to date ran with ZERO ambient — shadowed texels collapsed to 0/1.0
# (downtown road 96.8% dark, props_dt_* 97.6% black) while the env pano
# rendered minutes later WITH ambient in the same run. Cork's proven rig
# carries explicit sky-fill lamps; this port dropped them and trusted the
# HDRI world, which bpy.ops.object.bake does not reliably sample. The fill
# sun is insurance; verify_env_image + the AMBIENT_GATE are the alarms.
FILL_ENERGY = 0.5
WORLD_STRENGTH = 0.2  # calibrated 2026-11-23: MULTIPLE_SCATTERING sky at 1.0
                      # saturated downtown 98%; sky-only plate measured 0.665
                      # at strength 0.35 -> 0.2 lands shadow interiors mid-band
FILL_ANGLE_DEG = 80
UV_INSET_TEXELS = 12  # post-repair: shelf-pack tiles abut, and the 8px bake
                      # margin dilates each island into its neighbor's edge
                      # band. pm's texel scans measured 6-7 texels of bleed
                      # (ocean blue into the road island's final rows); 4 was
                      # inside the blue, 12 clears the 8px worst case with
                      # margin. Acceptance: road v1-edge B-R < 15 at every u.
FILL_DIR = (0.35, 0.0, -0.82)  # blender-space travel: from the west sky, downward
scene = bpy.context.scene

# ---------------- engine ----------------
def verify_env_image(img):
    """Force-load env pixels and verify real radiance. Background-mode bakes do
    NOT reliably trigger Blender's lazy image load — an unloaded env samples
    BLACK and the whole bake runs sun-only. Explicit --env failures raise."""
    _ = img.pixels[0]  # touch forces the lazy pixel load
    if img.size[0] == 0:
        raise RuntimeError("ENV_VERIFY_FAIL: %s has no pixels" % img.name)
    mean, mx = image_stats(img)
    if mean < 0.02 or mx < 0.5:
        raise RuntimeError("ENV_VERIFY_FAIL: %s mean=%.4f max=%.4f - sky reads black"
                           % (img.name, mean, mx))
    print("ENV_VERIFY_OK: %s mean=%.4f max=%.4f" % (img.name, mean, mx))


def set_world_env(hdr_path):
    """CC0-policy HDRI in the bake rig: HDRI = ambient/sky env; the sun lamp
    stays for sharp directional shadows."""
    world = scene.world
    nt = world.node_tree
    bg = nt.nodes.get("Background")
    img = bpy.data.images.load(hdr_path, check_existing=True)
    img.colorspace_settings.name = "Non-Color"
    for n in list(nt.nodes):
        if n.type == "TEX_SKY":
            nt.nodes.remove(n)
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    env.image = img
    nt.links.new(env.outputs[0], bg.inputs[0])
    bg.inputs[1].default_value = 1.0
    verify_env_image(img)
    print("WORLD_ENV:", os.path.basename(hdr_path))


def set_warm_rig():
    """--warm golden-hour bake rig (the graded A/B values): qwantani dome at
    reduced strength + every sun retinted 2500K and dropped low. Filmic is
    NOT set here — bake passes write linear data; view transforms are a
    render-camera concern only."""
    env_path = os.path.join(ASSETS, "hdri", WARM_HDRI)
    if not os.path.isfile(env_path):
        raise RuntimeError("WARM_RIG_FAIL: missing %s" % env_path)
    set_world_env(env_path)
    nt = scene.world.node_tree
    bg = nt.nodes.get("Background")
    bg.inputs[1].default_value = WARM_STRENGTH
    print("WARM_RIG: dome strength %.2f" % WARM_STRENGTH)
    n_sun = 0
    for o in scene.objects:
        if o.type == "LIGHT" and o.data.type == "SUN":
            o.data.color = WARM_SUN_RGB
            o.data.energy = WARM_SUN_ENERGY
            o.rotation_euler = (math.radians(78), 0.0, math.radians(250))
            n_sun += 1
    print("WARM_RIG: %d sun(s) retinted 2500K, low-angle" % n_sun)


def bake_group_light_only(g, objs, res, samples, margin):
    """--warm pass: the LIGHT bake ONLY, on the blend's EXISTING atlas UVs
    (no uv_pass re-assignment — the certified rects stay authoritative),
    saved as light_<g>_golden.png. No albedo pass (albedo is env-neutral
    by contract)."""
    import time
    t0 = time.time()
    light = fresh_image("light_" + g + "_golden", res, linear=True)
    saved = {ob.name: [m for m in ob.data.materials if m] for ob in objs}
    lo = white_override(g, light)
    for ob in objs:
        keep = light_material_for(saved[ob.name], g, light)
        ob.data.materials.clear()
        ob.data.materials.append(keep)
    full = [o for o in objs if not (o.name.endswith("_lod1") or o.name.endswith("_lod2"))]
    lods = [o for o in objs if o not in full]
    for stage, hidden in ((full, lods), (lods, full)):
        if not stage:
            continue
        for ob in hidden:
            ob.hide_render = True
        bpy.ops.object.select_all(action="DESELECT")
        for ob in stage:
            ob.select_set(True)
        bpy.context.view_layer.objects.active = stage[0]
        bpy.ops.object.bake(type="DIFFUSE", pass_filter={"DIRECT", "INDIRECT"},
                            use_clear=False, margin=margin)
        for ob in hidden:
            ob.hide_render = False
    lmean, lmax = image_stats(light)
    mid_frac = light_gate(light)
    for ob in objs:
        ob.data.materials.clear()
        for m in saved[ob.name]:
            ob.data.materials.append(m)
    ok_l = lmax > 0.0005
    if ok_l:
        save_png(light)
    print("WARM_GROUP %s res=%d objs=%d time=%.1fs light mean=%.4f max=%.4f %s "
          "ambient_mid=%.4f" % (g, res, len(objs), time.time() - t0, lmean,
                                lmax, "VERIFY_OK" if ok_l else "VERIFY_FAIL",
                                mid_frac))
    return {"group": g, "light": "light_%s_golden.png" % g if ok_l else None,
            "ambient_mid": round(mid_frac, 4)}


def ensure_world_env():
    if scene.world is None:
        scene.world = bpy.data.worlds.new("bake_world")
        scene.world.use_nodes = True
    nt = scene.world.node_tree
    bg = nt.nodes.get("Background")

    def wire_sky():
        sky = nt.nodes.new("ShaderNodeTexSky")
        for candidate in ("NISHITA", "MULTIPLE_SCATTERING", "SINGLE_SCATTERING",
                          "PREETHAM", "HOSEK_WILKIE"):
            try:
                sky.sky_type = candidate
                break
            except Exception:
                continue
        nt.links.new(sky.outputs[0], bg.inputs[0])
        print("WORLD_RIG: procedural sky wired")

    for n in nt.nodes:
        if n.type == "TEX_ENVIRONMENT" and n.image:
            try:
                verify_env_image(n.image)
                print("WORLD_RIG: env verified")
            except RuntimeError as exc:
                print("ENV_FALLBACK_NISHITA:", exc)
                img = n.image
                nt.nodes.remove(n)
                bpy.data.images.remove(img, do_unlink=True)
                wire_sky()
            if bg is not None:
                bg.inputs[1].default_value = WORLD_STRENGTH
                print("WORLD_RIG: strength scaled to %.2f" % WORLD_STRENGTH)
            return
    if bg is not None and not bg.inputs[0].is_linked:
        locked = os.path.join(ASSETS, "hdri", "kloofendal_48d_partly_cloudy_puresky.hdr")
        if os.path.isfile(locked):
            img = bpy.data.images.load(locked, check_existing=True)
            img.colorspace_settings.name = "Non-Color"
            env = nt.nodes.new("ShaderNodeTexEnvironment")
            env.image = img
            nt.links.new(env.outputs[0], bg.inputs[0])
            verify_env_image(img)
            bg.inputs[1].default_value = WORLD_STRENGTH
            print("WORLD_RIG: locked HDRI wired over an unlinked Background, "
                  "strength %.2f" % WORLD_STRENGTH)
            return
        raise RuntimeError("WORLD_RIG_FAIL: Background.Color unlinked and no "
                           "locked HDRI at assets/hdri/ - refusing a flat-grey bake")
    if bg is not None and bg.inputs[0].is_linked:
        bg.inputs[1].default_value = WORLD_STRENGTH
        print("WORLD_RIG: ok (Background linked), strength %.2f" % WORLD_STRENGTH)

def setup_engine(samples):
    scene.render.engine = "CYCLES"
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for dev in ("OPTIX", "CUDA"):
            try:
                prefs.compute_device_type = dev
                prefs.get_devices()
                scene.cycles.device = "GPU"
                print("BAKE_DEVICE:", dev)
                break
            except Exception:
                continue
    except Exception:
        scene.cycles.device = "CPU"
        print("BAKE_DEVICE: CPU")
    scene.cycles.samples = samples
    scene.cycles.use_adaptive_sampling = False
    scene.cycles.max_bounces = 4
    scene.cycles.sample_clamp_indirect = 2.0
    scene.cycles.use_denoising = False
    scene.view_settings.view_transform = "Standard"  # un-tonemapped bakes
    scene.render.image_settings.file_format = "PNG"


def add_fill_rig():
    """Cork-style explicit sky-fill: one soft wide-angle sun opposing the key
    sun. Guarantees downwelling ambient in baked light even if the HDRI env
    fails to contribute. Idempotent; __bake_fill never ships as content."""
    if bpy.data.objects.get("__bake_fill"):
        return
    from mathutils import Vector
    d = bpy.data.lights.new("__bake_fill", type="SUN")
    d.energy = FILL_ENERGY
    d.angle = math.radians(FILL_ANGLE_DEG)
    ob = bpy.data.objects.new("__bake_fill", d)
    scene.collection.objects.link(ob)
    ob.rotation_euler = Vector(FILL_DIR).normalized().to_track_quat("-Z", "Y").to_euler()
    print("FILL_RIG: energy=%.2f angle=%ddeg dir=%s" % (FILL_ENERGY, FILL_ANGLE_DEG, FILL_DIR))

# ---------------- helpers ----------------
def group_of(name):
    pre = name.split("_")[0]
    return pre if pre in GROUPS else None

def collect_groups():
    groups = {}
    for ob in scene.objects:
        if ob.type != "MESH" or ob.name.startswith("__bake"):
            continue
        # neon_* self-textured emissive devices (WS-B2 sign kit) are EXCLUDED
        # from the baked-atlas pipeline: their glyph texture + emission ride
        # the GLB as the client's emissive asset (neonI rig scales
        # emissiveIntensity). Baking them into shelf tiles produced
        # position-cursed void tiles (7 bakes of evidence) for zero benefit —
        # the device carries its own content by design.
        if any(m and m.name.startswith("neon_") for m in ob.data.materials if m):
            print("NEON_BYPASS", ob.name)
            continue
        g = group_of(ob.name)
        if g:
            groups.setdefault(g, []).append(ob)
    for g in groups:
        groups[g].sort(key=lambda o: o.name)
    return groups

def area_of(ob):
    ob.data.calc_loop_triangles()
    return sum(p.area for p in ob.data.polygons) or 1e-6

def uv_bbox(ob):
    uv = ob.data.uv_layers.active
    if not uv:
        return (0.0, 0.0, 1.0, 1.0)
    us, vs = [], []
    for d in uv.data:
        us.append(d.uv[0])
        vs.append(d.uv[1])
    return (min(us), min(vs), max(us), max(vs))

def smart_unwrap(ob):
    """Headless unwrap for objects without usable UVs."""
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    try:
        bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.01)
    except Exception as exc:
        print("UNWRAP_FALLBACK", ob.name, exc)
        try:
            bpy.ops.uv.cube_project(cube_size=1.0)
        except Exception:
            pass
    bpy.ops.object.mode_set(mode="OBJECT")
    return uv_bbox(ob)

def shelf_pack(entries):
    """entries: [(key, side)] square tile sides in UV units; returns key -> rect."""
    total = sum(a * a for _, a in entries)
    scale = 1.0
    for _ in range(10):
        x = y = row_h = 0.0
        place, ok = {}, True
        for key, side in sorted(entries, key=lambda e: -e[1]):
            s = max(0.03, side * scale)
            if x + s > 1.0 + 1e-6:
                x = 0.0
                y += row_h
                row_h = 0.0
            if y + s > 1.0 + 1e-6:
                ok = False
                break
            place[key] = (x, y, x + s, y + s)
            x += s
            row_h = max(row_h, s)
        if ok and y + row_h <= 1.0 + 1e-6:
            return place
        scale *= 0.85
    raise RuntimeError("shelf_pack overflow for " + str(entries))

def assign_tile_uvs(ob, rect, bbox, inset_uv=0.0):
    """Fit the mesh's UV bbox to its atlas tile INDEPENDENTLY PER AXIS.
    The old aspect-preserving min-scale crushed the U axis of ribbons whose
    source v-range is in world meters (roads emit 1 x ~184 -> 0.0006-wide
    hairline islands; 40 meshes affected — the "black-crushed road"). Per-axis
    stretch fills the tile instead: maximum texel density on both axes, and
    the builder's lane-aligned road u (0=left edge .. 1=right edge) survives
    so the grading wear-bands map correctly.

    inset_uv shrinks the target rect by that many UV units per edge BEFORE
    mapping (UV_INSET_TEXELS / atlas_res): shelf-pack tiles abut, and the bake
    margin dilates each island into its neighbor's edge band — without the
    inset the client samples the contaminated rim (ocean blue on the road's
    outer edge). Skipped for degenerate-tiny tiles."""
    u0, v0, u1, v1 = rect
    u0i, v0i = u0 + inset_uv, v0 + inset_uv
    u1i, v1i = u1 - inset_uv, v1 - inset_uv
    if u1i > u0i and v1i > v0i:
        u0, v0, u1, v1 = u0i, v0i, u1i, v1i
    bu0, bv0, bu1, bv1 = bbox
    bw = max(1e-9, bu1 - bu0)
    bh = max(1e-9, bv1 - bv0)
    su = (u1 - u0) / bw
    sv = (v1 - v0) / bh
    uv = ob.data.uv_layers.active
    for d in uv.data:
        d.uv = (u0 + (d.uv[0] - bu0) * su, v0 + (d.uv[1] - bv0) * sv)

def fresh_image(name, res, linear):
    old = bpy.data.images.get(name)
    if old:
        bpy.data.images.remove(old, do_unlink=True)
    img = bpy.data.images.new(name, res, res, alpha=False)
    if linear:
        img.colorspace_settings.name = "Non-Color"
    return img

def ensure_img_node(mat, img):
    mat.use_nodes = True
    nt = mat.node_tree
    for n in nt.nodes:
        n.select = False
    tex = None
    for n in nt.nodes:
        if n.type == "TEX_IMAGE" and n.image and n.image.name == img.name:
            tex = n
            break
    if tex is None:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
    tex.select = True
    nt.nodes.active = tex
    return tex

def white_override(g, img):
    name = "__bake_light_" + g
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        b = m.node_tree.nodes.get("Principled BSDF")
        b.inputs["Base Color"].default_value = (1.0, 1.0, 1.0, 1.0)
        b.inputs["Roughness"].default_value = 1.0
        b.inputs["Metallic"].default_value = 0.0
    ensure_img_node(m, img)
    return m

def light_material_for(orig_mats, g, img):
    """Emissive statics (neon_* — the WS-B2 sign kit) keep their OWN material
    in the light pass: the override would wipe their Emission node, and the
    baked glyph structure in the light atlas IS the client's emissiveMap
    asset (neonI consumer). Everything else gets the flat white override so
    the bake measures pure incident light. NOTE: check the SAVED original
    materials — the caller clears ob.data.materials before applying."""
    for mat in orig_mats:
        if mat and mat.name.startswith("neon_"):
            ensure_img_node(mat, img)
            return mat
    return white_override(g, img)

def image_stats(img, stride=997):
    import array
    n = img.size[0] * img.size[1] * img.channels
    buf = array.array("f", bytes(4 * n))
    img.pixels.foreach_get(buf)
    mx, tot, cnt = 0.0, 0.0, 0
    for i in range(0, n, stride):
        v = buf[i]
        tot += v
        cnt += 1
        if v > mx:
            mx = v
    return (tot / max(1, cnt), mx)

def save_png(img):
    img.filepath_raw = os.path.join(ASSETS, img.name + ".png")
    img.file_format = "PNG"
    img.save()


def light_gate(img):
    """Ambient-floor gate on a freshly baked light atlas. R-channel stride-16
    samples (stride % 4 == 0 lands every sample on the R channel — avoids the
    documented alpha-inflated stride-997 means). Defect signature this catches:
    sun-only bakes collapse lit texels to 0/1.0 (bimodal, no mid-tones) because
    no ambient reached shadowed surfaces. Fails the run loudly instead of
    shipping black-crushed shadows."""
    import array
    n = img.size[0] * img.size[1] * img.channels
    buf = array.array("f", bytes(4 * n))
    img.pixels.foreach_get(buf)
    lit = mid = 0
    b0 = b1 = b2 = b3 = 0
    for i in range(0, n, 16):
        v = buf[i]
        if v <= 0.02:
            continue
        lit += 1
        if v <= 0.92:
            mid += 1
        b8 = min(255, int(v * 255.0 + 0.5))
        if b8 <= 2:
            b0 += 1
        elif b8 <= 59:
            b1 += 1
        elif b8 <= 200:
            b2 += 1
        else:
            b3 += 1
    if lit == 0:
        raise RuntimeError("AMBIENT_GATE_FAIL: light atlas entirely dark")
    mid_frac = mid / lit
    print("AMBIENT_GATE lit_frac=%.4f mid_frac=%.4f buckets8bit(0-2/3-59/60-200/201-255)="
          "%.3f/%.3f/%.3f/%.3f" % (lit / (n / 16.0), mid_frac,
                                   b0 / lit, b1 / lit, b2 / lit, b3 / lit))
    if mid_frac < 0.01:
        raise RuntimeError("AMBIENT_GATE_FAIL: mid_frac=%.4f < 0.01 - bimodal "
                           "0/255 light atlas, catastrophic bake failure" % mid_frac)
    return mid_frac

# ---------------- bake per group ----------------
def uv_pass(g, objs, res):
    entries = []
    infos = []
    total = sum(area_of(o) for o in objs)
    inset_uv = UV_INSET_TEXELS / float(res)
    for ob in objs:
        has_uv = ob.data.uv_layers.active is not None
        bbox = uv_bbox(ob) if has_uv else smart_unwrap(ob)
        # Degenerate-UV guard (2026-11-23): ribbon meshes whose source UVs
        # collapse on an axis (builders emit v in world meters, uv_pass's
        # aspect-fit then crushes u) map to hairline atlas islands — the sweep
        # found 40 (coastal_road + downtown_road + every guard + deckbar). A
        # hairline island bakes nothing and renders the whole surface from a
        # few texels (the "black-crushed road"). Re-unwrap instead of mapping
        # the collapse into a tile.
        if has_uv and (bbox[2] - bbox[0] < 1e-3 or bbox[3] - bbox[1] < 1e-3):
            print("UV_DEGENERATE_REUNWRAP", ob.name)
            bbox = smart_unwrap(ob)
        side = math.sqrt(area_of(ob) / total)
        infos.append((ob, bbox, inset_uv))
        entries.append((ob.name, side))
    tiles = shelf_pack(entries)
    for ob, bbox, inset_uv in infos:
        assign_tile_uvs(ob, tiles[ob.name], bbox, inset_uv)
    return tiles

def bake_group(g, objs, res, samples, margin):
    import time
    t0 = time.time()
    tiles = uv_pass(g, objs, res)
    # Margin clamp (2026-11-25, neon-sign round): bake margin dilates each
    # island OUTWARD into neighboring texels — with small shelf-packed tiles
    # (the 37px sign tiles) edge-to-edge, a 16px margin lets the LAST-baked
    # object's dilation paint over its neighbors, nondeterministically voiding
    # 2-3 tiles per run (the victims moved between identical runs). Clamp the
    # margin to ~1/5 of the smallest tile so dilation stays inside the tile.
    if tiles:
        min_side = min((r[2] - r[0]) * res for r in tiles.values())
        margin = max(2, min(margin, int(min_side * 0.2)))
        print("MARGIN_CLAMP %s -> %dpx (min tile %.1fpx)" % (g, margin, min_side))
    albedo = fresh_image("albedo_" + g, res, linear=False)
    light = fresh_image("light_" + g, res, linear=True)

    # ALBEDO pass — color only, no lighting
    for ob in objs:
        for mat in ob.data.materials:
            if mat:
                ensure_img_node(mat, albedo)
    bpy.ops.object.select_all(action="DESELECT")
    for ob in objs:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"},
                        use_clear=False, margin=margin)
    amean, amax = image_stats(albedo)

    # LIGHT pass — white override, direct+indirect, linear. LOD-staged (Defect
    # C): coincident _lod1/_lod2 twins self-shadow their full-res originals
    # (pole stem was 47% dark), so bake full-res with LODs render-hidden, then
    # the LOD tiles with full hidden — use_clear=False accumulates both into
    # the one atlas.
    saved = {ob.name: [m for m in ob.data.materials if m] for ob in objs}
    lo = white_override(g, light)
    for ob in objs:
        keep = light_material_for(saved[ob.name], g, light)
        ob.data.materials.clear()
        ob.data.materials.append(keep)
    full = [o for o in objs if not (o.name.endswith("_lod1") or o.name.endswith("_lod2"))]
    lods = [o for o in objs if o not in full]
    for stage, hidden in ((full, lods), (lods, full)):
        if not stage:
            continue
        for ob in hidden:
            ob.hide_render = True
        bpy.ops.object.select_all(action="DESELECT")
        for ob in stage:
            ob.select_set(True)
        bpy.context.view_layer.objects.active = stage[0]
        bpy.ops.object.bake(type="DIFFUSE", pass_filter={"DIRECT", "INDIRECT"},
                            use_clear=False, margin=margin)
        for ob in hidden:
            ob.hide_render = False
    print("LIGHT_STAGES %s full=%d lods=%d" % (g, len(full), len(lods)))
    lmean, lmax = image_stats(light)
    mid_frac = light_gate(light)
    for ob in objs:
        ob.data.materials.clear()
        for m in saved[ob.name]:
            ob.data.materials.append(m)

    ok_a = amax > 0.001
    ok_l = lmax > 0.0005
    if ok_a:
        save_png(albedo)
    if ok_l:
        save_png(light)
    print("BAKE_GROUP %s res=%d objs=%d time=%.1fs albedo mean=%.4f max=%.4f %s "
          "light mean=%.4f max=%.4f %s ambient_mid=%.4f" % (
              g, res, len(objs), time.time() - t0, amean, amax,
              "VERIFY_OK" if ok_a else "VERIFY_FAIL",
              lmean, lmax, "VERIFY_OK" if ok_l else "VERIFY_FAIL", mid_frac))
    return {"group": g, "res": res,
            "albedo": "albedo_%s.png" % g if ok_a else None,
            "light": "light_%s.png" % g if ok_l else None,
            "ambient_mid": round(mid_frac, 4),
            "nodes": [o.name for o in objs]}

# ---------------- env panorama (--full) ----------------
def render_pano():
    suffix = ""
    if PANO_TIME == "goldenhour" or ENV_NAME:
        suffix = "_goldenhour" if PANO_TIME == "goldenhour" else "_" + (ENV_NAME or "variant").replace("_puresky", "").replace("_4k", "")
    old = bpy.data.objects.get("pano")
    if old:
        bpy.data.objects.remove(old, do_unlink=True)
    cam_data = bpy.data.cameras.new("pano")
    cam_data.type = "PANO"
    try:
        cam_data.panorama_type = "EQUIRECTANGULAR"
    except Exception:
        pass
    cam = bpy.data.objects.new("pano", cam_data)
    scene.collection.objects.link(cam)
    start = None
    for ob in scene.objects:
        if ob.name.startswith("coastal_road"):
            me = ob.data
            v0 = me.vertices[0].co
            start = ob.matrix_world @ v0
            break
    if start is None:
        start = (0.0, 0.0, 30.0)
    loc = (start[0], start[1], start[2] + 3.0)
    d = (1.0, 0.0, -0.015)
    yaw = math.atan2(d[1], d[0]) - math.pi / 2
    pitch = math.pi / 2 + math.asin(max(-1, min(1, d[2])))
    cam.location = loc
    cam.rotation_euler = (pitch, 0.0, yaw)
    scene.camera = cam
    scene.cycles.samples = 128
    scene.render.resolution_x = 2048
    scene.render.resolution_y = 1024
    scene.render.image_settings.file_format = "JPEG"
    scene.render.image_settings.quality = 85
    # the pano is the SHIPPED visible environment (sky background + car IBL):
    # render it at the natural sky strength, not the bake-calibrated one
    bg = scene.world.node_tree.nodes.get("Background") if scene.world else None
    saved_strength = bg.inputs[1].default_value if bg else None
    if bg is not None:
        bg.inputs[1].default_value = 1.0
    if PANO_TIME == "goldenhour":
        # v2 (blowout fix): the bake world is the LOCKED HDRI (no sky node —
        # set_world_env removes them; a flat-color tint hits a linked input
        # and is ignored). Golden-hour read = HDRI dimmed to 0.3 + a warm
        # low-elevation SUN lamp keying the frame; both pano-only, cleaned up
        # after the render.
        sun = bpy.data.lights.new("__pano_gh_sun", type="SUN")
        # v3 per the clip analysis: energy 1.2 (4 slammed 13x over the dimmed
        # env), 3000K amber, LOW elevation (rake 12deg -> long shadows), and
        # Filmic so the warm channels survive to the 8-bit jpg
        sun.energy = 1.8
        sun.color = (1.0, 0.42, 0.15)
        sun_ob = bpy.data.objects.new("__pano_gh_sun", sun)
        scene.collection.objects.link(sun_ob)
        sun_ob.rotation_euler = (math.radians(82), 0.0, math.radians(250))
        if bg is not None:
            bg.inputs[1].default_value = 0.22
        saved_vt = scene.view_settings.view_transform
        scene.view_settings.view_transform = "Filmic"
        scene.view_settings.look = "Medium Contrast"
        suffix = "_goldenhour"
    scene.render.filepath = os.path.join(
        ASSETS, "env_coast%s.jpg" % suffix)
    bpy.ops.render.render(write_still=True)
    if PANO_TIME == "goldenhour":
        s = bpy.data.objects.get("__pano_gh_sun")
        if s:
            ld = s.data
            bpy.data.objects.remove(s, do_unlink=True)
            if ld and ld.users == 0:
                bpy.data.lights.remove(ld)
    if PANO_TIME == "goldenhour" and saved_vt:
        scene.view_settings.view_transform = saved_vt
    if bg is not None and saved_strength is not None:
        bg.inputs[1].default_value = saved_strength
    print("PANO_OK", scene.render.filepath)

# ---------------- main ----------------
setup_engine(SAMPLES.get(MODE, 64))
if ENV_NAME:
    env_path = os.path.join(ASSETS, "hdri", ENV_NAME + ".hdr")
    if os.path.isfile(env_path):
        set_world_env(env_path)
    else:
        print("WORLD_ENV_MISSING:", env_path, "- keeping scene sky")
ensure_world_env()
if WARM:
    set_warm_rig()
if MODE != "--export-only" and not WARM:
    add_fill_rig()
groups = collect_groups()
print("BAKE_MODE:", MODE, "groups:", {g: len(o) for g, o in groups.items()})
manifest = {"generated_by": "bake.py", "mode": MODE, "atlas_groups": {}}
margin = MARGIN.get(MODE, 4)

if MODE == "--export-only":
    for g, objs in groups.items():
        uv_pass(g, objs, GROUPS[g])
        manifest["atlas_groups"][g] = {"res": GROUPS[g], "nodes": [o.name for o in objs],
                                       "albedo": "albedo_%s.png" % g,
                                       "light": "light_%s.png" % g}
    bpy.ops.wm.save_mainfile()
    print("BLEND_SAVED (atlas UVs persisted)")
elif MODE == "--pano-only" or WARM:
    # Variant modes share one contract: the CERTIFIED artifacts
    # (manifest.json, the daytime light_<g>.png set, tracks.glb, the blend)
    # are never touched — variants are SUFFIXED side files + a side-car
    # manifest. --pano-only renders the pano variant; --warm bakes the
    # golden-hour LIGHT variant set on the existing atlas UVs.
    if MODE == "--pano-only":
        render_pano()
        print("MANIFEST_PRESERVED (--pano-only does not rewrite manifest.json)")
    else:
        golden = {}
        for g, objs in groups.items():
            golden[g] = bake_group_light_only(g, objs, GROUPS[g],
                                              SAMPLES["--full"], margin)
        with open(os.path.join(ASSETS, "manifest_golden.json"), "w",
                  encoding="utf-8") as fh:
            import json
            json.dump({"generated_by": "bake.py --warm",
                       "pairs_with_env": "env_coast_goldenhour.jpg",
                       "rig": {"hdri": WARM_HDRI, "strength": WARM_STRENGTH,
                               "sun_rgb": list(WARM_SUN_RGB),
                               "sun_energy": WARM_SUN_ENERGY},
                       "atlas_groups": golden}, fh, indent=2)
        print("MANIFEST_GOLDEN_OK (manifest.json untouched)")
    print("BAKE_DONE mode=%s" % ("--pano-only" if MODE == "--pano-only" else "--warm"))
    raise SystemExit(0)
else:
    for g, objs in groups.items():
        res = GROUPS[g] if MODE == "--full" else TEST_RES_SCALE[g]
        manifest["atlas_groups"][g] = bake_group(g, objs, res, SAMPLES.get(MODE, 64), margin)
    bpy.ops.wm.save_mainfile()
    print("BLEND_SAVED")
    if MODE == "--full":
        render_pano()

glb_path = os.path.join(ASSETS, "tracks.glb")
try:
    bpy.ops.export_scene.gltf(filepath=glb_path, export_format="GLB", export_apply=False)
    print("EXPORT_OK", glb_path)
except Exception as exc:
    print("EXPORT_FAILED:", exc)

with open(os.path.join(ASSETS, "manifest.json"), "w", encoding="utf-8") as fh:
    import json
    json.dump(manifest, fh, indent=2)
print("MANIFEST_OK", os.path.join(ASSETS, "manifest.json"))
print("BAKE_DONE mode=%s" % MODE)