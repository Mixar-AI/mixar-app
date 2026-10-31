#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent previews and export packages in the background worker, on the REAL app.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_BACKEND=/path/to/mixar-backend \
MIXAR_QA_PORT=4799 QA_SCENARIO_OUT=/tmp/render-worker \
python tests/qa/render_worker_e2e.py [light|heavy|all]

Runs the backend's own ``render_viewport_final.py`` / ``render_inspection.py``
templates and the ``export_asset`` script body through the real ScriptExecutor
sandbox, and holds the reply open exactly as the executor does (the reply
sender is redirected into driver_namespace: no backend, no credits). Each job
runs twice, in the app (worker path switched off) and in the worker, so the
evidence carries end-to-end time, main-thread time, UI round trips during the
job, the snapshot cost, the delivered PNGs (compare them) and the two export
packages (compare their manifests). A forced native crash in the worker
(``supervisor.crash_next``) must leave the app's pid unchanged and the job
answered: retried once, then ``render_worker_crashed``.

``heavy`` builds 3000 objects with unique meshes and 8 packed 2K textures and
measures the snapshot (plain, compressed, with dirty images) and the previews.
"""
import base64
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(os.environ["QA_HARNESS"]) / "scenarios"))
from lib import QA, ScenarioFail, run_scenario  # noqa: E402

BACKEND = Path(os.environ.get("MIXAR_BACKEND", Path.home() / "mixar-src/mixar-backend"))
VIEWPORT = BACKEND / "modules/agent/tools/scripts/viewport"
OUT = Path(os.environ.get("QA_SCENARIO_OUT", "/tmp/render-worker-qa"))
PHASE = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()

INSTALL = """
import time, bpy
from mixar.modules.space_mixie_chat.core import preview_deferral as pd
ns = bpy.app.driver_namespace
for name in ('qa_rw_replies', 'qa_rw_reply_t', 'qa_rw_counts', 'qa_rw_t0'):
    ns[name] = {}
def record_reply(req, value):
    ns['qa_rw_counts'][req.request_id] = ns['qa_rw_counts'].get(req.request_id, 0) + 1
    ns['qa_rw_replies'][req.request_id] = dict(value)
    ns['qa_rw_reply_t'][req.request_id] = time.perf_counter()
