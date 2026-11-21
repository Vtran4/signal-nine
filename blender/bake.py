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
GROUPS = {"coastal": 2048, "downtown": 2048, "props": 1024}
TEST_RES_SCALE = {"coastal": 512, "downtown": 512, "props": 512}
SAMPLES = {"--test": 64, "--full": 384}
MARGIN = {"--test": 4, "--full": 8}
scene = bpy.context.scene

# ---------------- engine ----------------
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
    print("WORLD_ENV:", os.path.basename(hdr_path))

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

# ---------------- helpers ----------------
def group_of(name):
    pre = name.split("_")[0]
    return pre if pre in GROUPS else None

def collect_groups():
    groups = {}
    for ob in scene.objects:
        if ob.type != "MESH" or ob.name.startswith("__bake"):
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

def assign_tile_uvs(ob, rect, bbox):
    u0, v0, u1, v1 = rect
    bu0, bv0, bu1, bv1 = bbox
    bw = max(1e-6, bu1 - bu0)
    bh = max(1e-6, bv1 - bv0)
    s = min((u1 - u0) / bw, (v1 - v0) / bh)
    ox = u0 + ((u1 - u0) - bw * s) * 0.5
    oy = v0 + ((v1 - v0) - bh * s) * 0.5
    uv = ob.data.uv_layers.active
    for d in uv.data:
        d.uv = (ox + (d.uv[0] - bu0) * s, oy + (d.uv[1] - bv0) * s)

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

# ---------------- bake per group ----------------
def uv_pass(g, objs, res):
    entries = []
    infos = []
    total = sum(area_of(o) for o in objs)
    for ob in objs:
        has_uv = ob.data.uv_layers.active is not None
        bbox = uv_bbox(ob) if has_uv else smart_unwrap(ob)
        side = math.sqrt(area_of(ob) / total)
        infos.append((ob, bbox))
        entries.append((ob.name, side))
    tiles = shelf_pack(entries)
    for ob, bbox in infos:
        assign_tile_uvs(ob, tiles[ob.name], bbox)
    return tiles

def bake_group(g, objs, res, samples, margin):
    import time
    t0 = time.time()
    tiles = uv_pass(g, objs, res)
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

    # LIGHT pass — white override, direct+indirect, linear
    saved = {ob.name: [m for m in ob.data.materials if m] for ob in objs}
    lo = white_override(g, light)
    for ob in objs:
        ob.data.materials.clear()
        ob.data.materials.append(lo)
    bpy.ops.object.bake(type="DIFFUSE", pass_filter={"DIRECT", "INDIRECT"},
                        use_clear=False, margin=margin)
    lmean, lmax = image_stats(light)
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
          "light mean=%.4f max=%.4f %s" % (
              g, res, len(objs), time.time() - t0, amean, amax,
              "VERIFY_OK" if ok_a else "VERIFY_FAIL",
              lmean, lmax, "VERIFY_OK" if ok_l else "VERIFY_FAIL"))
    return {"group": g, "res": res,
            "albedo": "albedo_%s.png" % g if ok_a else None,
            "light": "light_%s.png" % g if ok_l else None,
            "nodes": [o.name for o in objs]}

# ---------------- env panorama (--full) ----------------
def render_pano():
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
    scene.render.filepath = os.path.join(ASSETS, "env_coast.jpg")
    bpy.ops.render.render(write_still=True)
    print("PANO_OK", scene.render.filepath)

# ---------------- main ----------------
setup_engine(SAMPLES.get(MODE, 64))
if ENV_NAME:
    env_path = os.path.join(ASSETS, "hdri", ENV_NAME + ".hdr")
    if os.path.isfile(env_path):
        set_world_env(env_path)
    else:
        print("WORLD_ENV_MISSING:", env_path, "- keeping scene sky")
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