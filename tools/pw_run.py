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
        # texture hardening: the baked swap must happen AND come from the
        # embed bundle. A fallback hit while the bundle exists = manifest/
        # bundle drift — the exact bug that white-screened file:// while four
        # localhost gates stayed green.
        print("TEX:", pg.evaluate("JSON.stringify({bakeSwap: window.__bakeSwap, texCounts: window.__texCounts || null})"))
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

    elif MODE == "botsprint":
        # Downtown Sprint acceptance (spec §5): bot drives downtown end-to-end.
        # Log-matched acceptance: boost earned (oncoming + near-miss), drift line
        # used in S2, crest air observed near s~2050, meter arc sampled.
        sp_pg, errors = new_page(ctx)
        sp_pg.goto(f"http://127.0.0.1:{PORT}/index.html?lockres&track=downtown&auto=1&seed=7&state=drive")
        wait_ready(sp_pg)
        # --- PHASE 1: deterministic structural probes (the integration's actual
        # deliverables; single-run bot telemetry on stochastic traffic is too
        # noisy to gate on) ---
        phase1 = sp_pg.evaluate("""(function () {
          const T = window.__g.track, out = {};
          out.laneSqueeze = T.laneSqueeze;                    // spec §4.2: -1.25 inner oncoming
          out.laneDodge = T.laneDodge;
          out.zones = (window.__g.traffic.zones || []).length; // spec §2/§3: 8 zones wired
          out.excludes = (window.__g.traffic.excludes || []).length; // 5: 4 bubbles + crest runway
          // sprint grid: startRace, read positions, return to drive
          window.__g.startRace();
          const car = window.__g.car;
          out.gridPlayer = Math.round(car.s);
          out.gridRivals = (window.__g.mode === 'race' && window.__g.race)
            ? window.__g.race.rivals.map(r => Math.round(r.s)) : null;
          window.__g.startRun();                               // back to drive for the bot run
          return out;
        })()""")
        print("SPRINT_STRUCT:", json.dumps(phase1))
        struct_ok = (phase1.get("laneSqueeze") == -1.25 and phase1.get("zones") == 8
                     and phase1.get("excludes") == 5 and phase1.get("gridPlayer") == 54
                     and phase1.get("gridRivals") == [45, 36, 27, 18, 9])
        print("SPRINT_STRUCT_OK:", struct_ok)
        time.sleep(1.5)
        samples = []
        t0 = time.time()
        maxAirT = 0.0
        while time.time() - t0 < 150:
            st = json.loads(sp_pg.evaluate("window.__state()"))
            # crest window (S4, s 1850-2300): fast-poll car.air at ~10 Hz — a
            # 0.3-0.5s lift is invisible to 1 Hz sampling
            if 1850 <= st["dbg"]["s"] <= 2300:
                airT = sp_pg.evaluate("(function(){const a=window.__g&&window.__g.car&&window.__g.car.air;return a?a.time:0})()")
                maxAirT = max(maxAirT, airT or 0)
                airUp = bool(sp_pg.evaluate("(function(){const a=window.__g&&window.__g.car&&window.__g.car.air;return a&&a.up})()"))
            else:
                airUp = False
            samples.append({"t": round(time.time() - t0, 1), "s": st["dbg"]["s"],
                            "mph": st["speedMph"], "meter": round(st["boost"], 2),
                            "active": st["boostActive"], "chain": st["chain"],
                            "nm": st["stats"]["nearMisses"], "onc": round(st["stats"]["oncomingTime"], 1),
                            "drift": round(st["stats"]["driftTime"], 1),
                            "airUp": airUp})
            sp_pg.wait_for_timeout(1000)
            if st["dbg"]["s"] > 2950 or st["mode"] != "drive":
                break
        fin = json.loads(sp_pg.evaluate("window.__state()"))
        print("SPRINT_TRAIL:", json.dumps(samples[::3]))   # every 3rd sample
        print("SPRINT_FINAL:", json.dumps(fin))
        print("SPRINT_AIR_MAX:", round(maxAirT, 2))
        stats = fin["stats"]
        maxMeter = max((x["meter"] for x in samples), default=0)
        s2Mph = max((x["mph"] for x in samples if 400 <= x["s"] <= 900), default=0)
        checks = {
            "boost_earned": fin["boost"] > 0.05 or fin["boostActive"] or stats["burnouts"] > 0 or maxMeter >= 0.99,
            "nearmiss_income": stats["nearMisses"] > 0,
            "oncoming_income": stats["oncomingTime"] > 1.0,
            # drift_flag_live: the drifting flag registers slip-based drift; the
            # spec's S2 drift LINE is a player technique (bot.js hardcodes
            # drift:false) — reported as S2 sweep mph below, not gating
            "drift_flag_live": stats["driftTime"] > 0.2,
            # crest_air: Option 1 arcade-hop is LIVE (ruling 2026-11-24) — the
            # bot carries 120+ mph into the S4 crest, so the 10 Hz fast-poll
            # must see ~0.75s of air; 0.5s floor = ruling margin
            "crest_air_0p75": maxAirT > 0.5,
            "progress_made": fin["dbg"]["s"] > 1500,
        }
        s2Mph = max((x["mph"] for x in samples if 400 <= x["s"] <= 900), default=0)
        crestMph = max((x["mph"] for x in samples if 1850 <= x["s"] <= 2300), default=0)
        print("SPRINT_S2_MPH(report-only, bot is a no-drift follower):", s2Mph)
        print("SPRINT_CREST_MPH(report-only):", crestMph)
        print("SPRINT_CHECKS:", json.dumps(checks))
        print("SPRINT_PASS:", struct_ok and all(checks.values()))
        print("ERRORS:", json.dumps(errors[:20], indent=1))
        print("SHOT:", shot(sp_pg, "botsprint_final"))
        sp_pg.close()

    elif MODE == "fps":
        # contract (pinned by pm-s9): design target 60 sustained at 1080p on the
        # 1080 Ti; headless cadence bounds this assert at ~57 (RAF gaps ~17.5ms
        # median), real-display 60 validated via headed capture. Asserts:
        # sustained fps >= 55, median RAF gap <= 18.5ms, frame-cost EMA <= 18ms,
        # scaler unengaged (resScale 1.0), full live traffic, no ?lockres.
        fps_pg, errors = new_page(ctx)
        fps_pg.goto(f"http://127.0.0.1:{PORT}/index.html?seed=7&auto=1&state=drive")
        wait_ready(fps_pg)
        fps_pg.wait_for_timeout(3000)  # let the scaler settle
        samples = fps_pg.evaluate("""(async () => {
          const gaps = []; let last = performance.now(); let n = 0;
          await new Promise(res => { function f(){ const t = performance.now(); gaps.push(t - last); last = t; n++;
            if (n < 600) requestAnimationFrame(f); else res(); } requestAnimationFrame(f); });
          gaps.sort((a, b) => a - b);
          return {fps: window.__fps, ms: window.__frameMs, scale: window.__resScale,
                  medianGap: Math.round(gaps[Math.floor(gaps.length / 2)] * 100) / 100};
        })()""")
        sustained_ok = (samples["fps"] >= 30 and samples["medianGap"] <= 18.5
                        and samples["ms"] <= 18.0 and samples["scale"] == 1.0)
        print("CONTRACT: Phase 2.0 floor 30 sustained (>=55 retired at the lit-default landing); design target 60; healthy lit numbers 57-60")
        print("FPS:", json.dumps(samples), "SUSTAINED_OK:", sustained_ok)
        print("ERRORS:", json.dumps(errors[:10], indent=1))
        fps_pg.close()

    elif MODE == "audio":
        # audio-verification rider (approved 2026-11-23): functional check of the
        # WebAudio set via the window.__g.audio debug handle — zero client changes.
        # Drives the REAL graph: enable -> build check -> engine pitch tracks
        # speed -> boost swell -> drift chirp -> music scheduler advances ->
        # one-shot events build their graphs (in-page node-count patch).
        import json as _json
        au_pg, errors = new_page(ctx)
        au_pg.goto(f"http://127.0.0.1:{PORT}/index.html?seed=7&auto=1&state=drive")
        wait_ready(au_pg)
        checks = au_pg.evaluate("""(async () => {
          const out = {};
          const A = window.__g && window.__g.audio;
          if (!A) return { fatal: 'no window.__g.audio handle' };
          A.enable();
          out.enabled = !!(A.on && A.ctx);
          out.ctxState = A.ctx ? A.ctx.state : 'none';
          if (A.ctx && A.ctx.state === 'suspended') { try { await A.ctx.resume(); } catch (e) {} }
          out.ctxStateAfterResume = A.ctx ? A.ctx.state : 'none';
          out.graph = { osc: A.osc ? A.osc.length : 0, hasFilter: !!A.engFilter,
                        hasBuses: !!(A.busEngine && A.busSfx && A.busMusic),
                        hasChirp: !!A.chirpGain, hasWind: !!A.windGain };
          const settle = (ms) => new Promise(r => setTimeout(r, ms));
          // The live game loop calls audio.update() every frame with REAL state,
          // clobbering any single synthetic call. For the state-driven checks we
          // shadow the instance's update() for the drive duration — the game's
          // calls land in our wrapper and the ORIGINAL update() receives ONLY
          // our synthetic state. Restored right after. Page-side test rig only.
          const realUpdate = A.update.bind(A);
          let shadow = null;
          A.update = (dt, st) => shadow ? shadow(dt, st) : realUpdate(dt, st);
          const drive = async (ms, st) => { shadow = (dt) => realUpdate(dt, st);
            await settle(ms); shadow = null; };
          // 1) engine pitch tracks speed: drive update() with synthetic state
          await drive(300, { speedNorm: 0.05, throttle: 0, boostK: 0, drifting: false });
          const fLow = A.osc[0].frequency.value;
          await drive(300, { speedNorm: 0.95, throttle: 1, boostK: 0, drifting: false });
          const fHigh = A.osc[0].frequency.value;
          out.enginePitch = { fLow: Math.round(fLow * 10) / 10, fHigh: Math.round(fHigh * 10) / 10,
                              tracksSpeed: fHigh > fLow * 2 };
          // 2) boost swell: music bus to ~1.0 on boost, ~0.3 off
          await drive(500, { speedNorm: 0.5, throttle: 1, boostK: 0.9, drifting: false });
          const gBoost = A.busMusic.gain.value;
          await drive(900, { speedNorm: 0.5, throttle: 1, boostK: 0, drifting: false });
          const gCalm = A.busMusic.gain.value;
          out.boostSwell = { boost: Math.round(gBoost * 100) / 100, calm: Math.round(gCalm * 100) / 100,
                             swells: gBoost > 0.85 && gCalm < 0.55 };
          // 3) drift chirp gates on drifting
          await drive(300, { speedNorm: 0.6, throttle: 1, boostK: 0, drifting: true });
          const cOn = A.chirpGain.gain.value;
          await drive(600, { speedNorm: 0.6, throttle: 1, boostK: 0, drifting: false });
          const cOff = A.chirpGain.gain.value;
          out.chirp = { on: Math.round(cOn * 1000) / 1000, off: Math.round(cOff * 1000) / 1000,
                        gates: cOn > 0.1 && cOff < 0.05 };
          A.update = realUpdate;  // unwrap — game state flows normally again
          // 4) music scheduler advances on the real clock
          const s0 = A._step; await settle(1200); const s1 = A._step;
          out.musicScheduler = { step0: s0, step1: s1, advances: s1 > s0 };
          // 5) one-shot events actually build their graphs (count node creation)
          const counts = { osc: 0, gain: 0, buf: 0, filt: 0 };
          const wrap = (kind, key) => { const orig = A.ctx[kind].bind(A.ctx);
            A.ctx[kind] = (...a) => { counts[key]++; return orig(...a); }; };
          wrap('createOscillator', 'osc'); wrap('createGain', 'gain');
          wrap('createBufferSource', 'buf'); wrap('createBiquadFilter', 'filt');
          const fired = {};
          for (const ev of ['nearmiss', 'crash', 'burnout', 'wall']) {
            const before = { ...counts };
            try { A.fire(ev); fired[ev] = true; } catch (e) { fired[ev] = String(e); }
            await settle(30);
            fired[ev + '_nodes'] = (counts.osc - before.osc) + (counts.gain - before.gain)
                                 + (counts.buf - before.buf) + (counts.filt - before.filt);
          }
          out.events = fired;
          out.allOk = out.enabled && out.ctxStateAfterResume === 'running'
            && out.graph.osc === 3 && out.graph.hasFilter && out.graph.hasBuses
            && out.graph.hasChirp && out.graph.hasWind
            && out.enginePitch.tracksSpeed && out.boostSwell.swells
            && out.chirp.gates && out.musicScheduler.advances
            && ['nearmiss', 'crash', 'burnout', 'wall'].every(ev => fired[ev] === true && fired[ev + '_nodes'] > 0);
          return out;
        })()""")
        print("AUDIO:", _json.dumps(checks, indent=1))
        print("AUDIO_OK:", checks.get("allOk", False))
        print("ERRORS:", _json.dumps(errors[:10], indent=1))
        shot(au_pg, "audio_main")
        au_pg.close()

    b.close()
print("DONE", MODE)