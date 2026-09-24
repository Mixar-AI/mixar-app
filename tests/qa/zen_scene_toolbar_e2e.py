#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit Zen toolbar replay. Use an isolated QA app and inspect the PNGs.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4891 \
    QA_SCENARIO_OUT=/tmp/zen-toolbar python3 tests/qa/zen_scene_toolbar_e2e.py
"""

import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ["QA_HARNESS"]) / "scenarios"))
from lib import run_scenario  # noqa: E402

OUT = Path(os.environ.get("QA_SCENARIO_OUT", "/tmp/zen-toolbar"))
HEADER = {"area_type": "VIEW_3D", "region_type": "HEADER"}
SETUP = """
win = drv.main_window()
scene = win.scene
area = next(a for a in win.screen.areas if a.type == 'VIEW_3D')
view = area.spaces.active
"""


def reset_zen_scene(qa):
    """The installed harness still expects a retired MIXIE startup area.

    Use the same real home-file reset but assert today's Zen viewport instead.
    Re-query temporary windows after every close; never retain freed RNA.
    """
    # The QA socket opens before time-budgeted UI registration has completed.
    qa.wait("hasattr(drv.main_window().scene, 'mixie_chat_is_busy') and "
            "hasattr(bpy.types, 'MIXAR_OT_zen_set_sky') and "
            "hasattr(bpy.types, 'MIXAR_PT_zen_render_settings')", timeout=30)
    qa.eval("""
import os
assert os.environ.get('MIXAR_QA') == '1'
assert not drv.main_window().scene.mixie_chat_is_busy
def reset():
    while True:
        main=drv.main_window()
        extra=next((w for w in bpy.context.window_manager.windows if w != main), None)
        if extra is None:
            break
        with bpy.context.temp_override(window=extra):
            bpy.ops.wm.window_close()
        yield .1
    with bpy.context.temp_override(window=drv.main_window()):
        bpy.ops.wm.read_homefile()
    drv.reset_runtime_state()
    yield .5
    return True
result=reset()
""")
    qa.wait("drv.main_window().workspace.name == 'Zen Mode' and bool(drv.find(text='Add Objects', area_type='VIEW_3D'))", timeout=12)


def snap(qa, name):
    qa.cmd("snap", path=str(OUT / (name + ".png")), area="VIEW_3D")


def choose_engine(qa, label, value):
    qa.cmd("choose", widget={**HEADER, "prop": "engine"}, item=label)
    qa.wait(f"drv.main_window().scene.render.engine == {value!r}", timeout=8)


def layout(qa):
    widgets = qa.find(**HEADER)["widgets"]
    geometry = qa.eval(SETUP + """
r = next(r for r in area.regions if r.type == 'HEADER')
result = [r.x, r.y, r.width, r.height, bpy.context.preferences.system.ui_scale]
""")
    x, y, width, height, scale = geometry
    assert abs(height / scale - 54 * .85) <= 1, geometry
    interactive = [w for w in widgets if w["type"] not in ("Label", "Other")]
    for w in interactive:
        x0, y0, x1, y1 = w["rect"]
        assert x <= x0 < x1 <= x + width, w
        assert y <= y0 < y1 <= y + height, w
        assert "…" not in w.get("text", ""), w
    ordered = sorted(interactive, key=lambda w: w["rect"][0])
    for a, b in zip(ordered, ordered[1:]):
        assert a["rect"][2] <= b["rect"][0] + 1, (a, b)
    assert any(w.get("text") == "Add Objects" for w in widgets)
    assert any(w.get("text") == "Export" for w in widgets)
    snap(qa, "toolbar-default")
    targets = qa.cmd("snap", path=str(OUT / "toolbar-targets.png"),
                     area="VIEW_3D", annotate=HEADER)
    (OUT / "toolbar-targets.json").write_text(json.dumps(targets, indent=2) + "\n")
    return {"controls": len(interactive), "geometry": geometry}


def add_object(qa):
    # Keep the new primitive visibly outside the startup cube.
    qa.eval("drv.main_window().scene.cursor.location=(3,0,0); result=True")
    before = qa.eval("result=len(bpy.data.objects)")
    qa.click(**HEADER, text="Add Objects")
    qa.click(popup=True, text="Mesh")
    qa.click(popup=True, op="MESH_OT_primitive_uv_sphere_add")
    qa.wait(f"len(bpy.data.objects) == {before + 1}", timeout=6)
    result = qa.eval(SETUP + """
