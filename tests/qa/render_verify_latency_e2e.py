#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""The agent's verification render is fast and leaves the main thread alone, on the REAL app.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_BACKEND=/path/to/mixar-backend \
MIXAR_QA_PORT=4799 QA_SCENARIO_OUT=/tmp/render-verify \
python tests/qa/render_verify_latency_e2e.py

No backend, no credits: the backend's own ``render_viewport_final.py`` /
``render_inspection.py`` templates run through the real ScriptExecutor and the
held-open deferral (the reply sender is redirected, as in render_worker_e2e).

1. Main-thread cost. On a scene of 400 animated objects the SAME render script
   runs as ``render_viewport`` (this branch: no before/after scene diff, no
   undo checkpoint) and under a scene-changing tool name, which is exactly the
   old path every render took. The render tool must take a fraction of it and
   push no undo step.
2. A warm worker. Cold (fresh worker) vs warm Cycles finals; then an idle
   worker past the idle stop while agent scripts keep arriving must survive
   and render warm, and without activity it must still stop (memory goes back).
3. The worker drops its document after each job (its log says so) and the next
   job still renders correctly. PNGs are saved for visual review.
"""
import json
import os
import time
import uuid

from render_worker_e2e import (COLLECT, INSTALL, LIGHT, OUT, VIEWPORT, QA, ScenarioFail,
                               _params_script, _ps_rss_mb, require, run_scenario)

ANIMATE = """
import bpy
scene = bpy.context.scene
coll = bpy.data.collections.new('RV_Anim')
scene.collection.children.link(coll)
mesh = bpy.data.meshes['Cube'] if 'Cube' in bpy.data.meshes else bpy.data.meshes.new('RV_M')
for i in range(400):
    ob = bpy.data.objects.new('RV_A_%03d' % i, mesh)
    ob.location = (i % 20 - 10, i // 20 - 10, -3)
    coll.objects.link(ob)
    for f in range(0, 200, 4):
        ob.location.z = -3 + (f % 7) * .01
        ob.rotation_euler.z = f * .01
        ob.keyframe_insert('location', frame=f)
        ob.keyframe_insert('rotation_euler', frame=f)
import time
from mixar.modules.space_mixie_chat.core.executor import get_executor
t = time.perf_counter()
get_executor()._capture_scene_state()
result = {'objects': len(scene.objects), 'capture_s': round(time.perf_counter() - t, 4)}
"""

RUN = """
import time, bpy
from mixar.modules.space_mixie_chat.core.executor import ScriptExecutor
from mixar.modules.space_mixie_chat.core import preview_deferral as pd
from mixar.modules.common.agent_execution.request import ExecutionRequest
ns = bpy.app.driver_namespace
executor = ScriptExecutor()
pushes = []
real_push = executor._push_undo_for_script
executor._push_undo_for_script = lambda *a, **k: (pushes.append(1), real_push(*a, **k))[1]
captures = []
real_capture = executor._capture_scene_state
executor._capture_scene_state = lambda: (captures.append(1), real_capture())[1]
t0 = time.perf_counter()
ns['qa_rw_t0'][RID] = t0
res = executor.execute(SCRIPT, tool_name=TOOL).to_dict()
main_s = time.perf_counter() - t0
req = ExecutionRequest(RID, '', tool_name='render_viewport', session_id='')
key = pd.deferred_preview_key(res)
held = bool(key) and pd.defer_response(req, key, initial_result=res)
result = {'held': bool(held), 'main_s': round(main_s, 4), 'undo_pushes': len(pushes),
          'captures': len(captures),
          'created': res.get('created_objects'), 'modified': len(res.get('modified_objects') or []),
          'tail': res.get('output', '')[-200:]}
"""

WORKERS = "from mixar.modules.common.render_worker import supervisor as s\nresult = s.workers()"


def final_script(engine="cycles"):
    return _params_script(VIEWPORT / "render_viewport_final.py",
                          {"job_key": uuid.uuid4().hex, "engine": engine, "width": 960, "height": 720})


def render(qa, tool, label, engine="cycles", timeout=300):
    rid = f"qa-rv-{label}-{uuid.uuid4().hex[:6]}"
    code = (RUN.replace("RID", repr(rid)).replace("TOOL", repr(tool))
            .replace("SCRIPT", repr(final_script(engine))))
    started = qa.eval(code)
    require(started["held"], f"{label}: not held open: {started}")
    qa.wait(f"{rid!r} in bpy.app.driver_namespace['qa_rw_replies']", timeout=timeout)
    png = OUT / f"{label}.png"
    got = qa.eval(COLLECT.replace("RID", repr(rid)).replace("PNG", repr(str(png))))
    require(got["reply"].get("status") == "done", f"{label}: {got['reply']}")
    row = {"label": label, "tool": tool, "main_s": started["main_s"], "e2e_s": got["e2e_s"],
           "undo_pushes": started["undo_pushes"], "captures": started["captures"],
           "created": started["created"], "modified": started["modified"],
           "worker": got["preview_worker"], "png": str(png)}
    print(f"[rv] {label}: main {row['main_s']} s, e2e {row['e2e_s']} s, "
          f"worker pid {row['worker'].get('pid')} seconds {row['worker'].get('worker_seconds')}",
          flush=True)
    return row


def run(qa: QA):
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        qa.step("wait_login", qa.cmd, "wait_login", timeout=10)
    except ScenarioFail:
        pass
    if hasattr(qa, "dismiss_splash"):
        qa.dismiss_splash()
    pid = qa.eval(INSTALL)["pid"]
    qa.eval(LIGHT.replace("PATH", repr(str(OUT / "rv_light.blend"))))
    ev = {"app_pid": pid}
    ev["scene"] = qa.eval(ANIMATE)
    print(f"[rv] scene: {ev['scene']}", flush=True)
    qa.eval("from mixar.modules.common.render_worker import supervisor as s\ns.shutdown_all()\nresult=1")

    # 2. cold vs warm (also the first main-thread sample of each tool name)
    cold = render(qa, "render_viewport", "cycles_cold")
    warm = render(qa, "render_viewport", "cycles_warm")
    require(warm["worker"]["pid"] == cold["worker"]["pid"], "the warm worker was not reused")
    ev["cold"], ev["warm"] = cold, warm

    # 1. main thread: the same render under the old path's tool name vs render_viewport
    rows = []
    for k in range(3):
        rows.append(render(qa, "execute_bpy_script", f"old_path_{k}"))
        rows.append(render(qa, "render_viewport", f"render_tool_{k}"))
    old = sorted(r["main_s"] for r in rows if r["tool"] == "execute_bpy_script")
    new = sorted(r["main_s"] for r in rows if r["tool"] == "render_viewport")
    ev["main_thread"] = {"old_path_s": old, "render_tool_s": new, "rows": rows}
    require(all(r["created"] in (None, []) and r["modified"] == 0 and r["undo_pushes"] == 0
                and r["captures"] == 0 for r in rows if r["tool"] == "render_viewport"),
            "the render tool diffed the scene, reported edits or pushed an undo step")
    require(all(r["captures"] == 2 for r in rows if r["tool"] == "execute_bpy_script"),
            "the old path no longer takes its two scene walks: the A/B is invalid")
    require(new[1] < old[1], f"render tool main thread {new} not below the old path {old}")

    # 1b. unsaved 4K paint images: only the pixel read stays on the main thread
    # (conversion and file writes run on the snapshot's background thread), and
    # the worker must still render the unsaved pixels: RV_Paint_0 (pure red)
    # textures the cube.
    qa.eval("import bpy, numpy as np\n"
            "for k in range(3):\n"
            "    img = bpy.data.images.new('RV_Paint_%d' % k, 4096, 4096)\n"
            "    px = np.full(4096 * 4096 * 4, .3 + .1 * k, dtype=np.float32)\n"
            "    if k == 0:\n"
            "        px.reshape(-1, 4)[:] = (1.0, 0.0, 0.0, 1.0)\n"
            "    img.pixels.foreach_set(px)\n"
            "mat = bpy.data.objects['RW_Cube'].active_material\n"
            "tex = mat.node_tree.nodes.new('ShaderNodeTexImage')\n"
            "tex.image = bpy.data.images['RV_Paint_0']\n"
            "mat.node_tree.links.new(tex.outputs['Color'], mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'])\n"
            "result = 1")
    # The old path, measured here: every pixel converted and written on the
    # calling thread (``background=False`` is exactly what each render did).
    old_dirty = qa.eval("import time\n"
                        "from mixar.modules.common.render_worker import snapshot\n"
                        "t = time.perf_counter()\n"
                        "rec = snapshot.write('measure', background=False)\n"
                        "result = round(time.perf_counter() - t, 4)\n"
                        "snapshot.remove_folder(rec['folder'])")
    dirty = []
    for k in range(3):
        qa.eval("import bpy\nbpy.data.objects['RW_Cube'].location.x += .01\nresult = 1")
        dirty.append(render(qa, "render_viewport", f"dirty_images_{k}"))
    ev["dirty_images"] = [{"main_s": r["main_s"], "images_s": r["worker"].get("snapshot_images_s"),
                           "save_s": r["worker"].get("snapshot_save_s"),
                           "dirty": r["worker"].get("dirty_images")} for r in dirty]
    print(f"[rv] dirty images: {ev['dirty_images']}", flush=True)
    require(all(r["worker"].get("dirty_images") == 3 for r in dirty), "the dirty images were not carried")
    ev["dirty_old_path_main_s"] = old_dirty
    print(f"[rv] dirty images, old synchronous path: {old_dirty} s", flush=True)
    # Only the pixel read (foreach_get) may stay on the main thread: well under
    # half of the old convert + write path on any platform (macOS ~0.06 vs 0.3 s,
    # Linux ~0.14 s vs the read + 0.1 s CRC + convert + write per image).
    require(sorted(r["main_s"] for r in dirty)[1] < 0.5 * old_dirty,
            f"three 4K dirty images still cost the main thread {ev['dirty_images']} "
            f"(old path {old_dirty} s)")
    red = qa.eval("import bpy\n"
                  "img = bpy.data.images.load(" + repr(dirty[-1]["png"]) + ")\n"
                  "w, h = img.size\n"
                  "px = img.pixels[:]\n"
                  "x, y = int(w * .74), int(h * .35)\n"
                  "i = (y * w + x) * 4\n"
                  "result = [round(v, 3) for v in px[i:i + 3]]\n"
                  "bpy.data.images.remove(img)")
    ev["cube_pixel_rgb"] = red
    # Lit and view-transformed, the red face reads about (0.95, 0.5, 0.46); the
    # cube's own material is blue, so red well above blue means the pixels arrived.
    require(red[0] > red[2] + 0.3 and red[0] > red[1] + 0.3,
            f"the worker did not render the unsaved red texture: {red}")
    # Drop the texture node with its image, or later renders show the missing-
    # texture magenta on the cube.
    qa.eval("import bpy\nmat = bpy.data.objects['RW_Cube'].active_material\n"
            "for node in [n for n in mat.node_tree.nodes if n.bl_idname == 'ShaderNodeTexImage']:\n"
            "    mat.node_tree.nodes.remove(node)\n"
            "for k in range(3):\n    bpy.data.images.remove(bpy.data.images['RV_Paint_%d' % k])\n"
            "result = 1")

    # 2b. idle past the stop while the agent keeps working, then without activity
    warm_pid = rows[-1]["worker"]["pid"]
    qa.eval("from mixar.modules.common.render_worker import supervisor as s\ns.IDLE_TTL_S = 3.0\nresult=1")
    try:
        for _ in range(8):
            qa.eval("from mixar.modules.common.render_worker import keep_warm, supervisor as s\n"
                    "keep_warm.note_agent_activity()\ns.maintain()\nresult=1")
            time.sleep(1.0)
        alive = qa.eval(WORKERS)
        require(alive.get("preview", {}).get("pid") == warm_pid,
                f"the warm worker was stopped while the agent was active: {alive}")
        kept = render(qa, "render_viewport", "cycles_after_active_idle")
        require(kept["worker"]["pid"] == warm_pid, "the kept worker did not serve the render")
        ev["kept_warm"] = kept
        ev["worker_rss_mb_idle_after_release"] = _ps_rss_mb(warm_pid)
        qa.eval("from mixar.modules.common.render_worker import keep_warm\nkeep_warm.reset_for_tests()\nresult=1")
        time.sleep(4.0)
        gone = qa.eval("from mixar.modules.common.render_worker import supervisor as s\n"
                       "s.maintain()\nresult = s.workers()")
        require("preview" not in gone, f"an idle worker with no agent activity survived: {gone}")
    finally:
        qa.eval("from mixar.modules.common.render_worker import supervisor as s\ns.IDLE_TTL_S = 120.0\nresult=1")

    # 3. the worker log says it dropped each document; the next job still rendered
    log = os.path.join(qa.eval("from mixar.modules.common.render_worker import supervisor as s\n"
                               "result = s.root_dir()"), "worker-preview", "worker.log")
    # The supervisor's log reader writes through a buffered file that is flushed
    # when the stopped worker's pipe closes, a moment after the stop above.
    deadline = time.monotonic() + 20
    while True:
        text = open(log, encoding="utf-8", errors="replace").read() if os.path.isfile(log) else ""
        ev["release_lines"] = [line for line in text.splitlines() if "document released" in line][-5:]
        if ev["release_lines"] or time.monotonic() > deadline:
            break
        time.sleep(0.5)
    require(ev["release_lines"], "the worker never reported a released document")

    ev["summary"] = {"cold_e2e_s": cold["e2e_s"], "warm_e2e_s": warm["e2e_s"],
                     "kept_warm_e2e_s": kept["e2e_s"],
                     "old_path_main_s_median": old[1], "render_tool_main_s_median": new[1],
                     "capture_one_walk_s": ev["scene"]["capture_s"]}
    print("[rv] summary " + json.dumps(ev["summary"]), flush=True)
    require(kept["e2e_s"] < cold["e2e_s"], "the kept worker was not faster than a cold one")
    qa.eval("from mixar.modules.common.render_worker import supervisor as s\ns.shutdown_all()\nresult=1")
    (OUT / "evidence-render-verify.json").write_text(json.dumps(ev, indent=2, default=str))
    require(qa.eval("import os\nresult = os.getpid()") == pid, "the app restarted")
    return {"evidence": str(OUT / "evidence-render-verify.json"), "backend_calls": 0}


if __name__ == "__main__":
    run_scenario("render_verify_latency_e2e", run)
