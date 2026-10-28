# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""No-credit QA scenario: Smart UV counts the uploaded mesh and lands over its source.

Bug 2 (triangle limit), through real Moodboard nodes and the Generate button:
a cube under Subsurf level 7 (12 base triangles, 196,608 evaluated) gets past
the limit, and a 100,000-triangle grid under Decimate 0.5 (~50k evaluated) is
refused before any export. The agent operator ``mixie.agent_tripo_uv`` is
checked the same way.

Bug 1 (placement): a Suzanne source at (-4, 0, 1), rot z 30 deg, scale 1.5 is
submitted from its Smart UV node AND from the agent operator. The result hook
each submit builds is then replayed exactly as a completed job runs it
(``model_io.import_file`` + ``AsyncGLBJob.on_imported``) with a Tripo
``/v3/mesh/uv`` result GLB, which comes back centred and normalised to 1 m.
Each ``<source>_uv`` must cover the source's world box and coincide with its
vertices (so no rotation is needed), and the source must be untouched.

Nothing is submitted: ``enqueue_generation`` is patched in both submit modules
to record the call and raise, and ``JobQueueService.enqueue`` raises as a
backstop; all three are restored at the end.

Launch a fresh isolated app (``$QA_HARNESS/run_qa_app_parallel.sh``), then:
    QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=<port> \\
        [QA_SMART_UV_GLB=/path/to/tripo/model.glb] \\
        python3 tests/qa/smart_uv_placement_tricount_e2e.py