obj = win.view_layer.objects.active
assert obj.type == 'MESH' and len(obj.data.vertices) > 100
obj.name = 'QA_Zen_Sphere'
with bpy.context.temp_override(window=win, area=area,
    region=next(r for r in area.regions if r.type == 'WINDOW')):
    bpy.ops.view3d.view_selected()
result = obj.name
""")
    snap(qa, "added-object")
    return result


def render_settings(qa):
    for label, engine, prop, expr, value in (
        ("Cycles", "CYCLES", "samples", "scene.cycles.samples", 32),
        ("EEVEE", "BLENDER_EEVEE", "taa_render_samples", "scene.eevee.taa_render_samples", 48),
    ):
        choose_engine(qa, label, engine)
        qa.cmd("set_text", widget={**HEADER, "prop": prop}, text=str(value))
        assert qa.eval(SETUP + f"result={expr}") == value
        qa.cmd("set_text", widget={**HEADER, "prop": prop}, text="999", enter=False)
        qa.press("ESC")
        assert qa.eval(SETUP + f"result={expr}") == value, "Escape did not cancel the edit"
        snap(qa, "samples-" + engine.lower())
    choose_engine(qa, "Workbench", "BLENDER_WORKBENCH")
    qa.cmd("choose", widget={**HEADER, "prop": "render_aa"}, item="32 Samples")
    assert qa.eval(SETUP + "result=scene.display.render_aa") == "32"
    assert all(not w["enabled"] for w in qa.find(**HEADER, op="MIXAR_OT_zen_set_sky")["widgets"])
    snap(qa, "workbench")
    choose_engine(qa, "Cycles", "CYCLES")
    assert qa.eval(SETUP + "result=scene.cycles.samples") == 32
    choose_engine(qa, "EEVEE", "BLENDER_EEVEE")
    return {"cycles": 32, "eevee": 48, "workbench": "32", "cancel": True}


def sample_range(qa):
    results = {}
    for label, engine, prop, owner, maximum in (
        ("Cycles", "CYCLES", "samples", "scene.cycles", 1024),
        ("EEVEE", "BLENDER_EEVEE", "taa_render_samples", "scene.eevee", 256),
    ):
        choose_engine(qa, label, engine)
        query = {**HEADER, "prop": prop}
        expr = f"{owner}.{prop}"
        saved = qa.eval(SETUP + f"result={expr}")
        native_range = qa.eval(SETUP + f"""
p = {owner}.bl_rna.properties[{prop!r}]
result = [p.hard_min, p.hard_max, p.soft_min, p.soft_max]
""")
        try:
            # High typed values survive redraws; the short drag track stays bounded.
            qa.cmd("set_text", widget=query, text=str(maximum * 4))
            qa.eval(SETUP + "area.tag_redraw(); result=True")
            assert qa.eval(SETUP + f"result={expr}") == maximum * 4
            snap(qa, "samples-high-" + engine.lower())
            qa.cmd("set_text", widget=query, text="1")
            for direction, expected in ((1, maximum), (-1, 1)):
                actual = qa.eval(SETUP + f"""
def drag_sample():
    target = drv.find_one(**{query!r})
    x, y = target['center']
    width = target['rect'][2] - target['rect'][0]
    yield from drv.drag_xy_steps(target['_win'], x, y, x + {direction} * width * 1.4, y)
    yield .2
    return {expr}
result = drag_sample()
""")
                assert actual == expected, (engine, direction, actual, expected)
            qa.cmd("set_text", widget=query, text=str(maximum // 2))
            snap(qa, "samples-midpoint-" + engine.lower())
            assert qa.eval(SETUP + f"result={expr}") == maximum // 2
            after = qa.eval(SETUP + f"""
p = {owner}.bl_rna.properties[{prop!r}]
result = [p.hard_min, p.hard_max, p.soft_min, p.soft_max]
""")
            assert after == native_range, "Zen changed a global RNA property range"
            results[engine] = {"drag": [1, maximum], "typed": maximum * 4,
                               "native_range_unchanged": True}
        finally:
            qa.cmd("set_text", widget=query, text=str(saved))
    return results


def playback(qa):
    qa.eval(SETUP + """
