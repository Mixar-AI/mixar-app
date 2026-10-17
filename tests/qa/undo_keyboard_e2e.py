#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit native menu Add and real undo/redo keys in Zen and Engine.

Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT; see docs/modules/undo-validation.md. Event-simulate
launch required. Reads the running app's Screen keymap (including macOS
modifiers), not the host Python platform. Inspect both final viewport frames.
"""

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
sys.path.insert(0, str(Path(__file__).parent))
from lib import ScenarioFail, run_scenario
from undo_turn_fixture import capture, output_dir, reset, write_results


KEYMAP = '''
keymap = bpy.context.window_manager.keyconfigs.active.keymaps['Screen']
result = {}
for operation in ('ed.undo', 'ed.redo'):
    item = next(k for k in keymap.keymap_items
                if k.active and k.idname == operation and k.type == 'Z' and k.value == 'PRESS')
    assert not item.any, 'Use the standard Screen undo keymap'
    result[operation] = {name: bool(getattr(item, name))
                         for name in ('ctrl', 'shift', 'alt', 'oskey')}
'''
OBJECTS = 'result = sorted(o.name for o in drv.main_window().scene.objects)'


def run_mode(qa, mode, out):
    reset(qa)
    target = 'ai' if mode == 'Zen' else 'pro'
    current = qa.eval("from mixar.config.config import get_ui_mode\nresult = get_ui_mode()")
    if current != target:
        qa.click(text=mode)
        qa.wait(f"__import__('mixar.config.config', fromlist=['x']).get_ui_mode() == {target!r}", timeout=10)
    bindings = qa.eval(KEYMAP)
    qa.eval('''
s = drv.main_window().scene
s.mixie_session_id = 'qa-undo-keyboard'
obj = next(o for o in s.objects if o.type == 'MESH')
obj.location.x = -3
bpy.context.window_manager.mixar_undo_push('QA keyboard baseline', scene=s)
result = True
''')
    before = qa.eval(OBJECTS)
    if mode == 'Zen':
        qa.click(text='Add Objects')
    else:
        qa.click(text='Add', but_type='Pulldown', area_type='VIEW_3D')
    qa.click(popup=True, text='Mesh')
    qa.click(popup=True, op='MESH_OT_primitive_cube_add')
    added = qa.eval(OBJECTS)
    qa.eval('''
w = drv.main_window()
area = next(a for a in w.screen.areas if a.type == 'VIEW_3D')
region = next(r for r in area.regions if r.type == 'WINDOW')
drv.move_to(w, region.x + region.width // 2, region.y + region.height // 2)
result = True
''')
    qa.press('Z', **bindings['ed.undo'])
    qa.wait(f'len(drv.main_window().scene.objects) == {len(before)}', timeout=5)
    undone = qa.eval(OBJECTS)
    qa.press('Z', **bindings['ed.redo'])
    qa.wait(f'len(drv.main_window().scene.objects) == {len(added)}', timeout=5)
    redone = qa.eval(OBJECTS)
    capture(qa, out / (mode.lower() + '.png'))
    checks = {'add_one_cube': len(added) == len(before) + 1,
              'undo_restores_objects': undone == before,
              'redo_restores_objects': redone == added}
    return {'mode': mode, 'keymap': bindings, 'before': before, 'added': added,
            'undone': undone, 'redone': redone, 'checks': checks, 'ok': all(checks.values())}


def run(qa):
    out = output_dir('undo-keyboard')
    rows = []
    for mode in ('Zen', 'Engine'):
        row = qa.step(mode, run_mode, qa, mode, out)
        rows.append(row)
        write_results(out, rows)
        if not row['ok']:
            raise ScenarioFail(f'{mode}: {row["checks"]}')
    return {'cases': rows, 'backend_turns': 0}


if __name__ == '__main__':
    run_scenario('undo_keyboard_e2e', run)
