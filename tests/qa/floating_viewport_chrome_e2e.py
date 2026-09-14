#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit native shading/header regression; requires an isolated Dev QA app.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4879 \
    QA_SCENARIO_OUT=/tmp/floating-chrome python3 tests/qa/floating_viewport_chrome_e2e.py

All control clicks resolve native RNA widgets or the drawer's QA targets.
Inspect the emitted PNGs as well as the state verdict.
"""

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ["QA_HARNESS"]) / "scenarios"))
from lib import run_scenario  # noqa: E402

OUT = Path(os.environ.get("QA_SCENARIO_OUT", "/tmp/floating-chrome"))
VIEW = {"area_type": "VIEW_3D", "region_type": "HEADER", "prop": "type"}
SETUP = """
win = drv.main_window()
area = next(a for a in win.screen.areas if a.type == 'VIEW_3D')
view = area.spaces.active
"""


def workspace(qa, name):
    qa.eval(f"""
def switch():
    win = drv.main_window()
    win.workspace = bpy.data.workspaces[{name!r}]
    yield .5
    return win.workspace.name
result = switch()
""")
    qa.wait(f"len(drv.find(**{VIEW!r})) >= 3", timeout=10)


def snap(qa, name):
    return qa.cmd("snap", path=str(OUT / (name + ".png")), area="VIEW_3D")


def shading_clicks(qa, engine, expected):
    qa.eval(f"drv.main_window().scene.render.engine = {engine!r}; result=True")
    qa.wait(f"len(drv.find(**{VIEW!r})) == {len(expected)}", timeout=10)
    result = qa.eval(SETUP + f"""
def click_all():
    values = []
    for index, expected in enumerate({expected!r}):
        # RNA expansion preserves enum order. Re-resolve live widgets before
        # every click; never infer pixel positions or set the shading value.
        widgets = sorted(drv.find(**{VIEW!r}), key=lambda w: w['rect'][0])
        assert all(w['type'] == 'Row' and not w.get('op') for w in widgets)
        yield from drv.click_steps(widgets[index])
        yield .25
        assert view.shading.type == expected, (expected, view.shading.type)
        widgets = sorted(drv.find(**{VIEW!r}), key=lambda w: w['rect'][0])
        assert [i for i, w in enumerate(widgets) if w.get('sel')] == [index]
        values.append(view.shading.type)
    # Return to Solid through its real button too.
    yield from drv.click_steps(sorted(drv.find(**{VIEW!r}), key=lambda w: w['rect'][0])[1])
    yield .25
    return values
result = click_all()
""")
    assert result == expected, result
    snap(qa, "engine-" + engine.lower())
    return result


def align_headers(qa, alignment):
    return qa.eval(SETUP + f"""
def align():
    for region in area.regions:
        if region.type in ('HEADER', 'TOOL_HEADER') and region.alignment != {alignment!r}:
            with bpy.context.temp_override(window=win, area=area, region=region):
                assert bpy.ops.screen.region_flip() == {{'FINISHED'}}
    yield .4
    return True
result = align()
""")


def separate_headers(qa):
    rects = qa.eval(SETUP + """
rect = lambda r: [r.x, r.y, r.x+r.width, r.y+r.height]
result = {r.type: rect(r) for r in area.regions if r.type in ('HEADER', 'TOOL_HEADER')}
""")
    header, tools = rects["HEADER"], rects["TOOL_HEADER"]
    assert header[3] - header[1] > 1 and tools[3] - tools[1] > 1, rects
    assert header[3] <= tools[1] or tools[3] <= header[1], rects
    before = qa.eval(SETUP + """
result = {'shading': view.shading.type,
          'mirror': win.view_layer.objects.active.use_mesh_mirror_z}
""")
    qa.click(area_type="VIEW_3D", region_type="TOOL_HEADER", prop="use_mesh_mirror_z")
    qa.wait(f"drv.main_window().view_layer.objects.active.use_mesh_mirror_z == {not before['mirror']!r}",
            timeout=5)
    after = qa.eval(SETUP + "result=view.shading.type")
    assert after == before["shading"], (before, after)
    qa.click(area_type="VIEW_3D", region_type="TOOL_HEADER", prop="use_mesh_mirror_z")
    return rects


def texturing(qa):
    workspace(qa, "Texturing")
    saved = qa.eval(SETUP + """
result = {'header': view.show_region_header, 'tools': view.show_region_tool_header,
          'align': next(r.alignment for r in area.regions if r.type == 'HEADER')}
view.show_region_header = True
view.show_region_tool_header = True
with bpy.context.temp_override(window=win, area=area,
                              region=next(r for r in area.regions if r.type == 'WINDOW')):
    bpy.ops.object.mode_set(mode='EDIT')
