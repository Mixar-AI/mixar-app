#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit floating selection-menu replay in an isolated Mixar QA instance.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4897 \
QA_SCENARIO_OUT=/tmp/zen-object-controls python3 tests/qa/zen_object_controls_e2e.py

Historical scenario: modifier list/search selectors need updating before replay.

Fixture construction uses eval; feature actions use real native widgets.
The scenario creates a disposable scene and does not require authentication.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/zen-object-controls'))
CARD = {"popup": True}
STRIP = {'area_type': 'VIEW_3D', 'region_type': 'TOOL_HEADER'}
SETUP = """
w = drv.main_window()
a = next(a for a in w.screen.areas if a.type == 'VIEW_3D')
r = next(r for r in a.regions if r.type == 'WINDOW')
"""


def snap(qa, name):
    qa.cmd('snap', path=str(OUT / (name + '.png')), area='VIEW_3D')


def select(qa, name):
    qa.eval(SETUP + f"""
for obj in w.view_layer.objects: obj.select_set(False)
obj = w.scene.objects.get({name!r}) if {name!r} else None
if obj: obj.select_set(True)
w.view_layer.objects.active = obj
a.tag_redraw()
result = True
""")


def open_section(qa, label):
    # Native menu actions may close their parent popover. Reopen explicitly.
    qa.press('ESC')
    qa.press('ESC')
    qa.click(**STRIP, text=label)


def startup_and_fixture(qa):
    qa.wait("hasattr(bpy.types, 'MIXAR_OT_zen_add_modifier')", timeout=20)
    log = qa.eval("""
import os
from pathlib import Path
result = Path(os.environ['MIXAR_QA_OUT'], 'app.log').read_text(errors='replace')
""")
    assert 'Failed to load UI module' not in log
    assert 'Traceback (most recent call last)' not in log
    qa.press('ESC')
    qa.eval(SETUP + """
from mixar.modules.onboarding.core.tour import session
if session.current(): session.current().stop('qa')
assert w.workspace.name == 'Zen Mode'
w.scene = bpy.data.scenes.new('QA Floating Controls')
for obj in list(bpy.data.objects):
    if obj.name.startswith(('QA Cube', 'QA Light', 'QA Camera')):
        bpy.data.objects.remove(obj, do_unlink=True)
with bpy.context.temp_override(window=w, area=a, region=r):
    bpy.ops.mesh.primitive_cube_add()
    cube = bpy.context.object
    cube.name = 'QA Cube'
    bpy.ops.object.light_add(type='POINT', location=(3, 1, 4))
    bpy.context.object.name = 'QA Light'
    bpy.ops.object.camera_add(location=(5, -5, 5))
    bpy.context.object.name = 'QA Camera'
    bpy.ops.ed.undo_push(message='Floating controls fixture')
result = True
""")
    # Startup/workspace configuration must expose the floating host itself.
    qa.wait("next(a for a in drv.main_window().screen.areas if a.type == 'VIEW_3D').spaces.active.show_region_tool_header", timeout=8)
    select(qa, 'QA Cube')
    qa.wait(f"bool(drv.find(**{STRIP!r}, text='Modifier'))", timeout=8)
    return {'registration': True, 'startup_errors': 0}


def mesh(qa):
    open_section(qa, 'Modifier')
    qa.click(**CARD, text='Add Modifier')
    choices = qa.find(popup=True, op='MIXAR_OT_zen_add_modifier')['widgets']
    assert {w['text'] for w in choices} == {'Add Bevel', 'Add Subdivision', 'Add Mirror'}
    snap(qa, 'modifier-menu')
    qa.click(popup=True, op='MIXAR_OT_zen_add_modifier', text='Add Bevel')
    open_section(qa, 'Modifier')
    qa.cmd('set_text', widget={**CARD, 'prop': 'width'}, text='0.15')
    qa.cmd('set_text', widget={**CARD, 'prop': 'segments'}, text='3')
    state = qa.eval("m=drv.main_window().scene.objects['QA Cube'].modifiers.active; result=[m.type,m.width,m.segments]")
    assert state[0] == 'BEVEL' and abs(state[1] - .15) < 1e-6 and state[2] == 3, state
    snap(qa, 'mesh-bevel')
    qa.press('Z', ctrl=True)
    qa.wait("drv.main_window().scene.objects['QA Cube'].modifiers.active.segments == 1", timeout=5)
    qa.press('Z', ctrl=True, shift=True)
    qa.wait("drv.main_window().scene.objects['QA Cube'].modifiers.active.segments == 3", timeout=5)
    for label, prop, value in [('Subdivision', 'levels', '2'), ('Mirror', None, None)]:
        open_section(qa, 'Modifier')
        qa.click(**CARD, but_type='Menu')
        qa.click(popup=True, text='Add ' + label)
        open_section(qa, 'Modifier')
        if prop:
            qa.cmd('set_text', widget={**CARD, 'prop': prop}, text=value)
            assert qa.eval("result=drv.main_window().scene.objects['QA Cube'].modifiers.active.levels") == 2
        else:
            qa.click(**CARD, prop='use_axis', text='Y')
            assert qa.eval("result=list(drv.main_window().scene.objects['QA Cube'].modifiers.active.use_axis)") == [True, True, False]
        snap(qa, 'mesh-' + label.lower())
    open_section(qa, 'Modifier')
    qa.click(**CARD, but_type='Menu')
    qa.click(popup=True, op='MIXAR_OT_zen_select_modifier', text='Bevel')
    assert qa.eval("result=len(drv.main_window().scene.objects['QA Cube'].modifiers)") == 3
    open_section(qa, 'Modifier')
    qa.wait(f"bool(drv.find(**{CARD!r}, prop='width'))", timeout=5)
    return {'add_and_edit': ['BEVEL', 'SUBSURF', 'MIRROR'], 'undo_redo': True, 'existing_instance': True}


