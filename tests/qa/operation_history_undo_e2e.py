#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Live replay: undo keeps one operation-history folder per scene.

Undoing back past the step that assigned `scene.mixar_op_history_id` blanks the
property; the undo handler used to mint a new id and open a new folder each time
(13,658 folders on one machine). Undo, redo, undo, redo by real undo-key presses
must leave the scene on one id with every step recorded in that one folder, and
the daily prune must have run on a worker thread. Event-simulation launch (no
QA_MIXED). Fails on builds before the fix with four folders. Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT.
"""
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

STATE = '''
import os, bpy
from mixar.modules.operation_history.core import store, scene_key
from mixar.modules.operation_history.constants import SCENE_HISTORY_ID_PROP
base = store._base_dir()
dirs = sorted(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))) if os.path.isdir(base) else []
scene = bpy.context.window.scene
result = {
    'base': base, 'dirs': dirs,
    'prop': getattr(scene, SCENE_HISTORY_ID_PROP, ''),
    'sid': getattr(scene, SCENE_HISTORY_ID_PROP, '') or scene_key.remembered_id(scene),
    'cleanup_thread': getattr(getattr(store, '_cleanup_thread', None), 'name', None),
    'objects_in_scene': len(scene.objects),
}
'''


def state(qa):
    return qa.eval(STATE)


def press_z(qa, win, *, redo=False):
    """A real undo / redo key over the viewport (the undo keymap needs a live
    screen): Cmd+Z / Cmd+Shift+Z on macOS, Ctrl+Z / Ctrl+Shift+Z elsewhere."""
    mods = {'oskey': True} if sys.platform == 'darwin' else {'ctrl': True}
    qa.press('Z', window=win, shift=redo, **mods)


def records(qa, sid):
    return qa.eval(f'from mixar.modules.operation_history.core import store\n'
                   f'result = store.read_operations({sid!r}, limit=0)')


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/operation-history-undo'))
    out.mkdir(parents=True, exist_ok=True)
    qa.wait("hasattr(bpy.types.Scene, 'mixar_op_history_id')", timeout=30)
    qa.dismiss_splash()
    # A fresh scene has no id in any undo step, which is how the leak starts. Python
    # operator calls push an undo step only when asked (the second positional arg).
    qa.eval("import bpy\nwin = bpy.context.window\n"
            "with bpy.context.temp_override(window=win, screen=win.screen):\n"
            "    bpy.ops.scene.new('EXEC_DEFAULT', True, type='NEW')\n"
            "with bpy.context.temp_override(window=win, screen=win.screen, scene=win.scene):\n"
            "    bpy.ops.mesh.primitive_cube_add('EXEC_DEFAULT', True, location=(0, 0, 5))\n"
            "result = True")
    start = state(qa)
    assert start['objects_in_scene'] == 1 and start['prop'] == '', start
    win = qa.find(area_type='VIEW_3D')['widgets'][0]['window']
    qa.eval("w = drv.find_one(area_type='VIEW_3D'); x, y = drv.pick_click_point(w); "
            "w['_win'].cursor_warp(x, y); result = True")
    time.sleep(0.3)
    steps = []
    for i in range(4):
        redo = bool(i % 2)
        press_z(qa, win, redo=redo)
        qa.wait(f"len(bpy.context.window.scene.objects) == {1 if redo else 0}", timeout=10)
        time.sleep(0.4)
        steps.append(state(qa))
    sid = steps[0]['sid']
    assert sid and sid != '_nosession', steps[0]
    assert all(s['sid'] == sid and s['prop'] == sid for s in steps), [(s['sid'], s['prop']) for s in steps]
    new_dirs = sorted(set(steps[-1]['dirs']) - set(start['dirs']))
    assert new_dirs == [sid], new_dirs                      # one folder, not one per undo
    recs = records(qa, sid)
    marks = [r.get('op_idname') for r in recs if r.get('category') == 'UNDO']
    assert marks == ['ed.undo', 'ed.redo', 'ed.undo', 'ed.redo'], marks
    assert steps[-1]['cleanup_thread'] == 'mixar-operation-history-cleanup', steps[-1]
    (out / 'state.json').write_text(json.dumps({'start': start, 'steps': steps}, indent=1))
    return {'undo_redo_steps': 4, 'folders_added': len(new_dirs), 'records_in_scene_folder': len(marks),
            'prune_thread': steps[-1]['cleanup_thread'], 'evidence': str(out)}


if __name__ == '__main__':
    run_scenario('operation_history_undo_e2e', run)