pd._respond = record_reply
import os
result = {'pid': os.getpid()}
"""

LIGHT = """
import bpy, numpy as np
from mathutils import Vector
for obj in list(bpy.context.scene.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
img = bpy.data.images.new('RW_Checker', 512, 512)
img.generated_type = 'COLOR_GRID'
img.pack()
mat = bpy.data.materials.new('RW_Textured')
mat.use_nodes = True
nt = mat.node_tree
tex = nt.nodes.new('ShaderNodeTexImage')
tex.image = img
nt.links.new(tex.outputs['Color'], nt.nodes['Principled BSDF'].inputs['Base Color'])
bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32, location=(0, 0, 1))
sphere = bpy.context.object
sphere.name = 'RW_Sphere'
sphere.data.materials.append(mat)
bpy.ops.mesh.primitive_cube_add(size=1, location=(1.6, 0.4, 0.5))
cube = bpy.context.object
cube.name = 'RW_Cube'
blue = bpy.data.materials.new('RW_Blue')
blue.use_nodes = True
blue.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (.03, .15, .8, 1)
cube.data.materials.append(blue)
cube.modifiers.new('Bevel', 'BEVEL').width = .1
bpy.ops.mesh.primitive_plane_add(size=20)
bpy.context.object.name = 'RW_Ground'
bpy.ops.object.camera_add(location=(5, -7, 4))
cam = bpy.context.object
cam.rotation_euler = (Vector((0, 0, 1)) - cam.location).to_track_quat('-Z', 'Y').to_euler()
bpy.context.scene.camera = cam
bpy.ops.object.light_add(type='AREA', location=(2, -3, 6))
light = bpy.context.object
light.data.energy = 1200
light.data.size = 4
light.rotation_euler = (Vector((0, 0, 0)) - light.location).to_track_quat('-Z', 'Y').to_euler()
scene = bpy.context.scene
scene.render.resolution_x, scene.render.resolution_y = 1200, 900
scene.render.resolution_percentage = 80
bpy.ops.wm.save_as_mainfile(filepath=PATH)
result = {'objects': len(scene.objects), 'file': bpy.data.filepath.endswith('.blend')}
"""

HEAVY = """
import bpy, bmesh, numpy as np, time
t = time.perf_counter()
scene = bpy.context.scene
for obj in list(scene.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
rng = np.random.default_rng(7)
mats = []
for k in range(8):
    img = bpy.data.images.new('RW_Heavy_%d' % k, 2048, 2048)
    img.pixels.foreach_set(rng.random(2048 * 2048 * 4, dtype=np.float32))
    img.pack()
    mat = bpy.data.materials.new('RW_HeavyMat_%d' % k)
    mat.use_nodes = True
    tex = mat.node_tree.nodes.new('ShaderNodeTexImage')
    tex.image = img
    mat.node_tree.links.new(tex.outputs['Color'], mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'])
    mats.append(mat)
base = bpy.data.meshes.new('RW_HeavyBase')
bm = bmesh.new()
bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=12, radius=.35)
bm.to_mesh(base)
bm.free()
coll = bpy.data.collections.new('RW_Heavy')
scene.collection.children.link(coll)
for i in range(3000):
    me = base.copy()
    me.materials.append(mats[i % 8])
    ob = bpy.data.objects.new('RW_H_%04d' % i, me)
    ob.location = ((i % 60) - 30, (i // 60) - 25, 0)
    coll.objects.link(ob)
cam_data = bpy.data.cameras.new('RW_HeavyCam')
cam = bpy.data.objects.new('RW_HeavyCam', cam_data)
scene.collection.objects.link(cam)
cam.location = (0, -60, 45)
cam.rotation_euler = (0.95, 0, 0)
scene.camera = cam
sun = bpy.data.objects.new('RW_Sun', bpy.data.lights.new('RW_Sun', 'SUN'))
scene.collection.objects.link(sun)
bpy.ops.wm.save_as_mainfile(filepath=PATH)
result = {'objects': len(scene.objects), 'faces': sum(len(o.data.polygons) for o in coll.objects),
          'build_s': round(time.perf_counter() - t, 2),
          'dirty_after_pack': [i.name for i in bpy.data.images if i.is_dirty]}
"""

SNAPSHOT_VARIANTS = """
import bpy, os, time, json
from mixar.modules.common.render_worker import snapshot, supervisor
out = {}
record = snapshot.write('measure')
out['plain'] = {'save_s': record['save_s'], 'mb': round(record['bytes'] / 1e6, 1),
                'images_s': record['images_s'], 'dirty': record['image_count']}
snapshot.remove_folder(record['folder'])
path = os.path.join(supervisor.root_dir(), 'measure_compressed.blend')
t = time.perf_counter()
with snapshot._keep_bubble_windows():
    bpy.ops.wm.save_as_mainfile(filepath=path, copy=True, compress=True, relative_remap=True, thumbnail=False)
out['compressed'] = {'save_s': round(time.perf_counter() - t, 4), 'mb': round(os.path.getsize(path) / 1e6, 1)}
os.remove(path)
result = out
"""

DIRTY = """
import bpy, numpy as np
from mixar.modules.common.render_worker import snapshot
for k in range(4):
    img = bpy.data.images.new('RW_Paint_%d' % k, 2048, 2048)
    px = np.ones(2048 * 2048 * 4, dtype=np.float32) * .5
    img.pixels.foreach_set(px)
record = snapshot.write('measure')
snapshot.remove_folder(record['folder'])
result = {'save_s': record['save_s'], 'images_s': record['images_s'], 'dirty': record['image_count'],
          'mb': round(record['bytes'] / 1e6, 1)}
for k in range(4):
    bpy.data.images.remove(bpy.data.images['RW_Paint_%d' % k])
"""

RUN = """
import time, json, bpy
from mixar.modules.space_mixie_chat.core.executor import ScriptExecutor
from mixar.modules.space_mixie_chat.core import preview_deferral as pd, main_thread_executor as mte
from mixar.modules.common.agent_execution.request import ExecutionRequest
from mixar.modules.common.render_worker import supervisor as sup
ns = bpy.app.driver_namespace
original = sup.available
if MODE == 'app':
    sup.available = lambda: False
t0 = time.perf_counter()
ns['qa_rw_t0'][RID] = t0
try:
    mte._deferrable_depth += 1
    try:
        res = ScriptExecutor().execute(SCRIPT, push_undo=False).to_dict()
    finally:
        mte._deferrable_depth -= 1
finally:
    sup.available = original
main_s = time.perf_counter() - t0
req = ExecutionRequest(RID, '', tool_name=TOOL, session_id='')
key = pd.deferred_preview_key(res)
held = pd.defer_response(req, key, initial_result=res) if key else mte._defer_worker_job(
    req, res, bpy.context.scene)
if not held:
    value = dict(res)
    value.update(pd._printed_result(res.get('output', '')))
    value.pop('output', None)
    ns['qa_rw_replies'][RID] = value
    ns['qa_rw_reply_t'][RID] = time.perf_counter()
    ns['qa_rw_counts'][RID] = 1
result = {'held': bool(held), 'main_s': round(main_s, 4),
          'render_job': bpy.app.is_job_running('RENDER'),
          'res': {k: v for k, v in res.items() if k not in ('output',)},
          'tail': res.get('output', '')[-300:]}
"""

COLLECT = """
import base64, bpy, os
from mixar.modules.space_mixie_chat.core import preview_render as pr, export_package as ep
ns = bpy.app.driver_namespace
reply = dict(ns['qa_rw_replies'][RID])
e2e = ns['qa_rw_reply_t'][RID] - ns['qa_rw_t0'][RID]
image = reply.pop('image_url', None) or reply.pop('image_base64', None)
if image:
    raw = base64.b64decode(image.split(',', 1)[-1])
    with open(PNG, 'wb') as handle:
        handle.write(raw)
    reply['png_bytes'] = len(raw)
reply.pop('objects', None)
result = {'reply': reply, 'e2e_s': round(e2e, 3), 'count': ns['qa_rw_counts'][RID],
          'preview_worker': pr.last_worker_job(), 'export_worker': ep.last_worker_job()}
"""


def _params_script(template, params):
    return (f"import json as __json\n__PARAMS__ = __json.loads({json.dumps(params)!r})\ndel __json\n"
            + template.read_text())


def export_script(kwargs):
    encoded = json.dumps(kwargs)
    body = ("from mixar.modules.space_mixie_chat.core.export_package import export_package\n"
            "try:\n"
            f"    result = export_package(**json.loads({encoded!r}))\n"
            "    result['success'] = True\n"
            "except Exception as _error:\n"
            "    result = {'success': False, 'error': type(_error).__name__ + ': ' + str(_error)}")
    return f"import json\n{body}\nprint('\\n__RESULT__' + json.dumps(result))\n"


def require(cond, msg):
    if not cond:
        raise ScenarioFail(msg)


def _rtt(qa, n=4):
    samples = []
    for _ in range(n):
        t = time.monotonic()
        qa.eval("result = 1")
        samples.append(round(time.monotonic() - t, 3))
    return samples


def run_job(qa, mode, tool, script, label, timeout=600):
    rid = f"qa-rw-{label}-{mode}-{uuid.uuid4().hex[:6]}"
    code = (RUN.replace("MODE", repr(mode)).replace("RID", repr(rid)).replace("TOOL", repr(tool))
            .replace("SCRIPT", repr(script)))
    started = qa.eval(code)
    during = _rtt(qa) if started["held"] else []
    qa.wait(f"{rid!r} in bpy.app.driver_namespace['qa_rw_replies']", timeout=timeout)
    png = OUT / f"{label}-{mode}.png"
    got = qa.eval(COLLECT.replace("RID", repr(rid)).replace("PNG", repr(str(png))))
    got.update(mode=mode, label=label, main_s=started["main_s"], held=started["held"],
               native_render_job_at_start=started["render_job"], ui_rtt_during_s=during,
               png=str(png) if got["reply"].get("png_bytes") else "")
    require(got["count"] == 1, f"{label}/{mode}: answered {got['count']} times")
    return got


def _ps_rss_mb(pid):
    try:
        out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True)
        return round(int(out.stdout.strip()) / 1024, 1)
    except Exception:
        return None


def _worker_rss(qa):
    workers = qa.eval("from mixar.modules.common.render_worker import supervisor as s\nresult = s.workers()")
    return {kind: _ps_rss_mb(info["pid"]) for kind, info in workers.items()}


def _png_diff(a, b):
    import numpy as np
    from PIL import Image
    x = np.asarray(Image.open(a).convert("RGB"), dtype=np.float32)
    y = np.asarray(Image.open(b).convert("RGB"), dtype=np.float32)
    if x.shape != y.shape:
        return {"shape_a": list(x.shape), "shape_b": list(y.shape)}
    d = np.abs(x - y)
    return {"mean_abs": round(float(d.mean()), 3), "p99_abs": round(float(np.percentile(d, 99)), 2),
            "max_abs": float(d.max()), "shape": list(x.shape)}


def light(qa, evidence, pid):
    qa.eval(LIGHT.replace("PATH", repr(str(OUT / "rw_light.blend"))))
    # START is idempotent per key: each run needs its own key.
    def final_script(engine):
        return _params_script(VIEWPORT / "render_viewport_final.py",
                              {"job_key": uuid.uuid4().hex, "engine": engine, "width": 960, "height": 720})

    def inspect_script(shading, view="hero"):
        return _params_script(VIEWPORT / "render_inspection.py", {
            "job_key": uuid.uuid4().hex, "max_faces": 0,
            "inspection": {"view": view, "shading": shading, "width": 1024, "height": 768}})
    for label, make in (("light_final_eevee", lambda: final_script("eevee")),
                        ("light_final_cycles", lambda: final_script("cycles")),
                        ("light_inspect_material", lambda: inspect_script("material")),
                        ("light_inspect_solid", lambda: inspect_script("solid"))):
        rows = []
        for mode in ("app", "worker", "worker"):  # the second worker run is the warm one
            row = run_job(qa, mode, "render_viewport", make(), label)
            require(row["reply"].get("status") == "done", f"{label}/{mode}: {row['reply']}")
            row["worker_rss_mb"] = _worker_rss(qa) if mode == "worker" else {}
            rows.append(row)
        evidence[label] = {"rows": rows,
                           "pixel_diff_app_vs_worker": _png_diff(rows[0]["png"], rows[2]["png"])}
        print(f"[rw] {label}: " + ", ".join(f"{r['mode']} e2e={r['e2e_s']} main={r['main_s']}"
                                            for r in rows)
              + f" diff={evidence[label]['pixel_diff_app_vs_worker']}", flush=True)

    # Inspection metadata (labels, focus) must match too.
    a, w = evidence["light_inspect_material"]["rows"][0]["reply"], evidence["light_inspect_material"]["rows"][2]["reply"]
    evidence["inspection_keys_equal"] = sorted(a) == sorted(w)
    evidence["inspection_render_app"], evidence["inspection_render_worker"] = a.get("render"), w.get("render")

    # Scripts are not refused while a worker preview renders: no native job runs.
    row = run_job(qa, "worker", "render_viewport", final_script("cycles"), "no_gate")
    evidence["no_native_job_during_worker_preview"] = not row["native_render_job_at_start"]

    # --- forced native crash in the worker: retried once, app untouched ---
    qa.eval("from mixar.modules.common.render_worker import supervisor as s\ns.crash_next('preview', 1)\nresult=True")
    crash1 = run_job(qa, "worker", "render_viewport", inspect_script("material"), "crash_once")
    lw = crash1["preview_worker"]
    require(crash1["reply"].get("status") == "done", f"crash retry did not deliver: {crash1['reply']}")
    require(lw.get("attempts") == 2 and lw.get("retried_after_crash"), f"no retry recorded: {lw}")
    require(qa.eval("import os\nresult = os.getpid()") == pid, "the app restarted")
    qa.eval("from mixar.modules.common.render_worker import supervisor as s\ns.crash_next('preview', 2)\nresult=True")
    crash2 = run_job(qa, "worker", "render_viewport", inspect_script("material"), "crash_twice")
    require(crash2["reply"].get("status") == "failed"
            and crash2["reply"].get("error") == "render_worker_crashed", f"double crash: {crash2['reply']}")
    require(qa.eval("import os\nresult = os.getpid()") == pid, "the app restarted")
    reports = qa.eval("import os, glob\nfrom mixar.modules.common.render_worker import supervisor as s\n"
                      "result = sorted(os.path.basename(p) for p in glob.glob(os.path.join(s.root_dir(), 'worker-*', 'tmp', '*.crash.txt')))")
    after = run_job(qa, "worker", "render_viewport", inspect_script("material"), "after_crash")
    require(after["reply"].get("status") == "done", "the worker path did not recover after crashes")
    evidence["crash"] = {"once": {"reply_status": crash1["reply"]["status"], "worker": lw, "e2e_s": crash1["e2e_s"]},
                         "twice": {"reply": {k: crash2["reply"].get(k) for k in ("status", "error", "success")},
                                   "worker": crash2["preview_worker"], "e2e_s": crash2["e2e_s"]},
                         "worker_crash_reports": reports, "app_pid_unchanged": True,
                         "next_preview_after_crashes": after["reply"]["status"]}
    qa.snap(str(OUT / "app-after-crashes.png"))

    # --- export_asset: in the app vs in the worker; same package ---
    names_before = qa.eval("result = sorted(o.name for o in bpy.context.scene.objects)")
    packages = {}
    for mode in ("app", "worker"):
        kwargs = {"names": ["RW_Sphere", "RW_Cube"], "fmt": "glb", "filename": "rw_pkg",
                  "where": "project", "folder": f"pkg_{mode}", "join": False, "texture_tiers": [256],
                  "include_source": True, "readme": "QA package", "animations": None}
        row = run_job(qa, mode, "export_asset", export_script(kwargs), "export")
        require(row["reply"].get("success"), f"export/{mode}: {row['reply']}")
        manifest = json.loads((OUT / f"pkg_{mode}" / "manifest.json").read_text())
        packages[mode] = {"e2e_s": row["e2e_s"], "main_s": row["main_s"], "ui_rtt_during_s": row["ui_rtt_during_s"],
                          "files": row["reply"].get("files"), "verification": row["reply"].get("verification"),
                          "triangles": row["reply"].get("triangles"), "dimensions_m": row["reply"].get("dimensions_m"),
                          "manifest_files": {f["file"]: f["sha256_16"] for f in manifest["files"]},
                          "worker": row["export_worker"] if mode == "worker" else None}
    names_after = qa.eval("result = sorted(o.name for o in bpy.context.scene.objects)")
    require(names_before == names_after, "the export changed the user's object names")
    same = {f: packages["app"]["manifest_files"].get(f) == sha
            for f, sha in packages["worker"]["manifest_files"].items()}
    evidence["export"] = {"packages": packages, "file_sha_equal": same,
                          "verification_equal": packages["app"]["verification"] == packages["worker"]["verification"],
                          "scene_names_unchanged": True}
    print(f"[rw] export: app {packages['app']['e2e_s']}s (main {packages['app']['main_s']}), worker "
          f"{packages['worker']['e2e_s']}s (main {packages['worker']['main_s']}); same files {same}", flush=True)

    qa.eval("from mixar.modules.common.render_worker import supervisor as s\ns.crash_next('export', 1)\nresult=True")
    kwargs = {"names": ["RW_Sphere"], "fmt": "glb", "filename": "rw_crash", "where": "project",
              "folder": "pkg_crash", "texture_tiers": [], "include_source": False}
    row = run_job(qa, "worker", "export_asset", export_script(kwargs), "export_crash")
    require(row["reply"].get("success") and row["export_worker"].get("attempts") == 2,
            f"export crash retry: {row['reply']} {row['export_worker']}")
    evidence["export_crash_once"] = {"success": True, "worker": row["export_worker"], "e2e_s": row["e2e_s"]}


def heavy(qa, evidence):
    built = qa.eval(HEAVY.replace("PATH", repr(str(OUT / "rw_heavy.blend"))))
    evidence["heavy_scene"] = built
    print(f"[rw] heavy scene {built}", flush=True)
    evidence["heavy_snapshot"] = qa.eval(SNAPSHOT_VARIANTS)
    evidence["heavy_snapshot_dirty_images"] = qa.eval(DIRTY)
    print(f"[rw] heavy snapshot {evidence['heavy_snapshot']} dirty {evidence['heavy_snapshot_dirty_images']}", flush=True)
    app_rss = _ps_rss_mb(qa.eval("import os\nresult = os.getpid()"))
    evidence["heavy_app_rss_mb"] = app_rss

    def inspect_script():
        return _params_script(VIEWPORT / "render_inspection.py", {
            "job_key": uuid.uuid4().hex, "max_faces": 0,
            "inspection": {"view": "camera", "shading": "material", "width": 1024, "height": 768}})

    def final_script():
        return _params_script(VIEWPORT / "render_viewport_final.py",
                              {"job_key": uuid.uuid4().hex, "engine": "eevee", "width": 960, "height": 720})
    for label, make in (("heavy_inspect_material", inspect_script), ("heavy_final_eevee", final_script)):
        rows = []
        for mode in ("app", "worker", "worker"):
            row = run_job(qa, mode, "render_viewport", make(), label)
            require(row["reply"].get("status") == "done", f"{label}/{mode}: {row['reply']}")
            row["worker_rss_mb"] = _worker_rss(qa) if mode == "worker" else {}
            rows.append(row)
        evidence[label] = {"rows": rows,
                           "pixel_diff_app_vs_worker": _png_diff(rows[0]["png"], rows[2]["png"])}
        print(f"[rw] {label}: " + ", ".join(f"{r['mode']} e2e={r['e2e_s']} main={r['main_s']} "
                                            f"snap={r['preview_worker'].get('snapshot_save_s') if r['mode']=='worker' else '-'}"
                                            for r in rows)
              + f" diff={evidence[label]['pixel_diff_app_vs_worker']}", flush=True)
    names = [f"RW_H_{i:04d}" for i in range(0, 3000, 10)]
    for mode in ("app", "worker"):
        kwargs = {"names": names, "fmt": "glb", "filename": "rw_heavy", "where": "project",
                  "folder": f"heavy_pkg_{mode}", "join": True, "texture_tiers": [], "include_source": False}
        row = run_job(qa, mode, "export_asset", export_script(kwargs), "heavy_export")
        require(row["reply"].get("success"), f"heavy export/{mode}: {row['reply']}")
        evidence[f"heavy_export_{mode}"] = {"e2e_s": row["e2e_s"], "main_s": row["main_s"],
                                            "ui_rtt_during_s": row["ui_rtt_during_s"],
                                            "files": row["reply"].get("files"),
                                            "worker": row["export_worker"] if mode == "worker" else None}
        print(f"[rw] heavy export {mode}: e2e {row['e2e_s']} main {row['main_s']}", flush=True)


def run(qa: QA):
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        qa.step("wait_login", qa.cmd, "wait_login", timeout=10)
    except ScenarioFail:
        pass
    qa.dismiss_splash()
    qa.wait("not bpy.app.is_job_running('RENDER')", timeout=120)
    pid = qa.eval(INSTALL)["pid"]
    evidence = {"app_pid": pid}
    try:
        if PHASE in ("light", "all"):
            light(qa, evidence, pid)
        if PHASE in ("heavy", "all"):
            heavy(qa, evidence)
    finally:
        evidence["workers_at_end"] = qa.eval(
            "from mixar.modules.common.render_worker import supervisor as s\nresult = s.workers()")
        qa.eval("from mixar.modules.common.render_worker import supervisor as s\ns.shutdown_all()\nresult=True")
        (OUT / f"evidence-{PHASE}.json").write_text(json.dumps(evidence, indent=2, default=str))
    require(qa.eval("import os\nresult = os.getpid()") == pid, "the app restarted")
    return {"evidence": str(OUT / f"evidence-{PHASE}.json"), "backend_calls": 0}


if __name__ == "__main__":
    run_scenario("render_worker_e2e", run)