obj = win.view_layer.objects.active
obj.keyframe_insert(data_path='location', frame=1)
obj.keyframe_insert(data_path='location', frame=12)
scene.frame_start = 1
scene.frame_end = 24
scene.frame_set(1)
result=True
""")
    for index, frame in ((1, 12), (0, 1)):
        qa.eval(f"""
def click():
    buttons = sorted(drv.find(op='SCREEN_OT_keyframe_jump', **{HEADER!r}), key=lambda w:w['rect'][0])
    yield from drv.click_steps(buttons[{index}])
    yield .2
    return drv.main_window().scene.frame_current
result=click()
""")
        assert qa.eval("result=drv.main_window().scene.frame_current") == frame
    qa.click(**HEADER, op="SCREEN_OT_animation_play")
    qa.wait("drv.main_window().screen.is_animation_playing and drv.main_window().scene.frame_current > 1", timeout=6)
    snap(qa, "playing")
    qa.click(**HEADER, op="SCREEN_OT_animation_play")
    qa.wait("not drv.main_window().screen.is_animation_playing", timeout=6)
    return {"previous_next": [1, 12], "play_pause": True}


def view_controls(qa):
    before = qa.eval(SETUP + "result=view.shading.show_xray")
    qa.click(**HEADER, prop="show_xray")
    assert qa.eval(SETUP + "result=view.shading.show_xray") != before
    qa.click(**HEADER, prop="show_xray")
    assert qa.eval(SETUP + "result=view.shading.show_xray") == before
    before = qa.eval(SETUP + "result=view.overlay.show_floor")
    qa.click(**HEADER, but_type="Popover")
    qa.click(popup=True, op="MIXAR_OT_zen_toggle_guides")
    qa.press("ESC")
    assert qa.eval(SETUP + "result=view.overlay.show_floor") != before
    qa.click(**HEADER, but_type="Popover")
    qa.click(popup=True, op="MIXAR_OT_zen_toggle_guides")
    qa.press("ESC")
    assert qa.eval(SETUP + "result=view.overlay.show_floor") == before
    return {"xray": True, "shading_popover_guides": True}


def sky(qa):
    saved = qa.eval(SETUP + """
original = scene.world
original['qa_zen_preserve'] = 'original-world'
view.shading.use_scene_world = False
view.shading.use_scene_world_render = True
result = {'name':original.name, 'nodes':len(original.node_tree.nodes)}
""")
    qa.click(**HEADER, op="MIXAR_OT_zen_set_sky", text="ON")
    qa.wait("drv.main_window().scene.world == drv.main_window().scene.mixar_zen_sky.sky_world", timeout=6)
    data = qa.eval(SETUP + """
assert scene.mixar_zen_sky.previous_world['qa_zen_preserve'] == 'original-world'
assert any(n.type == 'TEX_SKY' for n in scene.world.node_tree.nodes)
assert len(scene.world.node_tree.links) == 2
assert view.shading.use_scene_world and view.shading.use_scene_world_render
result={'world':scene.world.name, 'worlds':len(bpy.data.worlds)}
""")
    # Select Material Preview through its native shading enum for visible proof.
    qa.eval(f"""
def preview():
    widgets=sorted(drv.find(prop='type', **{HEADER!r}),key=lambda w:w['rect'][0])
    yield from drv.click_steps(widgets[2])
    yield 2
    return True
