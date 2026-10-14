# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Render and viewport cases: first Engine switch after the shader warm-up
(3.6), main-loop responsiveness during a render (3.7), the agent's preview
renders a private scene copy (3.9). No credits are spent."""

from __future__ import annotations

import json
import time
import uuid

from common import call_from_timer, jitter, mean_luminance, stall_seq, stalls_since, undo_mods, main_view3d_window

# Mean RGB measured on macOS: the black Rendered viewport ("Loading render
# kernels") 0.073, the normal EEVEE view of the cube ring 0.237-0.247.
# The cut-off sits halfway. See the calibration in the README.
BLACK_VIEWPORT_MAX = 0.15


def engine_switch_prewarm(c):
    """3.6: the display shaders are compiled at idle, so the first Engine switch is short."""
    qa = c.qa
    qa.wait("__import__('time').monotonic() > 0 and bpy.context.window_manager.get('mixar_prewarm_display_shaders', None) is not None",
            timeout=20)
    qa.wait("not bpy.context.window_manager.get('mixar_prewarm_display_shaders')", timeout=20)
    seq = stall_seq(qa)
    qa.eval(__import__("common").JITTER_START)
    call_from_timer(qa, "bpy.ops.mixar.set_ui_mode_pro()", delay=0.3)
    time.sleep(3.0)
    gaps = qa.eval(__import__("common").JITTER_READ)
    stalls = stalls_since(qa, seq)
    worst = max([s["ms"] for s in stalls] or [0])
    c.numbers.update(first_switch_max_gap_ms=gaps["max_gap_ms"], first_switch_worst_stall_ms=worst,
                     stalls=[f"{s['ms']}ms {s['culprit'][:60]}" for s in stalls])
    workspace = qa.eval("result = bpy.context.window_manager.windows[0].workspace.name")
    assert workspace != "Zen Mode", "Engine switch did not happen"
    assert gaps["max_gap_ms"] < 1500, f"first Engine switch froze for {gaps['max_gap_ms']} ms (fixed build: ~500 ms)"


def render_responsive(c):
    """3.7: a render job must not starve the main loop (the macOS Dock progress
    icon re-render took 68% of it). Measured on every platform."""
    qa = c.qa
    idle = jitter(qa, 2.0)
    qa.eval('''
import bpy
s = bpy.context.window.scene
s.render.engine = 'CYCLES'
s.cycles.samples = 24
s.render.resolution_x, s.render.resolution_y, s.render.resolution_percentage = 480, 270, 100
bpy.context.preferences.view.render_display_type = 'NONE'
result = True
''')
    qa.eval(__import__("common").JITTER_START)
    call_from_timer(qa, "bpy.ops.render.render('INVOKE_DEFAULT')", delay=0.2)
    time.sleep(1.0)
    qa.wait("not bpy.app.is_job_running('RENDER')", timeout=120)
    during = qa.eval(__import__("common").JITTER_READ)
    idle_rate = idle["ticks"] / max(idle["seconds"], 0.1)
    render_rate = during["ticks"] / max(during["seconds"], 0.1)
    ratio = round(render_rate / max(idle_rate, 1e-6), 2)
    c.numbers.update(idle_ticks_per_s=round(idle_rate), render_ticks_per_s=round(render_rate),
                     tick_ratio=ratio, render_max_gap_ms=during["max_gap_ms"], render_seconds=during["seconds"])
    assert during["max_gap_ms"] < 1000, f"main loop froze {during['max_gap_ms']} ms during the render"
    assert ratio >= 0.4, f"main loop ran at {ratio:.0%} of its idle rate during the render (before the fix: ~30%)"


_SCENE = '''
import bpy, math, mathutils
cols = [(0.1,0.7,0.9,1),(0.6,0.3,0.9,1),(0.95,0.3,0.6,1),(0.95,0.5,0.2,1),(0.5,0.85,0.3,1)]
mats = []
for i, col in enumerate(cols):
    m = bpy.data.materials.new('qa_col_%d' % i); m.use_nodes = True
    m.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = col
    mats.append(m)
win = bpy.context.window
with bpy.context.temp_override(window=win, screen=win.screen, scene=win.scene):
    for i in range(20):
        a = 2 * math.pi * i / 20
        bpy.ops.mesh.primitive_cube_add('EXEC_DEFAULT', True, size=0.8, location=(4*math.cos(a), 4*math.sin(a), 0.4))
        bpy.context.active_object.data.materials.append(mats[i % 5])
for area in win.screen.areas:
    if area.type == 'VIEW_3D':
        sp = area.spaces.active
        sp.shading.type = 'RENDERED'
        sp.region_3d.view_distance = 14
        sp.region_3d.view_rotation = mathutils.Euler((math.radians(55), 0, math.radians(30))).to_quaternion()
        sp.region_3d.view_location = (0, 0, 0)
result = True
'''

_STATE = '''
import bpy
from mixar.modules.space_mixie_chat.constants import is_internal_scene
from mixar.modules.space_mixie_chat.ui.operators.scene_tab_ops import ordered_tabs
s = bpy.context.window.scene
result = {'engine': s.render.engine, 'world': s.world.name if s.world else None,
          'camera': s.camera.name if s.camera else None, 'res': [s.render.resolution_x, s.render.resolution_y],
          'internal': [x.name for x in bpy.data.scenes if is_internal_scene(x)],
          'tabs': [x.name for x in ordered_tabs()], 'job': bpy.app.is_job_running('RENDER'),
          'rig_objects_in_user_scene': [o.name for o in s.objects if o.name.startswith('_rv_')]}
'''


def _start_preview(qa, inspection: bool) -> str:
    key = uuid.uuid4().hex
    if inspection:
        params = json.dumps({'width': 960, 'height': 720, 'shading': 'material', 'view': 'hero',
                             'focus_point': [0, 0, 0.4], 'focus_radius': 6})
        call = f"bpy.ops.mixie_chat.agent_preview_render(job_key={key!r}, inspection_json={params!r}, max_faces=65000000)"
    else:
        call = f"bpy.ops.mixie_chat.agent_preview_render(job_key={key!r}, width=1920, height=1080, engine='auto', max_faces=65000000)"
    call_from_timer(qa, call, delay=0.05)
    return key


def _result(qa, key: str) -> dict:
    return qa.eval("from mixar.modules.space_mixie_chat.core import preview_render as p\n"
                   f"r = dict(p.poll({key!r}))\n"
                   "result = {k: v for k, v in r.items() if k in ('status', 'error', 'engine')}")


def preview_private_scene(c):
    """3.9: the agent's inspection and final renders leave the user's scene and
    Rendered viewport untouched; the private copy never shows as a tab and is
    removed afterwards, also when undo cancels a render."""
    qa = c.qa
    qa.eval(_SCENE)
    time.sleep(5.0)
    before = qa.eval(_STATE)
    qa.cmd("snap", path=str(c.out / "0_before.png"), area_type="VIEW_3D")
    c.numbers["luminance_before"] = mean_luminance(qa, c.out / "0_before.png")
    for kind in ("inspection", "final"):
        key = _start_preview(qa, kind == "inspection")
        mid, t0 = None, time.time()
        while mid is None and time.time() - t0 < 6.0:   # catch the job while it runs
            state = qa.eval(_STATE)
            if state["job"] and state["internal"] and time.time() - t0 > 0.6:
                mid = state
            time.sleep(0.1)
        assert mid is not None, f"{kind}: never saw the render running with its private scene"
        qa.cmd("snap", path=str(c.out / f"{kind}_during.png"), area_type="VIEW_3D")
        lum = mean_luminance(qa, c.out / f"{kind}_during.png")
        qa.wait("not bpy.app.is_job_running('RENDER')", timeout=120)
        qa.wait(f"__import__('mixar.modules.space_mixie_chat.core.preview_render', fromlist=['x']).poll({key!r})['status'] != 'running'", timeout=30)
        res, after = _result(qa, key), qa.eval(_STATE)
        c.numbers[f"{kind}_luminance_during"] = lum
        c.numbers[f"{kind}_result"] = res.get("status")
        for label, st in (("during", mid), ("after", after)):
            for field in ("engine", "world", "camera", "res"):
                assert st[field] == before[field], f"{kind} {label}: user scene {field} changed {before[field]} -> {st[field]}"
            assert st["tabs"] == before["tabs"], f"{kind} {label}: scene tabs changed {st['tabs']}"
            assert not st["rig_objects_in_user_scene"], f"{kind} {label}: rig objects in the user scene"
        assert not after["internal"], f"{kind}: private scene left behind {after['internal']}"
        assert res.get("status") == "done", f"{kind}: render result {res}"
        assert lum > BLACK_VIEWPORT_MAX, f"{kind}: viewport looks black during the render (luminance {lum})"
    # Undo in the middle of an inspection: the job is cancelled, the copy is removed.
    win = main_view3d_window(qa)
    qa.eval("w = drv.find_one(area_type='VIEW_3D'); x, y = drv.pick_click_point(w); w['_win'].cursor_warp(x, y); result = True")
    qa.eval("import bpy\nwin = bpy.context.window\n"
            "with bpy.context.temp_override(window=win, screen=win.screen, scene=win.scene):\n"
            "    bpy.ops.mesh.primitive_cube_add('EXEC_DEFAULT', True, location=(0, 0, 3))\nresult = True")
    key = _start_preview(qa, True)
    time.sleep(1.2)
    qa.press("Z", window=win, **undo_mods())
    qa.wait("not bpy.app.is_job_running('RENDER')", timeout=60)
    time.sleep(2.0)
    after = qa.eval(_STATE)
    c.numbers["undo_mid_render_result"] = _result(qa, key)
    assert not after["internal"], f"undo mid-render left a private scene {after['internal']}"
    assert after["engine"] == before["engine"], "undo mid-render changed the user's engine"
