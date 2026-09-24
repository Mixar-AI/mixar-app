#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit native shading/header regression; requires an isolated Dev QA app.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4879 \
    QA_SCENARIO_OUT=/tmp/floating-chrome python3 tests/qa/floating_viewport_chrome_e2e.py

All control clicks resolve native RNA widgets or the drawer's QA targets.
Inspect the emitted PNGs as well as the state verdict.

Covers the Texturing workspace's restored chrome: the stock 3D viewport
header, and the Editor Type dropdown on every area with the five texturing
editors grouped under a "Texturing" heading.
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
    # Stock headers can horizontally overflow in a split Texturing viewport.
    # Its editor switcher is the visible ready target; shading is tested in Zen.
    target = VIEW if name == "Zen Mode" else {
        "area_type": "VIEW_3D", "region_type": "HEADER", "prop": "ui_type"}
    qa.wait(f"bool(drv.find(**{target!r}))", timeout=10)


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


SWITCHER = {"region_type": "HEADER", "prop": "ui_type"}
TEXTURING_EDITORS = (
    ("MIXAR_LAYERS", "Texturing Layers"),
    ("MIXAR_PROPERTIES", "Texturing Properties"),
    ("MIXAR_ASSETS", "Texturing Assets"),
    ("BAKING", "Texturing Baking Space"),
    ("TEXTURE_SETS", "Texture Sets"),
)


def editor_type_switchers(qa):
    """Every Texturing area offers the Editor Type dropdown.

    Drives the real menu: opens the 3D viewport's switcher, reads the
    popup, and checks the five texturing editors are listed under their
    own "Texturing" heading — then switches through the menu and back.
    The texturing side panels are checked for the widget itself, since
    the Layers header hangs off TOOL_PROPS rather than HEADER.
    """
    workspace(qa, "Texturing")
    saved = qa.eval("""
result = [a.ui_type for a in drv.main_window().screen.areas]
""")
    # The dropdown exists on the 3D viewport and on every texturing editor,
    # whichever region its header lives in.
    present = qa.eval("""
win = drv.main_window()
found = {}
for area in win.screen.areas:
    widgets = []
    for region in ('HEADER', 'TOOL_PROPS'):
        widgets += drv.find(area_type=area.type, region_type=region, prop='ui_type')
    found[area.ui_type] = len(widgets)
result = found
""")
    assert present.get("VIEW_3D"), present
    for ui_type, _label in TEXTURING_EDITORS:
        if ui_type in present:
            assert present[ui_type], (ui_type, present)

    # The whole stock viewport header came back, not just the switcher:
    # mode selector and the View / Select / Add menus are all native.
    stock = qa.eval("""
widgets = drv.find(area_type='VIEW_3D', region_type='HEADER')
result = {'mode': [w for w in widgets if w.get('prop') == 'mode' or
                  (w['type'] == 'Menu' and w.get('text') == 'Object Mode')],
          'labels': sorted({w.get('text') for w in widgets if w.get('text')})}
""")
    assert stock["mode"], stock
    for menu in ("View", "Select", "Add"):
        assert menu in stock["labels"], (menu, stock["labels"])

    qa.click(area_type="VIEW_3D", **SWITCHER)
    listed = qa.eval("result=[w.get('text') for w in drv.find(popup=True)]")
    assert "Texturing" in listed, listed
    heading = listed.index("Texturing")
    for _ui_type, label in TEXTURING_EDITORS:
        assert label in listed, (label, listed)
        assert listed.index(label) > heading, (label, listed)
    # Nothing that is not an editor leaks into the menu.
    for label in ("Agent Bubble", "Top Bar", "Status Bar"):
        assert label not in listed, (label, listed)

    qa.click(popup=True, text="Texturing Layers")
    qa.wait("sum(a.ui_type == 'MIXAR_LAYERS' for a in drv.main_window().screen.areas)"
            f" == {saved.count('MIXAR_LAYERS') + 1}",
            timeout=6)
    qa.cmd("snap", path=str(OUT / "editor-type-switched.png"))
    # Areas keep their screen order, so restore by index.
    qa.eval(f"""
for area, ui_type in zip(drv.main_window().screen.areas, {saved!r}):
    if area.ui_type != ui_type:
        area.ui_type = ui_type
result=True
""")
    qa.wait("bool(drv.find(area_type='VIEW_3D', region_type='HEADER', prop='ui_type'))",
            timeout=10)
    return {"listed": listed, "switchers": present}


def texturing(qa):
    """Both Texturing viewport header rows stay real, separate bars.

    Texturing is an ordinary Engine workspace now: the header no longer
    floats, so HEADER and TOOL_HEADER must each occupy their own strip at
    either alignment and with region overlap on or off, and a tool-header
    click must not disturb the shading state.
    """
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
    # A preceding drawer scenario can leave it open. Start from a settled
    # closed state, or the first wait may accept its pre-click open amount.
    if qa.eval("result=bpy.context.window_manager.mixar_moodboard_drawer_target"):
        qa.click(surface="moodboard_drawer_grip")
    qa.wait("abs(bpy.context.window_manager.mixar_moodboard_drawer_amount) < .002", timeout=8)
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
        results["editor-type"] = qa.step("editor-type", editor_type_switchers, qa)
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