""")
    results = {}
    try:
        for overlap in (True, False):
            qa.eval(f"bpy.context.preferences.system.use_region_overlap={overlap!r}; result=True")
            for alignment in ("TOP", "BOTTOM"):
                align_headers(qa, alignment)
                label = f"texturing-{alignment.lower()}-overlap-{overlap}"
                results[label] = qa.step(label, separate_headers, qa)
                snap(qa, label)
        # Both supported texturing names must share the same behavior.
        qa.eval("drv.main_window().workspace.name='Texture Paint'; result=True")
        results["texture-paint-name"] = qa.step("texture-paint-name", separate_headers, qa)
    finally:
        qa.eval("drv.main_window().workspace.name='Texturing'; result=True")
        align_headers(qa, saved["align"])
        qa.eval(SETUP + f"""
with bpy.context.temp_override(window=win, area=area,
                              region=next(r for r in area.regions if r.type == 'WINDOW')):
    bpy.ops.object.mode_set(mode='OBJECT')
view.show_region_header = {saved['header']!r}
view.show_region_tool_header = {saved['tools']!r}
bpy.context.preferences.system.use_region_overlap = True
result=True
""")
    return results


def drawer(qa):
    workspace(qa, "Zen Mode")
    initial = qa.eval(SETUP + """
result = {r.type: [r.x, r.y, r.width, r.height] for r in area.regions
          if r.type in ('WINDOW', 'HEADER', 'TOOL_PROPS')}
""")
    header, board = initial["HEADER"], initial["TOOL_PROPS"]
    assert board[2] > 100 and board[3] > 100, initial
    assert board[1]+board[3] <= header[1] or board[1] >= header[1]+header[3], initial
    for amount in (1, 0):
        qa.click(surface="moodboard_drawer_grip")
        qa.wait(f"abs(bpy.context.window_manager.mixar_moodboard_drawer_amount-{amount}) < .002",
                timeout=8)
        if amount:
            shading_clicks(qa, "BLENDER_WORKBENCH", ["WIREFRAME", "SOLID", "RENDERED"])
        snap(qa, "drawer-open" if amount else "drawer-closed")
    current = qa.eval(SETUP + """
r = next(r for r in area.regions if r.type == 'WINDOW')
result=[r.x, r.y, r.width, r.height]
""")
    assert current == initial["WINDOW"], (initial, current)
    return initial


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    saved = qa.eval("""
import os
assert os.environ.get('MIXAR_QA') == '1', 'Use an isolated QA app'
assert not drv.main_window().scene.mixie_chat_messages
from mixar.modules.agent_bubble.ui.operators import hover_ops
win = drv.main_window()
result = {'workspace': win.workspace.name, 'engine': win.scene.render.engine,
          'overlap': bpy.context.preferences.system.use_region_overlap,
          'tooltips': bpy.context.preferences.view.show_tooltips,
          'hover': bpy.app.timers.is_registered(hover_ops._hover_tick)}
bpy.context.preferences.view.show_tooltips = False
hover_ops.unregister()
bpy.ops.mixar.bubble_minimise()
class QAChromeEngine(bpy.types.RenderEngine):
    bl_idname = 'QA_CHROME_NO_VIEW_DRAW'
    bl_label = 'QA engine without viewport rendering'
    def render(self, depsgraph):
        pass
bpy.utils.register_class(QAChromeEngine)
bpy.app.driver_namespace['qa_chrome_engine'] = QAChromeEngine
""")
    results = {}
    try:
        workspace(qa, "Zen Mode")
        for engine, expected in (
            ("BLENDER_EEVEE", ["WIREFRAME", "SOLID", "MATERIAL", "RENDERED"]),
            ("BLENDER_WORKBENCH", ["WIREFRAME", "SOLID", "RENDERED"]),
            ("QA_CHROME_NO_VIEW_DRAW", ["WIREFRAME", "SOLID", "MATERIAL"]),
        ):
            results[engine] = qa.step(engine, shading_clicks, qa, engine, expected)
        qa.eval("drv.main_window().scene.render.engine='BLENDER_EEVEE'; result=True")
        results["texturing"] = texturing(qa)
        results["drawer"] = qa.step("zen-drawer", drawer, qa)
        return {"checks": results, "paid_requests": 0, "artifacts": str(OUT)}
    finally:
        qa.eval(f"""
drv.main_window().scene.render.engine={saved['engine']!r}
bpy.context.preferences.system.use_region_overlap={saved['overlap']!r}
bpy.context.preferences.view.show_tooltips={saved['tooltips']!r}
drv.main_window().workspace=bpy.data.workspaces[{saved['workspace']!r}]
bpy.utils.unregister_class(bpy.app.driver_namespace.pop('qa_chrome_engine'))
from mixar.modules.agent_bubble.ui.operators import hover_ops
if {saved['hover']!r}: hover_ops.register()
result=True
""")


if __name__ == "__main__":
    run_scenario("floating_viewport_chrome_e2e", run)
