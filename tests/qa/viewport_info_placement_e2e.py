#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Measure native viewport text pixels in an isolated Dev QA app (no credits).

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4879 \
    QA_SCENARIO_OUT=/tmp/viewport-info python3 tests/qa/viewport_info_placement_e2e.py

The Show Text off/on image difference isolates the actual native labels.
Read the emitted screenshots as well as the numeric verdict.
"""

import json
import os
from pathlib import Path
import sys

from PIL import Image, ImageChops

sys.path.insert(0, str(Path(os.environ["QA_HARNESS"]) / "scenarios"))
from lib import run_scenario  # noqa: E402

OUT = Path(os.environ.get("QA_SCENARIO_OUT", "/tmp/viewport-info"))
SETUP = """
win = drv.main_window()
area = next(a for a in win.screen.areas if a.type == 'VIEW_3D')
view = area.spaces.active
"""


def update(qa, code):
    qa.eval(SETUP + "\ndef update():\n" +
            "\n".join("    " + line for line in code.splitlines()) + """
    area.tag_redraw()
    yield .4
    return True
result = update()
""")


def capture_text(qa, name, zen=True):
    geometry = qa.eval(SETUP + """
r = next(r for r in area.regions if r.type == 'WINDOW')
s = bpy.context.preferences.system
result = {'viewport': [r.x, r.y, r.width, r.height],
          'unit': round(18 * s.ui_scale) + 2 * s.pixel_size,
          'header_inset': max([r.y + r.height - h.y for h in area.regions
              if h.type == 'HEADER' and h.alignment == 'TOP' and h.height > 1] or [0])}
""")
    paths = []
    for show in (False, True):
        update(qa, f"view.overlay.show_text = {show!r}")
        path = OUT / f"{name}-{'on' if show else 'off'}.png"
        qa.cmd("snap", path=str(path), area="VIEW_3D")
        paths.append(path)
    with Image.open(paths[0]) as off, Image.open(paths[1]) as on:
        delta = ImageChops.difference(off.convert("RGB"), on.convert("RGB"))
        # Pixel measurement only; the native renderer owns all text/geometry.
        crop = delta.crop((0, 0, min(delta.width // 2, 1000), int(geometry['unit'] * 8)))
        mask = crop.convert("L").point(lambda v: 255 if v > 30 else 0)
        bounds = mask.getbbox()
        assert bounds is not None, 'Show Text did not reveal the native info stack'
        occupied = [bool(mask.crop((0, y, mask.width, y + 1)).getbbox())
                    for y in range(mask.height)]
        lines = sum(value and (y == 0 or not occupied[y - 1])
                    for y, value in enumerate(occupied))
        assert lines == 2, (name, bounds, lines)
    unit = geometry['unit']
    if zen:
        assert .3 * unit <= bounds[0] <= .85 * unit, (name, bounds, geometry)
        assert 0 < bounds[1] - geometry['header_inset'] <= unit, (name, bounds, geometry)
    else:
        assert bounds[0] > unit, (name, bounds, geometry)
    return {**geometry, 'text_bounds': list(bounds), 'lines': lines}


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    saved = qa.eval("""
import os
assert os.environ.get('MIXAR_QA') == '1', 'Use an isolated QA app'
assert not drv.main_window().scene.mixie_chat_messages
from mixar.modules.agent_bubble.ui.operators import hover_ops
win = drv.main_window()
prefs = bpy.context.preferences.view
result = {'workspace': win.workspace.name, 'scale': prefs.ui_scale,
          'names': prefs.show_view_name, 'info': prefs.show_object_info,
          'tooltips': prefs.show_tooltips,
          'hover': bpy.app.timers.is_registered(hover_ops._hover_tick)}
hover_ops.unregister()
bpy.ops.mixar.bubble_minimise()
prefs.show_tooltips = False
prefs.show_view_name = True
prefs.show_object_info = True
bpy.app.driver_namespace['qa_viewport_info_saved'] = []
""")
    results = {}
    try:
        for workspace, zen in (("Zen Mode", True), ("Texturing", False)):
            qa.eval(f"drv.main_window().workspace=bpy.data.workspaces[{workspace!r}]; result=True")
            update(qa, """
props = {p: getattr(view, p) for p in ('show_region_toolbar', 'show_region_header',
                                     'show_region_tool_header')}
overlay = {p: getattr(view.overlay, p) for p in ('show_text', 'show_stats', 'show_overlays')}
bpy.app.driver_namespace['qa_viewport_info_saved'].append((view, props, overlay))
view.show_region_toolbar = True
view.show_region_header = True
view.overlay.show_stats = False
view.overlay.show_overlays = True
""")
            key = 'zen' if zen else 'texturing'
            results[key] = qa.step(key, capture_text, qa, key, zen)
            if not zen:
                continue
            for prop in ('show_region_toolbar', 'show_region_header'):
                update(qa, f"view.{prop} = False")
                label = 'zen-without-' + prop
                results[label] = qa.step(label, capture_text, qa, label)
                if prop == 'show_region_toolbar':
                    assert results[label]['text_bounds'] == results['zen']['text_bounds']
                else:
                    assert results[label]['text_bounds'][0] == results['zen']['text_bounds'][0]
                    assert results[label]['text_bounds'][1] < results['zen']['text_bounds'][1]
                update(qa, f"view.{prop} = True")
            update(qa, f"bpy.context.preferences.view.ui_scale = {saved['scale'] * 1.25!r}")
            results['zen-scaled'] = qa.step('zen-scaled', capture_text, qa, 'zen-scaled')
            update(qa, f"bpy.context.preferences.view.ui_scale = {saved['scale']!r}")
        verdict = {'checks': results, 'paid_requests': 0}
        (OUT / 'verdict.json').write_text(json.dumps(verdict, indent=2) + '\n')
        return verdict
    finally:
        qa.eval(f"""
for view, props, overlay in bpy.app.driver_namespace.pop('qa_viewport_info_saved'):
    for p, value in props.items(): setattr(view, p, value)
    for p, value in overlay.items(): setattr(view.overlay, p, value)
prefs = bpy.context.preferences.view
prefs.ui_scale = {saved['scale']!r}
prefs.show_view_name = {saved['names']!r}
prefs.show_object_info = {saved['info']!r}
prefs.show_tooltips = {saved['tooltips']!r}
drv.main_window().workspace = bpy.data.workspaces[{saved['workspace']!r}]
from mixar.modules.agent_bubble.ui.operators import hover_ops
if {saved['hover']!r}: hover_ops.register()
result=True
""")


if __name__ == '__main__':
    run_scenario('viewport_info_placement_e2e', run)