``QA_SMART_UV_GLB`` is a GLB a real Smart UV job returned for this exact
Suzanne; without it the scenario writes the equivalent fixture itself (the
source's world-space mesh, centred and scaled to 1 m: what Tripo returns).
Uses ``QA_SCENARIO_OUT`` when set. Never run on a user session.
Vision: in each snapshot the green ``_uv`` wireframe must sit exactly on the
red source Suzanne, with nothing left at the world origin.
"""

import json
import os
from pathlib import Path
import sys
import tempfile
import textwrap

SOURCE = "QA_SmartUV_Src"
SUBSURF = "QA_UV_Subsurf"
DECIMATE = "QA_UV_Decimate"

FIXTURES = f'''
import bmesh, math, numpy as np
from mathutils import Matrix
win = drv.main_window()
scene = win.scene
for name in ({SOURCE!r}, {SUBSURF!r}, {DECIMATE!r}):
    assert name not in bpy.data.objects, "Start a fresh QA instance"
def link(name, mesh, loc, rot_z=0.0, scale=1.0):
    obj = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(obj)
    obj.location, obj.rotation_euler.z, obj.scale = loc, math.radians(rot_z), (scale,) * 3
    return obj
bm = bmesh.new()
bm.loops.layers.uv.new("UVMap")
bmesh.ops.create_monkey(bm, matrix=Matrix.Identity(4), calc_uvs=True)
me = bpy.data.meshes.new({SOURCE!r}); bm.to_mesh(me); bm.free()
link({SOURCE!r}, me, (-4.0, 0.0, 1.0), 30.0, 1.5)
bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1.0)
me = bpy.data.meshes.new({SUBSURF!r}); bm.to_mesh(me); bm.free()
mod = link({SUBSURF!r}, me, (6.0, 0.0, 0.0)).modifiers.new("Subdivision", 'SUBSURF')
mod.levels = mod.render_levels = 7
nx, ny = 250, 200  # 50,000 quads = 100,000 triangles
X, Y = np.meshgrid(np.linspace(0, 1, nx + 1), np.linspace(0, 1, ny + 1))
co = np.stack([X.ravel(), Y.ravel(), np.zeros(X.size)], 1).astype(np.float32)
I, J = np.meshgrid(np.arange(nx), np.arange(ny))
a = (J * (nx + 1) + I).ravel()
quads = np.stack([a, a + 1, a + nx + 2, a + nx + 1], 1).astype(np.int32).ravel()
me = bpy.data.meshes.new({DECIMATE!r})
me.vertices.add(len(co)); me.vertices.foreach_set("co", co.ravel())
me.loops.add(len(quads)); me.loops.foreach_set("vertex_index", quads)
me.polygons.add(nx * ny)
me.polygons.foreach_set("loop_start", np.arange(0, len(quads), 4, dtype=np.int32))
me.update(calc_edges=True)
link({DECIMATE!r}, me, (12.0, -3.0, 0.0)).modifiers.new("Decimate", 'DECIMATE').ratio = 0.5
win.view_layer.update()
deps = bpy.context.evaluated_depsgraph_get()
def tris(obj, evaluated):
    mesh = obj.evaluated_get(deps).data if evaluated else obj.data
    return sum(len(p.vertices) - 2 for p in mesh.polygons)
result = {{n: {{"base": tris(bpy.data.objects[n], False),
              "evaluated": tris(bpy.data.objects[n], True)}}
          for n in ({SOURCE!r}, {SUBSURF!r}, {DECIMATE!r})}}
'''

# Record-and-raise in both submit modules; the queue service raises as a backstop.
GUARD = '''
import sys, types, base64, json, struct
from mixar.modules.moodboard.core import node_mesh_execution as nme
from mixar.modules.hunyuan.core import tripo_uv_enqueue as T
from mixar.modules.common.api.services.job_queue_service import JobQueueService
state = sys.modules.setdefault("qa_smart_uv_state", types.ModuleType("qa_smart_uv_state"))
if not hasattr(state, "originals"):
    state.originals = {"nme": nme.enqueue_generation, "T": T.enqueue_generation,
                       "service": JobQueueService.enqueue}
state.calls = []
def glb_triangles(b64):
    data = base64.b64decode(b64)
    gltf = json.loads(data[20:20 + struct.unpack_from("<I", data, 12)[0]])
    return sum(gltf["accessors"][p["indices"]]["count"] // 3
               for m in gltf["meshes"] for p in m["primitives"])
def guard(**kw):
    payload = kw.get("payload") or {}
    state.calls.append({"job_type": kw.get("job_type"), "label": kw.get("label"),
                        "glb_triangles": glb_triangles(payload["file_bytes_b64"]),
                        "hook": kw.get("on_imported"), "feature_key": kw.get("feature_key")})
    raise ValueError("QA GUARD: submit stopped")
def service_guard(self, *a, **kw):
    raise RuntimeError("QA GUARD: JobQueueService.enqueue must not run")
nme.enqueue_generation = T.enqueue_generation = guard
JobQueueService.enqueue = service_guard
result = True
'''

RESTORE = '''
import sys
from mixar.modules.moodboard.core import node_mesh_execution as nme
from mixar.modules.hunyuan.core import tripo_uv_enqueue as T
from mixar.modules.common.api.services.job_queue_service import JobQueueService
from mixar.modules.common.job_queue.core import enqueue as real
state = sys.modules.pop("qa_smart_uv_state", None)
if state is not None and hasattr(state, "originals"):
    nme.enqueue_generation = state.originals["nme"]
    T.enqueue_generation = state.originals["T"]
    JobQueueService.enqueue = state.originals["service"]
result = (nme.enqueue_generation is real.enqueue_generation
          and T.enqueue_generation is real.enqueue_generation
          and JobQueueService.enqueue.__name__ == "enqueue")
'''

# The geometry the source occupies and what the result must match.
MEASURE = f'''
import hashlib, numpy as np
from mixar.modules.hunyuan.core.tripo_uv_placement import source_world_bounds
drv.main_window().view_layer.update()
def world(obj):
    co = np.empty(len(obj.data.vertices) * 3); obj.data.vertices.foreach_get("co", co)
    m = np.array(obj.matrix_world)
    return co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]
def fingerprint(obj):
    co = np.empty(len(obj.data.vertices) * 3); obj.data.vertices.foreach_get("co", co)
    uv = np.empty(len(obj.data.loops) * 2); obj.data.uv_layers[0].data.foreach_get("uv", uv)
    return {{"name": obj.name, "data": obj.data.name,
            "matrix": [round(v, 6) for row in obj.matrix_world for v in row],
            "co": hashlib.sha1(co.tobytes()).hexdigest()[:12],
            "uv": hashlib.sha1(uv.tobytes()).hexdigest()[:12],
            "materials": [m.name for m in obj.data.materials if m]}}
def compare(result_name):
    src, res = bpy.data.objects[{SOURCE!r}], bpy.data.objects[result_name]
    s, r = world(src), world(res)
    dist = np.sqrt(((r[:, None, :] - s[None, :, :]) ** 2).sum(-1)).min(1)
    size = float((s.max(0) - s.min(0)).max())
    return {{"source_box": [s.min(0).round(4).tolist(), s.max(0).round(4).tolist()],
            "result_box": [r.min(0).round(4).tolist(), r.max(0).round(4).tolist()],
            "box_error": float(np.abs(np.r_[r.min(0) - s.min(0), r.max(0) - s.max(0)]).max()),
            "source_size": size,
            "nearest_vertex_mean": float(dist.mean()), "nearest_vertex_max": float(dist.max()),
            "result_scale": [round(v, 5) for v in res.matrix_world.to_scale()],
            "result_rotation": [round(v, 6) for v in res.matrix_world.to_euler()],
            "result_tris": sum(len(p.vertices) - 2 for p in res.data.polygons),
            "recorded_box": source_world_bounds([src])}}
'''

# The Tripo result for this Suzanne when no saved GLB is given: its
# world-space mesh, centred and scaled so the largest dimension is 1 m.
WRITE_GLB = f'''
import os, tempfile, numpy as np
from mathutils import Matrix
src = bpy.data.objects[{SOURCE!r}]
me = src.data.copy(); me.transform(src.matrix_world)
co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
lo, hi = co.min(0), co.max(0)
me.transform(Matrix.Diagonal((*([1.0 / float((hi - lo).max())] * 3), 1.0))
             @ Matrix.Translation(-(lo + hi) / 2))
tmp = bpy.data.objects.new({SOURCE!r} + "_tripo", me)
drv.main_window().scene.collection.objects.link(tmp)
for obj in drv.main_window().view_layer.objects:
    obj.select_set(obj is tmp)
path = os.path.join(tempfile.mkdtemp(prefix="qa-smart-uv-"), "model.glb")
bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True,
                          use_active_scene=True)
bpy.data.objects.remove(tmp); bpy.data.meshes.remove(me)
result = path
'''


def replay(call_index, glb):
    """Import *glb* and run the captured hook the way a finished job does."""
    return f'''
import shutil, sys, tempfile, os
from mixar.modules.common.job_queue.core.generic_jobs import AsyncGLBJob
from mixar.modules.common.job_queue.core.model_io import import_file
from mixar.modules.common.job_queue.core.queue_download import _pinned_scene
call = sys.modules["qa_smart_uv_state"].calls[{call_index}]
job = AsyncGLBJob(feature_key=call["feature_key"], label=call["label"],
                  job_type=call["job_type"], _on_imported_hook=call["hook"])
job.scene_name = drv.main_window().scene.name
copy = os.path.join(tempfile.mkdtemp(prefix="qa-smart-uv-"), "model.glb")
shutil.copyfile({glb!r}, copy)  # import_file deletes what it imports
with _pinned_scene(job.scene_name, ""):
    names = import_file(copy, "GLB", None)
job.on_imported(names)
hook = call["hook"]
cells = dict(zip(hook.__code__.co_freevars, (c.cell_contents for c in hook.__closure__)))
result = {{"imported": names, "final": job.imported_object_names,
          "hook_box": cells.get("uv_source_bounds", cells.get("source_bounds"))}}
'''


def evaluate(qa, code):
    return qa.eval(textwrap.dedent(code))


def mesh_node_for(qa, lib, name):
    """Select *name* alone, add it to the board, chain a Smart UV node; open it."""
    evaluate(qa, f'''
win = drv.main_window()
for obj in win.view_layer.objects:
    obj.select_set(obj.name == {name!r})
win.view_layer.objects.active = bpy.data.objects[{name!r}]
result = True
''')
    before = qa.eval("result=len(drv.main_window().scene.mixie_moodboard_asset_nodes)")
    host = qa.eval("result=drv.moodboard_host()")
    qa.click(area_type=host["area_type"], text="Add media or selected scene meshes")
    qa.wait("bool(drv.find(popup=True,op='MIXIE_OT_add_selected_mesh_to_moodboard'))", timeout=6)
    qa.click(popup=True, op="MIXIE_OT_add_selected_mesh_to_moodboard")
    qa.wait(f"len(drv.main_window().scene.mixie_moodboard_asset_nodes)=={before + 1}", timeout=6)
    asset = qa.eval("result=drv.main_window().scene.mixie_moodboard_asset_nodes[-1].node_id")
    qa.press("HOME")
    node_id = lib.connect_next_node(qa, asset, "Smart UV")
    lib.open_moodboard_node(qa, node_id)
    return node_id


def generate(qa, node_id):
    """Press the node's real Generate button; return its state and guard calls."""
    node = f"next(n for n in drv.main_window().scene.mixie_moodboard_action_nodes if n.node_id=={node_id!r})"
    before = qa.eval("import sys; result=len(sys.modules['qa_smart_uv_state'].calls)")
    assert qa.eval(
        "from mixar.modules.moodboard.core import node_mesh_execution as nme\n"
        "result=nme.enqueue_generation.__name__=='guard'"), "submit guard missing"
    qa.click(op="MIXIE_OT_moodboard_run_action_node")
    qa.wait(f"{node}.state != 'DRAFT'", timeout=30)
    info = qa.eval(
        f"import sys\nn={node}\ncalls=sys.modules['qa_smart_uv_state'].calls[{before}:]\n"
        "result={'state': n.state, 'error': n.error, 'action_type': n.action_type,"
        " 'calls': [{k: v for k, v in c.items() if k != 'hook'} for c in calls],"
        f" 'call_index': {before}}}")
    # A failed run (refusal or guard) raises Blender's error-report popup at the
    # cursor, which swallows the next click: read it, then dismiss it.
    qa.wait("bool(drv.find(popup=True))", timeout=5)
    info["report_popup"] = [w["text"] for w in qa.find(popup=True)["widgets"] if w.get("text")]
    qa.press("ESC")
    qa.wait("not drv.find(popup=True)", timeout=5)
    return info


def agent_submit(qa, name):
    before = qa.eval("import sys; result=len(sys.modules['qa_smart_uv_state'].calls)")
    out = evaluate(qa, f'''
import sys
w = drv.main_window()
wm = bpy.context.window_manager
wm["mixar_agent_gen_reason"] = ""
with bpy.context.temp_override(window=w, screen=w.screen, scene=w.scene, view_layer=w.view_layer):
    status = bpy.ops.mixie.agent_tripo_uv(object_name={name!r}, bake=True)
calls = sys.modules["qa_smart_uv_state"].calls[{before}:]
result = {{"status": sorted(status), "reason": wm.get("mixar_agent_gen_reason", ""),
          "calls": [{{k: v for k, v in c.items() if k != "hook"}} for c in calls],
          "call_index": {before}}}
''')
    return out


def check_placed(qa, final, fingerprint_before):
    state = evaluate(qa, MEASURE + f'''
result = {{"compare": compare({final!r}),
          "source": fingerprint(bpy.data.objects[{SOURCE!r}])}}
''')
    cmp_ = state["compare"]
    tol = 1e-3 * cmp_["source_size"]
    assert cmp_["box_error"] < tol, cmp_
    assert cmp_["nearest_vertex_max"] < tol, ("orientation/shape mismatch", cmp_)
    assert abs(cmp_["result_scale"][0] - cmp_["result_scale"][2]) < 1e-4, cmp_  # uniform
    assert state["source"] == fingerprint_before, ("source changed", state["source"])
    return cmp_


def close_drawer(qa):
    """The open Moodboard drawer covers the viewport; `~` closes it like a user."""
    if qa.eval("result=bpy.context.window_manager.mixar_moodboard_drawer_amount > 0.01"):
        qa.press("ACCENT_GRAVE")
        qa.wait("bpy.context.window_manager.mixar_moodboard_drawer_amount < 0.01", timeout=5)


def frame_and_snap(qa, out, final, label):
    close_drawer(qa)
    evaluate(qa, f'''
w = drv.main_window()
src, res = bpy.data.objects[{SOURCE!r}], bpy.data.objects[{final!r}]
for obj in w.view_layer.objects:
    if obj.name.startswith({SOURCE!r} + "_uv"):
        obj.hide_set(obj is not res)
src.color, res.color = (0.85, 0.12, 0.1, 1.0), (0.1, 0.95, 0.2, 1.0)
res.display_type, res.show_in_front = 'WIRE', True
area = next(a for a in w.screen.areas if a.type == "VIEW_3D")
region = next(r for r in area.regions if r.type == "WINDOW")
shading = area.spaces.active.shading
shading.type, shading.color_type, shading.wireframe_color_type = 'SOLID', 'OBJECT', 'OBJECT'
for obj in w.view_layer.objects:
    obj.select_set(obj in (src, res))
with bpy.context.temp_override(window=w, area=area, region=region):
    bpy.ops.view3d.view_axis(type="FRONT")
    bpy.ops.view3d.view_selected()
for obj in w.view_layer.objects:
    obj.select_set(False)
result = True
''')
    path = str(out / f"smart-uv-{label}-over-source.png")
    qa.cmd("snap", path=path, area="VIEW_3D")
    return path


def overview_snap(qa, out):
    """Everything in view: the results sit on the Suzanne, none at the origin."""
    evaluate(qa, f'''
w = drv.main_window()
for obj in w.view_layer.objects:
    obj.hide_set(False)
area = next(a for a in w.screen.areas if a.type == "VIEW_3D")
region = next(r for r in area.regions if r.type == "WINDOW")
with bpy.context.temp_override(window=w, area=area, region=region):
    bpy.ops.view3d.view_axis(type="TOP")
    bpy.ops.view3d.view_all()
near_origin = [o.name for o in w.view_layer.objects if o.name.startswith({SOURCE!r} + "_uv")
               and o.matrix_world.translation.length < 1.0]
assert not near_origin, near_origin
result = True
''')
    path = str(out / "smart-uv-overview-top.png")
    qa.cmd("snap", path=path, area="VIEW_3D")
    return path


def run(qa):
    sys.path.insert(0, str(Path(os.environ["QA_HARNESS"]) / "scenarios"))
    import lib

    out = Path(os.environ.get("QA_SCENARIO_OUT", tempfile.mkdtemp(prefix="qa-smart-uv-")))
    out.mkdir(parents=True, exist_ok=True)
    assert evaluate(qa, 'import os; result = os.environ.get("MIXAR_QA") == "1"')
    qa.cmd("wait_login", timeout=90)
    qa.wait(lib.CATALOG_LOADED, timeout=45)
    lib.ensure_scenes_drawer(qa)
    lib.ensure_moodboard_area(qa)
    evidence = {"fixtures": qa.step("fixtures", evaluate, qa, FIXTURES)}
    assert evidence["fixtures"][SUBSURF]["base"] == 12, evidence
    assert evidence["fixtures"][DECIMATE]["base"] == 100_000, evidence
    fp = evaluate(qa, MEASURE + f"result = fingerprint(bpy.data.objects[{SOURCE!r}])")
    glb = os.environ.get("QA_SMART_UV_GLB") or qa.step("write result glb", evaluate, qa, WRITE_GLB)
    evidence["result_glb"] = glb
    qa.step("install submit guard", evaluate, qa, GUARD)
    try:
        # Bug 2 through the real node and Generate button.
        sub = qa.step("subsurf node", mesh_node_for, qa, lib, SUBSURF)
        evidence["subsurf_node"] = r = qa.step("subsurf generate", generate, qa, sub)
        assert r["calls"] and r["calls"][0]["glb_triangles"] == 12, r
        assert "QA GUARD" in r["error"] and "196,608" not in r["error"], r
        dec = qa.step("decimate node", mesh_node_for, qa, lib, DECIMATE)
        evidence["decimate_node"] = r = qa.step("decimate generate", generate, qa, dec)
        assert r["state"] == "FAILED" and not r["calls"], r
        assert "80,000" in r["error"] and "100,000" in r["error"], r
        qa.cmd("snap", path=str(out / "smart-uv-decimate-refused.png"), area="VIEW_3D")
        # ... and through the agent operator.
        evidence["agent_subsurf"] = r = agent_submit(qa, SUBSURF)
        assert r["calls"] and r["calls"][0]["glb_triangles"] == 12, r
        evidence["agent_decimate"] = r = agent_submit(qa, DECIMATE)
        assert not r["calls"] and "100,000" in r["reason"], r

        # Bug 1: submit the Suzanne from its node, replay the finished job.
        node = qa.step("source node", mesh_node_for, qa, lib, SOURCE)
        r = qa.step("source generate", generate, qa, node)
        assert r["calls"] and r["calls"][0]["glb_triangles"] == 968, r
        rep = qa.step("node replay", evaluate, qa, replay(r["call_index"], glb))
        evidence["node_replay"] = rep
        assert rep["final"] == f"{SOURCE}_uv", rep
        evidence["node_placed"] = qa.step(
            "node result over source", check_placed, qa, rep["final"], fp)
        embedded = qa.eval(
            f"n=next(n for n in drv.main_window().scene.mixie_moodboard_action_nodes "
            f"if n.node_id=={node!r})\nresult=getattr(n.preview_object,'name','')")
        assert embedded == rep["final"], embedded
        snaps = [frame_and_snap(qa, out, rep["final"], "node")]

        # Bug 1 through the agent operator.
        r = qa.step("agent submit", agent_submit, qa, SOURCE)
        assert r["calls"] and r["calls"][0]["glb_triangles"] == 968, r
        rep = qa.step("agent replay", evaluate, qa, replay(r["call_index"], glb))
        evidence["agent_replay"] = rep
        assert rep["final"] == f"{SOURCE}_uv.001", rep
        evidence["agent_placed"] = qa.step(
            "agent result over source", check_placed, qa, rep["final"], fp)
        snaps.append(frame_and_snap(qa, out, rep["final"], "agent"))
        snaps.append(overview_snap(qa, out))
    finally:
        evidence["guard_restored"] = qa.step("restore submit", evaluate, qa, RESTORE)
    assert evidence["guard_restored"] is True
    (out / "smart-uv-evidence.json").write_text(json.dumps(evidence, indent=2, default=str))
    return {"snapshots": snaps, "evidence": str(out / "smart-uv-evidence.json"),
            "backend_submissions": 0, "credits_spent": 0}


if __name__ == "__main__":
    sys.path.insert(0, str(Path(os.environ["QA_HARNESS"]) / "scenarios"))
    from lib import run_scenario

    run_scenario("smart_uv_placement_tricount", run)