def light(qa):
    select(qa, 'QA Light')
    open_section(qa, 'Light')
    qa.wait(f"bool(drv.find(**{CARD!r}, prop='energy'))", timeout=5)
    qa.cmd('set_text', widget={**CARD, 'prop': 'energy'}, text='750')
    qa.cmd('set_text', widget={**CARD, 'prop': 'energy'}, text='999', enter=False)
    qa.press('ESC')
    assert qa.eval("result=drv.main_window().scene.objects['QA Light'].data.energy") == 750
    qa.click(**CARD, prop='color')
    qa.cmd('set_text', widget={'popup': True, 'but_type': 'Text'}, text='FF8844')
    qa.press('RET')
    qa.press('ESC')
    color = qa.eval("result=list(drv.main_window().scene.objects['QA Light'].data.color)")
    assert color[0] > .99 and .2 < color[1] < .3 and .04 < color[2] < .08, color
    snap(qa, 'light-color-brightness')
    for kind in ('SUN', 'SPOT', 'AREA', 'POINT'):
        qa.eval(f"drv.main_window().scene.objects['QA Light'].data.type={kind!r}; result=True")
        open_section(qa, 'Light')
        qa.wait(f"bool(drv.find(**{CARD!r}, prop='energy'))", timeout=5)
        assert qa.find(**CARD, prop='color')['total'] == 1
    return {'brightness': 750, 'color': color, 'cancel': True, 'types': ['POINT', 'SUN', 'SPOT', 'AREA']}


def visibility_and_scale(qa):
    qa.press('ESC')
    qa.press('ESC')
    for name in (None, 'QA Camera'):
        select(qa, name)
        qa.wait(f"not any(w.get('prop') or w.get('type') in {'Pulldown', 'Popover'} for w in drv.find(**{STRIP!r}))", timeout=5)
        snap(qa, 'no-selection' if name is None else 'camera')
    select(qa, 'QA Light')
    saved = qa.eval('result=bpy.context.preferences.view.ui_scale')
    try:
        for factor in (1, 1.5):
            qa.eval(f'bpy.context.preferences.view.ui_scale={saved * factor}; result=True')
            qa.wait(f"bool(drv.find(**{STRIP!r}, text='Light'))", timeout=5)
            bounds = qa.eval(SETUP + "result=[a.x,a.x+a.width,next(r.y for r in a.regions if r.type=='HEADER')]")
            widgets = [w for w in qa.find(**STRIP)['widgets'] if w['type'] != 'Other']
            assert all(bounds[0] <= w['rect'][0] < w['rect'][2] <= bounds[1] for w in widgets)
            assert all(w['rect'][3] <= bounds[2] for w in widgets), (bounds, widgets)
            snap(qa, f'floating-{factor}')
    finally:
        qa.eval(f'bpy.context.preferences.view.ui_scale={saved}; result=True')
    return {'hidden_for_empty_and_camera': True, 'below_header': True, 'scales': [1, 1.5]}


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    checks = {}
    for name, fn in [('startup', startup_and_fixture), ('mesh', mesh), ('light', light),
                     ('visibility-and-scale', visibility_and_scale)]:
        checks[name] = qa.step(name, fn, qa)
    verdict = {'checks': checks, 'paid_requests': 0, 'artifacts': str(OUT)}
    (OUT / 'verdict.json').write_text(json.dumps(verdict, indent=2) + '\n')
    return verdict


if __name__ == '__main__':
    run_scenario('zen_object_controls_e2e', run)