result=preview()
""")
    snap(qa, "sky-on")
    qa.click(**HEADER, op="MIXAR_OT_zen_set_sky", text="OFF")
    assert qa.eval(SETUP + "result=scene.world.name") == saved["name"]
    assert qa.eval(SETUP + "result=len(scene.world.node_tree.nodes)") == saved["nodes"]
    assert qa.eval(SETUP + "result=[view.shading.use_scene_world, view.shading.use_scene_world_render]") == [False, True]
    snap(qa, "sky-off")
    qa.click(**HEADER, op="MIXAR_OT_zen_set_sky", text="ON")
    assert qa.eval("result=len(bpy.data.worlds)") == data["worlds"], "Toggle leaked worlds"
    qa.click(**HEADER, op="MIXAR_OT_zen_set_sky", text="OFF")
    qa.eval(SETUP + "scene.world=None; result=True")
    qa.click(**HEADER, op="MIXAR_OT_zen_set_sky", text="ON")
    qa.click(**HEADER, op="MIXAR_OT_zen_set_sky", text="OFF")
    assert qa.eval(SETUP + "result=scene.world is None")
    qa.eval(SETUP + f"scene.world=bpy.data.worlds[{saved['name']!r}]; view.shading.type='SOLID'; result=True")
    return {**data, "restored": saved["name"], "none_restored": True}


def export_scene(qa):
    path = OUT / f"zen-toolbar-export-{time.time_ns()}.obj"
    qa.click(**HEADER, text="Export")
    qa.click(popup=True, op="MIXAR_OT_export_native_obj")
    qa.wait("bool(drv.find(area_type='FILE_BROWSER', prop='filename'))", timeout=10)
    # Seed the fixture destination: Blender's live path autocomplete consumes
    # batched slash-path keystrokes. Confirmation still uses the native button.
    qa.eval(f"""
