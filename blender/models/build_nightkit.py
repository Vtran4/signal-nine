# WS-B2 night-kit content: authored high-density emissive atlas for the
# downtown window banks (modeler-s9).
# - reads the LIVE tracks.glb downtown_block_* uv rects (the client's
#   boot-time rect source - generator and consumer stay in lockstep per
#   the re-derive rule)
# - paints assets/nightkit_emissive.png: per-rect dense window banks
#   (4x5px cells, 55% lit, warm/cool mix, sub-bloom alpha) + ONE vertical
#   neon banner strip per rect (cyan/magenta alternating, full alpha -
#   these are the bloom carriers) + a dim roof-edge accent band
# - writes assets/nightkit_report.json (rects, counts, density stats)
# Headless: blender -b -P blender/models/build_nightkit.py
import bpy, os, json, math

REPO = "C:/Users/vtran/OneDrive/Documents/AI projects/Signal Nine"
ASSETS = os.path.join(REPO, "assets")
RES = 4096

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=os.path.join(ASSETS, "tracks.glb"))

rects = {}
for o in bpy.data.objects:
    if o.type == "MESH" and o.name.startswith("downtown_block"):
        uv = o.data.uv_layers.active
        if uv is None:
            continue
        us = [d.uv[0] for d in uv.data]
        vs = [d.uv[1] for d in uv.data]
        rects[o.name] = (min(us), min(vs), max(us), max(vs))
print("BLOCKS", len(rects))

# --- deterministic per-block rng (FNV-1a like the client's hash) ---
def rng_for(name):
    h = 2166136261
    for c in name:
        h ^= ord(c)
        h = (h * 16777619) & 0xFFFFFFFF
    state = h or 1
    def rnd():
        nonlocal state
        state ^= (state << 13) & 0xFFFFFFFF
        state ^= state >> 17
        state ^= (state << 5) & 0xFFFFFFFF
        state &= 0xFFFFFFFF
        return state / 0xFFFFFFFF
    return rnd

# --- paint into a byte buffer (RGBA, top-down rows = (1-v) like the client) ---
import numpy as np
buf = np.zeros((RES, RES, 4), dtype=np.uint8)

def px(x, y, r, g, b, a):
    if 0 <= x < RES and 0 <= y < RES:
        buf[y, x, 0] = r
        buf[y, x, 1] = g
        buf[y, x, 2] = b
        buf[y, x, 3] = a

stats = []
for name, (u0, v0, u1, v1) in sorted(rects.items()):
    rnd = rng_for(name)
    x0, x1 = int(u0 * RES), int(u1 * RES)
    y0, y1 = int((1 - v1) * RES), int((1 - v0) * RES)  # top-down
    w, h = x1 - x0, y1 - y0
    # window bank: 4x5 cells, 2px gaps, 55% lit, sub-bloom alpha
    cw, ch, gx, gy = 4, 5, 2, 2
    lit = unlit = 0
    for y in range(y0 + gy, y1 - ch, ch + gy):
        for x in range(x0 + gx, x1 - cw, cw + gx):
            r = rnd()
            if r < 0.45:
                unlit += 1
                continue
            lit += 1
            if r < 0.75:
                col = (207, 216, 232)   # cool interior
            elif r < 0.92:
                col = (255, 217, 160)   # warm interior
            else:
                col = (255, 233, 200)   # bright
            a = int(255 * (0.35 + rnd() * 0.12))
            for dy in range(ch):
                for dx in range(cw):
                    px(x + dx, y + dy, col[0], col[1], col[2], a)
    # ONE vertical neon banner: cyan/magenta alternating by hash, full
    # alpha (the bloom carrier), x placed in the rect's outer third
    side = 1 if rnd() < 0.5 else -1
    bx = x0 + (w - 5) if side > 0 else x0 + 1
    if rnd() < 0.5:
        col = (79, 227, 255)    # cyan
    else:
        col = (255, 79, 227)    # magenta
    for y in range(y0 + 2, y1 - 2):
        for dx in range(4):
            px(bx + dx, y, col[0], col[1], col[2], 255)
    # dim roof-edge accent band (below bloom - structure)
    for x in range(x0 + 2, x1 - 2):
        px(x, y0 + 1, 60, 200, 230, 120)
        px(x, y0 + 2, 60, 200, 230, 90)
    stats.append({"block": name, "rect": [round(u0, 5), round(v0, 5),
                                          round(u1, 5), round(v1, 5)],
                  "rect_px": [x0, y0, x1, y1],
                  "windows_lit": lit, "windows_unlit": unlit,
                  "banner": "cyan" if col[1] > 150 else "magenta"})

img = bpy.data.images.new("nightkit_emissive", RES, RES, alpha=True)
flat = np.zeros(RES * RES * 4, dtype=np.float32)
# blender pixel rows are BOTTOM-up; the client samples this PNG with
# flipY=true (top-down rows = (1-v)) - flip before upload so the saved
# PNG matches the rect coordinates
flat[:] = buf[::-1].reshape(-1).astype(np.float32) / 255.0
img.pixels.foreach_set(flat)
img.filepath_raw = os.path.join(ASSETS, "nightkit_emissive.png")
img.file_format = "PNG"
img.save()
print("NIGHTKIT_SAVED", img.filepath_raw)

tot_lit = sum(s["windows_lit"] for s in stats)
report = {"file": "nightkit_emissive.png", "res": RES, "blocks": len(rects),
          "windows_lit_total": tot_lit,
          "consumer": ("emissiveMap replacing the procedural canvas; block "
                       "rects = live tracks.glb uv bboxes (nightkit_rects.json); "
                       "windows sub-bloom (structure), banner strips full-alpha "
                       "(bloom carriers), cyan/magenta per downtowntrack.png"),
          "per_block": stats}
with open(os.path.join(ASSETS, "nightkit_report.json"), "w") as f:
    json.dump(report, f, indent=1)
print("NIGHTKIT_REPORT_OK lit_total=%d per_block_med=%d"
      % (tot_lit, sorted(s["windows_lit"] for s in stats)[len(stats) // 2]))