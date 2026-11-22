# pw_run.py — headless verification harness for Signal Nine.
# Ported from the proven Chrome Ronin runner. Usage:
#   python tools/pw_run.py <mode> [outdir]
#     smoke : load, wait ready, screenshot, report console errors (localhost + fx=0)
#     shots : key-moment screenshots (state-driven)
#     bot   : ?auto=1 scripted run, state-log matched
#     fps   : 1920x1080 frame-rate over 10s of gameplay
import json, os, sys, time
from playwright.sync_api import sync_playwright

MODE = sys.argv[1] if len(sys.argv) > 1 else "smoke"
OUT = sys.argv[2] if len(sys.argv) > 2 else "shots"
OUT_DIR = os.path.abspath(OUT)
os.makedirs(OUT_DIR, exist_ok=True)
PORT = 8139
BASE = f"http://127.0.0.1:{PORT}/index.html?lockres"

def new_page(ctx, w=1920, h=1080):
    pg = ctx.new_page()
    pg.set_viewport_size({"width": w, "height": h})
    errors = []
    pg.on("console", lambda m: errors.append(f"console-{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    pg.route("**/*.js", lambda route: route.continue_(headers={
        **route.request.headers, "cache-control": "no-cache"}))
    return pg, errors

def wait_ready(pg, timeout=30000):
    pg.wait_for_function("window.__ready === true", timeout=timeout)

def shot(pg, name):
    path = os.path.join(OUT_DIR, f"{name}.png")
    pg.screenshot(path=path)
    return path

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True,
                          args=["--use-gl=angle", "--enable-gpu", "--disable-gpu-sandbox"])
    ctx = b.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)

    if MODE == "smoke":
        pg, errors = new_page(ctx)
        pg.goto(BASE)
        try:
            wait_ready(pg, 30000)
            print("READY")
        except Exception as e:
            print("NOT_READY:", e)
        time.sleep(2)
        print("STATE:", pg.evaluate("window.__state ? window.__state() : 'none'"))
        print("ERRORS:", json.dumps(errors[:20], indent=1))
        print("COLLECTED:", pg.evaluate("JSON.stringify(window.__errors || [])")[:2000])
        print("SHOT:", shot(pg, "smoke_main"))
        # fx off — the post stack disabled must also boot clean (?fx=0 isolates it)
        pg2, errors2 = new_page(ctx)
        pg2.goto(f"http://127.0.0.1:{PORT}/index.html?lockres&fx=0&auto=1&state=drive")
        try:
            wait_ready(pg2)
        except Exception as e:
            print("NOFX_NOT_READY:", e)
        time.sleep(1)
        print("NOFX_ERRORS:", json.dumps(errors2[:10]))
        print("COLLECTED2:", pg2.evaluate("JSON.stringify(window.__errors || [])")[:2000])
        print("SHOT:", shot(pg2, "smoke_nofx"))
        pg.close(); pg2.close()

    elif MODE == "shots":
        pg, errors = new_page(ctx)
        # main screen
        pg.goto(BASE)
        wait_ready(pg)
        time.sleep(1.5)
        print("SHOT:", shot(pg, "attract"))
        # state-driven moments: greybox drive, forced boost (streaks+FOV), oncoming
        for st in ["drive", "boost"]:
            pg.goto(BASE + f"&auto=1&state={st}&t=12")
            wait_ready(pg)
            time.sleep(1.0)
            print(f"STATE_{st}:", pg.evaluate("window.__state()"))
            print(f"SHOT_{st}:", shot(pg, st))
        print("ERRORS:", json.dumps(errors[:20], indent=1))
        pg.close()

    elif MODE == "bot":
        pg, errors = new_page(ctx)
        pg.goto(BASE + "&auto=1&seed=7&state=drive")
        wait_ready(pg)
        time.sleep(1.5)
        print("SHOT:", shot(pg, "bot_start"))
        pg.wait_for_timeout(15000)
        s1 = json.loads(pg.evaluate("window.__state()"))
        print("STATE_MID1:", json.dumps(s1))
        print("SHOT:", shot(pg, "bot_mid1"))
        pg.wait_for_timeout(20000)
        s2 = json.loads(pg.evaluate("window.__state()"))
        print("STATE_MID2:", json.dumps(s2))
        print("SHOT:", shot(pg, "bot_mid2"))
        # acceptance: bot keeps speed and earns boost (Phase 0 bot contract)
        ok_speed = s2["speedMph"] > 80
        ok_boost = s2["boost"] > 0.05 or s2["stats"]["burnouts"] > 0
        on_road = s2["speedMph"] > 0 and s2["mode"] == "drive"
        print("BOT_CHECKS:", json.dumps({"speed_ok": ok_speed, "boost_earned": ok_boost, "running": on_road}))
        print("ERRORS:", json.dumps(errors[:20], indent=1))
        pg.close()

    elif MODE == "fps":
        pg, errors = new_page(ctx)
        pg.goto(BASE + "&seed=7&auto=1&state=drive")
        wait_ready(pg)
        pg.wait_for_timeout(3000)
        samples = pg.evaluate("""(async () => {
          await new Promise(r => setTimeout(r, 10000));
          return {fps: window.__fps, ms: window.__frameMs};
        })()""")
        print("FPS:", json.dumps(samples))
        print("ERRORS:", json.dumps(errors[:10], indent=1))
        pg.close()

    b.close()
print("DONE", MODE)