#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Check rendered Zen tool glyphs against native hit rectangles (no credits).

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4896 \
    QA_SCENARIO_OUT=/tmp/zen-toolbar python3 tests/qa/zen_toolbar_alignment_e2e.py

Run against an isolated Dev QA app. Screenshots are native framebuffer captures;
Pillow measures their pixels without modifying them. Review the captures too.
"""

import os
from pathlib import Path
import sys

from PIL import Image

sys.path.insert(0, str(Path(os.environ["QA_HARNESS"]) / "scenarios"))
from lib import run_scenario  # noqa: E402

OUT = Path(os.environ.get("QA_SCENARIO_OUT", "/tmp/zen-toolbar"))
TOOLS = ("builtin.move", "builtin.rotate", "builtin.scale")
SETUP = """
win = drv.main_window()
area = next(a for a in win.screen.areas if a.type == 'VIEW_3D')
region = next(r for r in area.regions if r.type == 'WINDOW')
view = area.spaces.active
"""
TARGETS = """
targets = sorted(drv.find(area_type='VIEW_3D', region_type='TOOLS',
                          op='WM_OT_tool_set_by_id'), key=lambda t: -t['rect'][3])
assert len(targets) == 3, len(targets)
"""


def update(qa, code):
    return qa.eval(SETUP + "\ndef update():\n" +
                   "\n".join("    " + line for line in code.splitlines()) + """
    area.tag_redraw()
    yield .4
    return True
result = update()
""")


def capture(qa, name, hover=None):
    path = OUT / f"{name}.png"
    return qa.eval(SETUP + TARGETS + f"""
def capture():
    target = {hover!r}
    if target is None:
        drv.move_to(win, region.x + region.width // 2, region.y + region.height // 2)
    else:
        drv.move_to(win, *targets[target]['center'])
    yield .2
    rects = [t['rect'] for t in targets]
    x0 = max(0, min(r[0] for r in rects) - 8)
    y0 = min(r[1] for r in rects) - 8
    x1 = max(r[2] for r in rects) + 8
    y1 = max(r[3] for r in rects) + 8
    with bpy.context.temp_override(window=win):
        assert win.mixar_qa_capture_frame(filepath={str(path)!r}, x=x0, y=y0,
                                        width=x1-x0, height=y1-y0)
    return {{'path': {str(path)!r}, 'rects': rects, 'crop': [x0, y0, x1, y1]}}
result = capture()
""")


def measure(frame):
    x0, _y0, _x1, y1 = frame["crop"]
    measurements = []
    with Image.open(frame["path"]) as source:
        image = source.convert("RGB")
        for tool, rect in zip(TOOLS, frame["rects"]):
            # Remove separators and the end caps; include the full horizontal
            # capture so a glyph outside its button cannot evade the assertion.
            pad = int((rect[3] - rect[1]) * .16)
            top, bottom = y1 - rect[3] + pad, y1 - rect[1] - pad
            points = [(x, y) for y in range(top, bottom) for x in range(image.width)
                      if min(image.getpixel((x, y))) > 110
                      and max(image.getpixel((x, y))) - min(image.getpixel((x, y))) < 25]
            assert points, (tool, frame["path"])
            left = min(x for x, _ in points) + x0
            right = max(x for x, _ in points) + x0
            center = (left + right + 1) / 2
            expected = (rect[0] + rect[2]) / 2
            delta = center - expected
            measurements.append({"tool": tool, "glyph_x": [left, right],
                                 "button_x": [rect[0], rect[2]], "offset": delta})
            assert abs(delta) <= 2.5, (tool, f"glyph is {delta}px off-center", frame)
            assert rect[0] < left < right < rect[2], (tool, measurements[-1])
    return measurements


def click_tool(qa, index, expected):
    active = qa.eval(SETUP + TARGETS + f"""
def click():
    yield from drv.click_steps(targets[{index}])
    yield .2
    return win.workspace.tools.from_space_view3d_mode('OBJECT').idname
result = click()
""")
    assert active == expected, (active, expected)


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    saved = qa.eval("""
import os
assert os.environ.get('MIXAR_QA') == '1', 'Use an isolated QA app'
win = drv.main_window()
result = {'workspace': win.workspace.name, 'scale': bpy.context.preferences.view.ui_scale,
          'tooltips': bpy.context.preferences.view.show_tooltips}
win.workspace = bpy.data.workspaces['Zen Mode']
bpy.context.preferences.view.show_tooltips = False
""")
    qa.eval(SETUP + """
bpy.app.driver_namespace['qa_toolbar_saved'] = {
    'overlay': view.overlay.show_overlays, 'toolbar': view.show_region_toolbar,
    'background_type': view.shading.background_type,
    'background_color': tuple(view.shading.background_color),
    'shading': view.shading.type,
    'tool': win.workspace.tools.from_space_view3d_mode('OBJECT').idname}
result = True
""")
    results = {}
    try:
        update(qa, "view.show_region_toolbar = True")
        qa.cmd("snap", path=str(OUT / "viewport.png"), area="VIEW_3D")
        capture(qa, "toolbar-with-scene")
        update(qa, """
view.overlay.show_overlays = False
view.shading.type = 'SOLID'
view.shading.background_type = 'VIEWPORT'
view.shading.background_color = (.01, .01, .01)
with bpy.context.temp_override(window=win, area=area, region=region):
    bpy.ops.wm.tool_set_by_id(name='builtin.select_box')
""")
        for scale in (1.0, 1.25, .8):
            label = f"scale-{scale}"
            update(qa, f"bpy.context.preferences.view.ui_scale = {scale}")
            results[label] = qa.step(label + "-idle", measure, capture(qa, label + "-idle"))
            for index, tool in enumerate(TOOLS):
                name = f"{label}-{tool.rsplit('.', 1)[1]}"
                qa.step(name + "-hover", measure, capture(qa, name + "-hover", index))
                qa.step(name + "-select", click_tool, qa, index, tool)
                qa.step(name + "-selected-pixels", measure, capture(qa, name + "-selected"))
                qa.step(name + "-toggle-off", click_tool, qa, index, "builtin.select_box")
        return {"measurements": results, "screenshots": str(OUT), "backend_calls": 0}
    finally:
        update(qa, """
state = bpy.app.driver_namespace.pop('qa_toolbar_saved')
view.overlay.show_overlays = state['overlay']
view.show_region_toolbar = state['toolbar']
view.shading.type = state['shading']
view.shading.background_type = state['background_type']
view.shading.background_color = state['background_color']
with bpy.context.temp_override(window=win, area=area, region=region):
    bpy.ops.wm.tool_set_by_id(name=state['tool'])
""" + f"""
bpy.context.preferences.view.ui_scale = {saved['scale']!r}
bpy.context.preferences.view.show_tooltips = {saved['tooltips']!r}
win.workspace = bpy.data.workspaces[{saved['workspace']!r}]
""")


if __name__ == "__main__":
    run_scenario("zen_toolbar_alignment_e2e", run)
