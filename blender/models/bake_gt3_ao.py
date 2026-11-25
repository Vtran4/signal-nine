# WS-A AO aux bake for the GT3 (modeler-s9): unwrap every gt3 part into one
# 1024 shelf atlas, Cycles-bake AO into assets/ao_gt3.png, persist the UVs
# (the glb re-export carries them so coder's multiply-map shader samples the
# same layout), and write ao_gt3_report.json with the per-part rects.
# Patterns reused from blender/bake.py: shelf_pack / assign_tile_uvs /
# ensure_img_node. AO: white = open, dark = crevice — the client multiplies.
import bpy, math, os, json, sys

REPO = "C:/Users/vtran/OneDrive/Documents/AI projects/Signal Nine"
ASSETS = os.path.join(REPO, "assets")
src = open(os.path.join(REPO, "blender", "models", "build_gt3_hero.py")).read()
cut = src.index("scene = bpy.context.scene")
g = {"__name__": "gt3_build", "__file__":
     os.path.join(REPO, "blender", "models", "build_gt3_hero.py")}
exec(compile(src[:cut], "build_gt3_hero_partial", "exec"), g)
bpy = g["bpy"]
objs = sorted([o for o in bpy.data.objects
               if o.type == "MESH" and o.name.startswith("gt3_")
               and o.name != "gt3_ground"], key=lambda o: o.name)
print("AO_PARTS", len(objs))

RES = 2048  # WS-Q hi-res round: 2048^2 body maps (was 1024)
INSET = 12.0 / RES

def area_of(ob):
    ob.data.calc_loop_triangles()
    return sum(p.area for p in ob.data.polygons) or 1e-6

def uv_bbox(ob):
    uv = ob.data.uv_layers.active
    us = [d.uv[0] for d in uv.data]
    vs = [d.uv[1] for d in uv.data]
    return (min(us), min(vs), max(us), max(vs))

def smart_unwrap(ob):
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    if ob.data.uv_layers.active is None:
        ob.data.uv_layers.new(name="UVMap")
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.01)
    bpy.ops.object.mode_set(mode="OBJECT")
    return uv_bbox(ob)

def shelf_pack(entries):
    """Area-share shelf pack (bake.py pattern): tiles stacked in rows by
    decreasing side, rect = [u0, v0, u1, v1]. WS-Q fix: SHRINK-TO-FIT —
    the raw pack can exceed v=1.0 (it did: 45 of 49 tiles landed at
    v>1 and baked EMPTY, silently, since the first GT3 AO round); a
    uniform side scale keeps relative tile sizes while forcing the
    packed height inside the atlas."""
    lo, hi = 0.0, 1.0
    for _ in range(28):
        f = (lo + hi) / 2
        y_max = x = y = 0.0
        row_h = 0.0
        for name, side in sorted(entries, key=lambda e: -e[1]):
            w = h = side * f
            if x + w > 1.0:
                x = 0.0
                y += row_h
                row_h = 0.0
            x += w
            row_h = max(row_h, h)
            y_max = max(y_max, y + h)
        if y_max <= 1.0:
            lo = f  # feasible: the max feasible scale is >= f
        else:
            hi = f  # infeasible: go smaller
    f = lo
    tiles = {}
    x = y = 0.0
    row_h = 0.0
    for name, side in sorted(entries, key=lambda e: -e[1]):
        w = h = side * f
        if x + w > 1.0:
            x = 0.0
            y += row_h
            row_h = 0.0
        tiles[name] = [x, y, x + w, y + h]
        x += w
        row_h = max(row_h, h)
    return tiles

def assign_tile_uvs(ob, rect, bbox):
    uvl = ob.data.uv_layers.active
    bw = max(1e-6, bbox[2] - bbox[0])
    bh = max(1e-6, bbox[3] - bbox[1])
    rw = (rect[2] - rect[0]) - 2 * INSET
    rh = (rect[3] - rect[1]) - 2 * INSET
    for d in uvl.data:
        u, v = d.uv
        d.uv = (rect[0] + INSET + (u - bbox[0]) / bw * rw,
                rect[1] + INSET + (v - bbox[1]) / bh * rh)

# unwrap + pack (per-part: the parts have no UVs except the sign-kit-free
# gt3 — everything gets smart_unwrap)
entries = []
infos = []
for ob in objs:
    has = ob.data.uv_layers.active is not None
    bbox = uv_bbox(ob) if has else smart_unwrap(ob)
    if has and (bbox[2] - bbox[0] < 1e-3 or bbox[3] - bbox[1] < 1e-3):
        print("AO_REUNWRAP", ob.name)
        bbox = smart_unwrap(ob)
    side = math.sqrt(area_of(ob) / sum(area_of(o) for o in objs))
    infos.append((ob, bbox))
    entries.append((ob.name, side))
tiles = shelf_pack(entries)
for ob, bbox in infos:
    assign_tile_uvs(ob, tiles[ob.name], bbox)
print("AO_PACKED", len(tiles))

# AO bake: target image on every material, one pass over all parts
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.device = "GPU"
try:
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "OPTIX"
    prefs.get_devices()
    for d in prefs.devices:
        d.use = True
