#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit floating Animations placement and selection/lifetime replay.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4899 \
QA_SCENARIO_OUT=/tmp/animation-context python3 tests/qa/animation_context_menu_e2e.py
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ensure_scenes_drawer, run_scenario
from animation_browser_e2e import BASE, FIXTURE, OUT, STATE, freeze_at, open_browser, play, snap

STRIP = {'region_type': 'TOOL_HEADER', 'area_type': 'VIEW_3D'}


def select(qa, name):
    qa.eval(BASE + f"""
for obj in w.view_layer.objects: obj.select_set(False)
obj=w.scene.objects.get({name!r}) if {name!r} else None
if obj: obj.select_set(True)
w.view_layer.objects.active=obj
browser.invalidate()
a.tag_redraw()
result=True
""")


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.cmd('wait_login', timeout=30)
    qa.cmd('reset_state')
    qa.dismiss_splash()
    qa.cmd('set_mode', mode='zen')
    qa.wait("drv.main_window().workspace.name=='Zen Mode'", timeout=8)
    qa.eval('exec(compile(open(' + repr(str(FIXTURE)) + ").read(),'animation fixture','exec'))")
    qa.eval(BASE + "\nw.scene.objects['QA Robot Rig'].show_in_front=True\n"
            "a.spaces.active.overlay.show_overlays=True\nresult=True")
    ensure_scenes_drawer(qa)
    qa.wait("bool(drv.find(text='Animations',region_type='TOOL_HEADER'))", timeout=8)
    assert qa.find(text='Animations', region_type='HEADER')['total'] == 0
    assert qa.find(text='Modifier', **STRIP)['total'] == 1
    assert qa.find(text='Textures', **STRIP)['total'] == 1
    # Existing editing popovers still open from the same bar.
    for label, prop in [('Modifier', 'modifier'), ('Textures', 'material')]:
        qa.click(text=label, **STRIP)
        assert qa.find(popup=True)['total'] > 0, prop
        qa.press('ESC')
    snap(qa, '01-mesh-context-menu')
    qa.click(op='MIXAR_OT_zen_object_controls_show', **STRIP)
    qa.wait("not drv.find(text='Animations',region_type='TOOL_HEADER')", timeout=5)
    qa.click(op='MIXAR_OT_zen_object_controls_show', region_type='HEADER')
    qa.wait("bool(drv.find(text='Animations',region_type='TOOL_HEADER'))", timeout=5)
    qa.step('mesh_menu_and_close_restore', lambda: True)

    select(qa, 'QA Robot Rig')
    qa.wait("not drv.find(text='Modifier',region_type='TOOL_HEADER')", timeout=5)
    assert qa.find(text='Animations', **STRIP)['total'] == 1
    assert qa.find(text='Modifier', **STRIP)['total'] == 0
    assert qa.find(text='Textures', **STRIP)['total'] == 0
    open_browser(qa)
    assert qa.eval(f"result={STATE}.target_name") == 'QA Robot Rig'
    # A selected rig is never offered Hide Rig: hiding would deselect it.
    assert qa.find(op='MIXAR_OT_animation_hide_rig', popup=True)['total'] == 0
    play(qa, 'Wave', 'Wave stored')
    qa.press('ESC')
    qa.wait("bool(drv.find(text='Animations',region_type='TOOL_HEADER'))", timeout=5)
    # Nothing is pinned or locked while a clip plays: it is ordinary NLA data.
    assert qa.find(op='MIXAR_OT_zen_object_controls_show', enabled=True, **STRIP)['total'] == 1
    # Reopen while playing, then switch clips: solo moves to the other track.
    qa.click(text='Animations', **STRIP)
    play(qa, 'Walk', 'Walk stored')
    qa.press('ESC')
    snap(qa, '02-rig-playing-context-menu')
    qa.click(op='MIXAR_OT_animation_stop', region_type='HEADER')
    qa.step('rig_selection_and_clip_switch', lambda: True)

    select(qa, 'QA Robot Body')
    qa.wait("bool(drv.find(text='Modifier',region_type='TOOL_HEADER',enabled=True))", timeout=5)
    open_browser(qa)
    play(qa, 'Wave', 'Wave stored')
    freeze_at(qa, 1)
    geometry = BASE + """
with bpy.context.temp_override(window=w,area=a,region=r):
    obj=w.scene.objects['QA Robot Arm']
    ev=obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    result=[list(ev.matrix_world @ v.co) for v in ev.data.vertices]
"""
    first = qa.eval(geometry)
    qa.click(op='MIXAR_OT_animation_hide_rig', popup=True)
    rig_visibility = BASE + """
rig=w.scene.objects['QA Robot Rig']
result=[rig.visible_get(view_layer=w.view_layer), rig.hide_viewport]
"""
    # Hide Rig is the view-layer hide flag; hide_viewport (which would stop
    # deformation) is untouched.
    qa.wait("not drv.main_window().scene.objects['QA Robot Rig']"
            ".visible_get(view_layer=drv.main_window().view_layer)", timeout=5)
    assert qa.eval(rig_visibility) == [False, False]
    qa.cmd('set_text', widget={'prop': 'frame_current', 'popup': True}, text='25')
    qa.wait("drv.main_window().scene.frame_current == 25", timeout=5)
    second = qa.eval(geometry)
    movement = max(abs(x-y) for a,b in zip(first,second) for x,y in zip(a,b))
    assert movement > .1, movement
    snap(qa, '04-hide-rig-panel')
    qa.press('ESC')
    snap(qa, '05-rig-hidden-playing')
    qa.click(text='Animations', **STRIP)
    qa.click(op='MIXAR_OT_animation_hide_rig', popup=True)
    qa.wait("drv.main_window().scene.objects['QA Robot Rig']"
            ".visible_get(view_layer=drv.main_window().view_layer)", timeout=5)
    assert qa.eval(rig_visibility) == [True, False]
    visible_geometry = qa.eval(geometry)
    assert max(abs(x-y) for a,b in zip(second,visible_geometry) for x,y in zip(a,b)) < 1e-5
    qa.press('ESC')
    # Editing stays available while the clip is soloed.
    assert qa.find(text='Modifier', enabled=True, **STRIP)['total'] == 1
    assert qa.find(text='Textures', enabled=True, **STRIP)['total'] == 1
    qa.click(op='MIXAR_OT_animation_stop', region_type='HEADER')
    assert not qa.eval(BASE + "result=any(t.is_solo for t in w.scene.objects['QA Robot Rig']"
                       ".animation_data.nla_tracks)")
    qa.step('mesh_selection_plays_its_rig_and_keeps_editing', lambda: True)
    qa.step('hide_rig_keeps_skinning', lambda: movement)

    # An ordinary unanimated mesh still provides discovery through All in file.
    qa.eval(BASE + """
with bpy.context.temp_override(window=w,area=a,region=r):
    bpy.ops.mesh.primitive_cube_add(location=(4,0,0))
    bpy.context.object.name='QA Plain Cube'
browser.invalidate()
result=True
""")
    open_browser(qa)
    qa.wait(f"{STATE}.target_name=='QA Plain Cube' and not {STATE}.loading", timeout=5)
    assert qa.eval(f'result=len({STATE}.clips)') == 0
    assert qa.find(text='No animations assigned', popup=True)['total'] == 1
    qa.press('ESC')
    for name in ('QA Animated Light', None):
        select(qa, name)
        qa.wait("not drv.find(text='Animations',region_type='TOOL_HEADER')", timeout=5)
    qa.step('empty_mesh_and_context_visibility', lambda: True)
    return {'topbar_entry_removed': True, 'mesh_and_rig': True,
            'clip_switch': True, 'hide_rig': True, 'evidence': str(OUT)}


if __name__ == '__main__':
    run_scenario('animation_context_menu_e2e', run)
