#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit regression for reversible per-viewport Sky Light overrides.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4891 \
    QA_SCENARIO_OUT=/tmp/zen-sky python3 tests/qa/zen_sky_lighting_e2e.py
"""

import json
import os
from pathlib import Path

from zen_scene_toolbar_e2e import reset_zen_scene
from lib import run_scenario

OUT = Path(os.environ.get("QA_SCENARIO_OUT", "/tmp/zen-sky"))
SETUP = """
win = drv.main_window()
scene = win.scene
areas = sorted(win.screen.areas, key=lambda a: (a.y, a.x))
views = [s for a in areas for s in a.spaces if s.type == 'VIEW_3D']
"""
FLAGS = SETUP + "result=[[v.shading.use_scene_world, v.shading.use_scene_world_render] for v in views]"
ORIGINAL = [[False, True], [True, False]]


def fixture(qa):
    reset_zen_scene(qa)
    qa.eval("""
from mixar.modules.agent_bubble.ui.operators import hover_ops
hover_ops.unregister()
win = drv.main_window()
area = next(a for a in win.screen.areas if a.type == 'VIEW_3D')
with bpy.context.temp_override(window=win, area=area):
    bpy.ops.screen.area_split(direction='HORIZONTAL', factor=.5)
result=True
""")
    qa.wait("len(drv.find(text='ON', op='MIXAR_OT_zen_set_sky', region_type='HEADER')) == 2", timeout=8)
    qa.eval(SETUP + """
scene.render.engine = 'BLENDER_EEVEE'
for view, flags in zip(views, ((False, True), (True, False))):
    view.shading.use_scene_world, view.shading.use_scene_world_render = flags
    view.shading.type = 'MATERIAL'
    view.region_3d.view_location = (0, 0, 0)
    view.region_3d.view_distance = 18
result=True
""")


def sky(qa, enabled):
    # Choose the lower viewport's native target deterministically.
    qa.eval(f"""
def click_sky():
    targets = sorted(drv.find(text={'ON' if enabled else 'OFF'!r}, op='MIXAR_OT_zen_set_sky',
                             area_type='VIEW_3D', region_type='HEADER'),
                     key=lambda w: w['rect'][1])
    yield from drv.click_steps(targets[0])
    yield .1
    return True
result=click_sky()
""")


def snap(qa, name):
    qa.cmd("snap", path=str(OUT / (name + ".png")))


def undo(qa, *, redo=False):
    qa.click(area_type="TOPBAR", text="Edit")
    qa.click(popup=True, op="ED_OT_redo" if redo else "ED_OT_undo")


def per_viewport(qa):
    fixture(qa)
    untouched = qa.eval(SETUP + """
other = next(s for screen in bpy.data.screens if screen != win.screen
             for a in screen.areas for s in a.spaces if s.type == 'VIEW_3D')
other.shading.use_scene_world = False
other.shading.use_scene_world_render = False
result={'screen':other.id_data.name, 'path':other.path_from_id()}
""")
    snap(qa, "preview-before")
    sky(qa, True)
    assert qa.eval(FLAGS) == [[True, True], [True, True]]
    snap(qa, "preview-sky-on")
    sky(qa, True)
    sky(qa, False)
    assert qa.eval(FLAGS) == ORIGINAL
    assert qa.eval(f"""
view=bpy.data.screens[{untouched['screen']!r}].path_resolve({untouched['path']!r})
result=[view.shading.use_scene_world, view.shading.use_scene_world_render]
""") == [False, False]
    snap(qa, "preview-restored")
    return {"restored": ORIGINAL, "repeated_on": True, "unrelated_view_unchanged": True}


def inactive_space(qa):
    sky(qa, True)
    qa.eval(SETUP + "areas[-1].type='TEXT_EDITOR'; result=True")
    sky(qa, False)
    assert qa.eval(FLAGS) == ORIGINAL
    qa.eval(SETUP + "areas[-1].type='VIEW_3D'; result=True")
    return {"inactive_editor_restored": True}


def undo_history(qa):
    fixture(qa)
    sky(qa, True)
    undo(qa)
    assert qa.eval(FLAGS) == ORIGINAL
    undo(qa, redo=True)
    assert qa.eval(FLAGS) == [[True, True], [True, True]]
    sky(qa, False)
    assert qa.eval(FLAGS) == ORIGINAL
    qa.eval(SETUP + """
for view in views:
    view.shading.use_scene_world = True
    view.shading.use_scene_world_render = False
result=True
""")
    sky(qa, True)
    undo(qa)
    assert qa.eval(FLAGS) == [[True, False], [True, False]]
    # Undo the preceding OFF, then the first ON. Its own original flags
    # must survive even though a later activation captured different ones.
    undo(qa)
    assert qa.eval(FLAGS) == [[True, True], [True, True]]
    undo(qa)
    assert qa.eval(FLAGS) == ORIGINAL
    snap(qa, "preview-restored-by-undo")
    return {"first_enable_undo": True, "redo": True, "multiple_cycles": True}


def persistence(qa):
    fixture(qa)
    sky(qa, True)
    path = OUT / "two-viewport-sky.mixar"
    qa.eval(f"result=str(bpy.ops.wm.save_as_mainfile(filepath={str(path)!r}, check_existing=False))")
    qa.eval(f"result=str(bpy.ops.wm.open_mainfile(filepath={str(path)!r}))")
    qa.wait("len(drv.find(text='ON', op='MIXAR_OT_zen_set_sky', region_type='HEADER')) == 2", timeout=12)
    assert qa.eval(FLAGS) == [[True, True], [True, True]]
    sky(qa, False)
    assert qa.eval(FLAGS) == ORIGINAL
    undo(qa)
    assert qa.eval(FLAGS) == [[True, True], [True, True]]
    undo(qa, redo=True)
    assert qa.eval(FLAGS) == ORIGINAL
    snap(qa, "preview-restored-after-reopen")
    return {"reopened": str(path), "restored": ORIGINAL, "off_undo_redo": True}


def external_world(qa):
    sky(qa, True)
    name = qa.eval(SETUP + "scene.world=bpy.data.worlds.new('QA_External_World'); result=scene.world.name")
    sky(qa, False)
    assert qa.eval(SETUP + "result=scene.world.name") == name
    assert qa.eval(FLAGS) == ORIGINAL
    # A fresh cycle remembers preferences edited while the toggle is off.
    qa.eval(SETUP + """
for view in views:
    view.shading.use_scene_world = False
    view.shading.use_scene_world_render = False
result=True
""")
    sky(qa, True)
    sky(qa, False)
    assert qa.eval(FLAGS) == [[False, False], [False, False]]
    snap(qa, "preview-studio-restored")
    return {"external_world_preserved": name, "new_preferences_restored": True}


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    checks = {}
    for name, fn in (("per-viewport", per_viewport), ("inactive-space", inactive_space),
                     ("undo-history", undo_history), ("persistence", persistence),
                     ("external-world", external_world)):
        checks[name] = qa.step(name, fn, qa)
    verdict = {"checks": checks, "paid_requests": 0, "artifacts": str(OUT)}
    (OUT / "verdict.json").write_text(json.dumps(verdict, indent=2) + "\n")
    return verdict


if __name__ == "__main__":
    run_scenario("zen_sky_lighting_e2e", run)