except Exception as exc:
    print("AO_GPU_FALLBACK", exc)
scene.cycles.samples = 32
scene.cycles.use_adaptive_sampling = False
scene.render.bake.margin = 8

ao = bpy.data.images.new("ao_gt3", RES, RES, alpha=False)
for ob in objs:
    for mat in ob.data.materials:
        if mat and mat.use_nodes:
            nt = mat.node_tree
            for n in nt.nodes:
                n.select = False
            tex = None
            for n in nt.nodes:
                if n.type == "TEX_IMAGE" and n.image and n.image.name == ao.name:
                    tex = n
                    break
            if tex is None:
                tex = nt.nodes.new("ShaderNodeTexImage")
                tex.image = ao
            tex.select = True
            nt.nodes.active = tex
bpy.ops.object.select_all(action="DESELECT")
for ob in objs:
    ob.select_set(True)
bpy.context.view_layer.objects.active = objs[0]
bpy.ops.object.bake(type="AO", use_clear=False, margin=8)
ao.filepath_raw = os.path.join(ASSETS, "ao_gt3.png")
ao.file_format = "PNG"
ao.save()
print("AO_SAVED", ao.filepath_raw)

# ---- WS-Q hi-res: ALBEDO pass on the SAME atlas UVs --------------------
# paint_gt3 bakes NEUTRAL WHITE so the client's per-variant paint color
# multiplies on top (same pattern as the AO multiply slot); carbon/tire/
# glass/lights/accents keep their true base colors.
paint = bpy.data.materials.get("paint_gt3")
saved_paint = None
if paint and paint.use_nodes:
    for n in paint.node_tree.nodes:
        if n.type == "BSDF_PRINCIPLED":
            saved_paint = tuple(n.inputs["Base Color"].default_value)
            n.inputs["Base Color"].default_value = (1.0, 1.0, 1.0, 1.0)
            break
print("ALBEDO_PAINT_WHITENED", saved_paint is not None)
alb = bpy.data.images.new("alb_gt3", RES, RES, alpha=False)
for ob in objs:
    for mat in ob.data.materials:
        if mat and mat.use_nodes:
            for n in mat.node_tree.nodes:
                if n.type == "TEX_IMAGE" and n.image and n.image.name == ao.name:
                    n.image = alb
bpy.ops.object.bake(type="DIFFUSE", use_clear=True, margin=12,
                    pass_filter={"COLOR"})
alb.filepath_raw = os.path.join(ASSETS, "alb_gt3.png")
alb.file_format = "PNG"
alb.save()
print("ALB_SAVED", alb.filepath_raw)
# restore the paint color + re-point the tex nodes at the AO image
if saved_paint is not None:
    for n in paint.node_tree.nodes:
        if n.type == "BSDF_PRINCIPLED":
            n.inputs["Base Color"].default_value = saved_paint
            break
for ob in objs:
    for mat in ob.data.materials:
        if mat and mat.use_nodes:
            for n in mat.node_tree.nodes:
                if n.type == "TEX_IMAGE" and n.image and n.image.name == alb.name:
                    n.image = ao
print("ALBEDO_RESTORED")

# mean/max sanity (stride-4-safe: sample R channel only)
import array
n = ao.size[0] * ao.size[1] * ao.channels
buf = array.array("f", bytes(4 * n))
ao.pixels.foreach_get(buf)
tot = cnt = 0
mx = 0.0
for i in range(0, n, 997):
    v = buf[i]
    tot += v
    cnt += 1
    mx = max(mx, v)
print("AO_STATS mean=%.4f max=%.4f" % (tot / max(1, cnt), mx))

report = {"file": "ao_gt3.png", "res": RES, "parts": len(objs),
          "rects": {k: [round(x, 4) for x in v] for k, v in tiles.items()},
          "consumer": "multiply map; white=open, dark=crevice"}
with open(os.path.join(ASSETS, "ao_gt3_report.json"), "w") as f:
    json.dump(report, f, indent=1)
print("AO_REPORT_OK")
# albedo report: same rects (shared atlas UVs), paint-neutrality contract
import array as _arr
n_alb = alb.size[0] * alb.size[1] * alb.channels
buf_a = _arr.array("f", bytes(4 * n_alb))
alb.pixels.foreach_get(buf_a)
tot_a = cnt_a = 0
for i in range(0, n_alb, 997):
    tot_a += buf_a[i]
    cnt_a += 1
alb_report = {"file": "alb_gt3.png", "res": RES, "parts": len(objs),
              "rects": report["rects"],
              "mean": round(tot_a / max(1, cnt_a), 4),
              "consumer": ("diffuse albedo; paint_gt3 regions are NEUTRAL "
                           "WHITE — client multiplies the per-variant paint "
                           "color on top; carbon/tire/glass/accents carry "
                           "their true colors"),
              "paint_neutral": True}
with open(os.path.join(ASSETS, "alb_gt3_report.json"), "w") as f:
    json.dump(alb_report, f, indent=1)
print("ALB_REPORT_OK")

# re-export the glb so it carries the AO UV layout
g["export_glb"]()
print("AO_DONE")