h=drv.find(area_type='FILE_BROWSER', prop='directory')[0]
params=h['_area'].spaces.active.params
params.directory={str(OUT).encode()!r}
params.filename={path.name!r}
result=True
""")
    qa.click(area_type="FILE_BROWSER", prop="directory")
    window = qa.find(area_type="FILE_BROWSER", prop="directory")["widgets"][0]["window"]
    qa.press("RET", window=window)
    qa.click(area_type="FILE_BROWSER", op="FILE_OT_execute")
    qa.wait("not any(a.type == 'FILE_BROWSER' for w in bpy.context.window_manager.windows for a in w.screen.areas)", timeout=12)
    data = path.read_text()
    assert "v " in data and "f " in data and "QA_Zen_Sphere" in data
    qa.click(**HEADER, text="Export")
    qa.click(popup=True, op="MIXAR_OT_export_native_obj")
    qa.wait("bool(drv.find(area_type='FILE_BROWSER', prop='filename'))", timeout=10)
    qa.click(area_type="FILE_BROWSER", op="FILE_OT_cancel")
    qa.wait("bool(drv.find(area_type='VIEW_3D', text='Add Objects'))", timeout=8)
    return {"file": str(path), "bytes": path.stat().st_size, "cancel": True}


def compact(qa):
    saved = qa.eval("result=bpy.context.preferences.view.ui_scale")
    qa.eval(f"bpy.context.preferences.view.ui_scale={saved * 1.5!r}; result=True")
    try:
        qa.wait("bool(drv.find(text='Render Settings', region_type='HEADER'))", timeout=8)
        snap(qa, "toolbar-compact")
        qa.click(**HEADER, text="Render Settings")
        qa.cmd("set_text", widget={"popup": True, "prop": "taa_render_samples"}, text="24")
        assert qa.eval(SETUP + "result=scene.eevee.taa_render_samples") == 24
        snap(qa, "compact-render-settings")
        qa.press("ESC")
        qa.click(**HEADER, text="Sky Light")
        qa.click(popup=True, op="MIXAR_OT_zen_set_sky", text="ON")
        qa.press("ESC")
        assert qa.eval(SETUP + "result=scene.world == scene.mixar_zen_sky.sky_world")
        qa.click(**HEADER, text="Sky Light")
        qa.click(popup=True, op="MIXAR_OT_zen_set_sky", text="OFF")
        qa.press("ESC")
        return {"scale": saved * 1.5, "render_samples": 24, "sky": True}
    finally:
        qa.eval(f"bpy.context.preferences.view.ui_scale={saved!r}; result=True")


def persistence(qa):
    original = qa.eval(SETUP + "result=scene.world.name")
    flags = qa.eval(SETUP + "result=[view.shading.use_scene_world, view.shading.use_scene_world_render]")
    qa.click(**HEADER, op="MIXAR_OT_zen_set_sky", text="ON")
    qa.click(area_type="TOPBAR", text="Edit")
    qa.click(popup=True, op="ED_OT_undo")
    qa.wait(f"drv.main_window().scene.world.name == {original!r}", timeout=6)
    assert qa.eval(SETUP + "result=[view.shading.use_scene_world, view.shading.use_scene_world_render]") == flags
    qa.click(area_type="TOPBAR", text="Edit")
    qa.click(popup=True, op="ED_OT_redo")
    qa.wait("drv.main_window().scene.world == drv.main_window().scene.mixar_zen_sky.sky_world", timeout=6)
    assert qa.eval(SETUP + "result=[view.shading.use_scene_world, view.shading.use_scene_world_render]") == [True, True]
    path = OUT / "sky-persistence.mixar"
    qa.eval(f"result=str(bpy.ops.wm.save_as_mainfile(filepath={str(path)!r}, check_existing=False))")
    assert path.exists()
    qa.eval(f"result=str(bpy.ops.wm.open_mainfile(filepath={str(path)!r}))")
    qa.wait("bool(drv.find(text='ON', op='MIXAR_OT_zen_set_sky'))", timeout=12)
    assert qa.eval(SETUP + "result=scene.world == scene.mixar_zen_sky.sky_world")
    qa.click(**HEADER, op="MIXAR_OT_zen_set_sky", text="OFF")
    assert qa.eval(SETUP + "result=scene.world.name") == original
    assert qa.eval(SETUP + "result=[view.shading.use_scene_world, view.shading.use_scene_world_render]") == flags
    snap(qa, "sky-restored-after-reopen")
    return {"undo_redo": True, "reopened": str(path), "restored": original}


def mode_boundary(qa):
    centers = []
    for op in ("MIXAR_OT_set_ui_mode_pro", "MIXAR_OT_set_ui_mode_ai"):
        qa.click(area_type="TOPBAR", op=op)
        zen = op.endswith("_ai")
        qa.wait(f"(drv.main_window().workspace.name == 'Zen Mode') == {zen!r}", timeout=8)
        if zen:
            qa.wait("bool(drv.find(text='Add Objects', area_type='VIEW_3D'))", timeout=8)
        else:
            qa.wait("bool(drv.find(prop='ui_type', area_type='VIEW_3D', region_type='HEADER'))", timeout=8)
            assert not qa.find(text="Add Objects", **HEADER)["total"]
        left = qa.find(area_type="TOPBAR", op="MIXAR_OT_set_ui_mode_ai")["widgets"][0]["rect"]
        right = qa.find(area_type="TOPBAR", op="MIXAR_OT_set_ui_mode_pro")["widgets"][0]["rect"]
        width = qa.eval("result=max(a.x+a.width for a in drv.main_window().screen.areas)")
        center = (left[0] + right[2]) / 2
        assert abs(center - width / 2) <= 2, (left, right, width)
        centers.append(center)
    assert abs(centers[0] - centers[1]) <= 1, centers
    return {"engine_stock_header": True, "mode_centers": centers}


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    reset_zen_scene(qa)
    qa.eval("""
import os
assert os.environ.get('MIXAR_QA') == '1', 'Use an isolated QA profile'
from mixar.modules.agent_bubble.ui.operators import hover_ops
hover_ops.unregister()
bpy.context.preferences.view.show_tooltips=False
bpy.context.window_manager.mixar_zen_sample_target='RENDER'
drv.main_window().workspace=bpy.data.workspaces['Zen Mode']
result=True
""")
    qa.wait("bool(drv.find(text='Add Objects', region_type='HEADER'))", timeout=10)
    checks = {}
    for name, fn in (("layout", layout), ("add-object", add_object),
                     ("render-settings", render_settings), ("sample-range", sample_range),
                     ("view-controls", view_controls),
                     ("playback", playback),
                     ("sky", sky), ("export", export_scene), ("compact", compact),
                     ("persistence", persistence), ("mode-boundary", mode_boundary)):
        checks[name] = qa.step(name, fn, qa)
    snap(qa, "toolbar-final")
    verdict = {"checks": checks, "paid_requests": 0, "artifacts": str(OUT)}
    (OUT / "verdict.json").write_text(json.dumps(verdict, indent=2) + "\n")
    return verdict


if __name__ == "__main__":
    run_scenario("zen_scene_toolbar_e2e", run)
