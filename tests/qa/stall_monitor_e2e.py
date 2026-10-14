#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Live replay: the native stall monitor attributes induced main-thread stalls.

Run against a QA app started with QA_MIXED=1 (sleeping main loop). Five stalls
are induced from Python — a timer, an operator called from a timer, an app
handler, a viewport draw handler and a long sleeping timer — and each must appear
in stalls.jsonl with the right phase and breadcrumb; the last one also with the
watchdog's Python stack. Set QA_HARNESS, MIXAR_QA_PORT and
QA_SCENARIO_OUT.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

SETUP = '''
import time, bpy
from mixar.modules.common.utils import stall_log
drv._stall_path = stall_log.stall_log_path()
drv._stall_seq = max([r["seq"] for r in stall_log.read_stalls(drv._stall_path)] or [0])

class QA_OT_stall(bpy.types.Operator):
    bl_idname = "qa.stall"
    bl_label = "QA stall"
    def execute(self, context):
        time.sleep(0.2)
        return {"FINISHED"}
bpy.utils.register_class(QA_OT_stall)

def qa_stall_timer():
    time.sleep(0.3)
    return None

def qa_stall_timer_op():
    bpy.ops.qa.stall()
    return None

def qa_stall_handler(scene, depsgraph=None):
    if scene.get("qa_stall_armed"):
        del scene["qa_stall_armed"]
        time.sleep(0.25)

def qa_stall_draw():
    if not getattr(drv, "_stall_drawn", False):
        drv._stall_drawn = True
        time.sleep(0.2)

def qa_stall_timer_long():
    time.sleep(1.2)      # releases the GIL: the watchdog captures this frame mid-stall
    return None

drv._stall_fns = (qa_stall_timer, qa_stall_timer_op, qa_stall_handler, qa_stall_draw, qa_stall_timer_long)
result = drv._stall_path
'''

TEARDOWN = '''
import bpy
timer, timer_op, handler, draw, timer_long = drv._stall_fns
for fn in (timer, timer_op, timer_long):
    if bpy.app.timers.is_registered(fn):
        bpy.app.timers.unregister(fn)
if handler in bpy.app.handlers.depsgraph_update_post:
    bpy.app.handlers.depsgraph_update_post.remove(handler)
if getattr(drv, "_stall_draw_handle", None):
    bpy.types.SpaceView3D.draw_handler_remove(drv._stall_draw_handle, "WINDOW")
bpy.utils.unregister_class(bpy.types.QA_OT_stall)
result = True
'''


def new_records(qa):
    return qa.eval('from mixar.modules.common.utils import stall_log\n'
                   'result = stall_log.read_stalls(drv._stall_path, since_seq=drv._stall_seq)')


def wait_record(qa, kind, name_part, phase_index):
    """Block until a new record holds a breadcrumb of `kind` whose name contains
    `name_part`; assert the stall's dominant phase and return the record."""
    qa.wait('any(any(c["k"] == %r and %r in c["n"] for c in r["top"]) '
            'for r in __import__("mixar.modules.common.utils.stall_log", fromlist=["x"])'
            '.read_stalls(drv._stall_path, since_seq=drv._stall_seq))' % (kind, name_part),
            timeout=15)
    record = next(r for r in new_records(qa)
                  if any(c['k'] == kind and name_part in c['n'] for c in r['top']))
    assert record['ms'] >= 100, record
    assert max(range(4), key=lambda i: record['ph'][i]) == phase_index, record
    qa.eval(f'drv._stall_seq = {record["seq"]}; result=True')
    return record


def crumb(record, kind, name_part=''):
    return next(c for c in record['top'] if c['k'] == kind and name_part in c['n'])


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/stall-monitor'))
    out.mkdir(parents=True, exist_ok=True)
    qa.wait("hasattr(bpy.types.Scene, 'mixie_chat_input')", timeout=30)
    path = qa.eval(SETUP)
    assert path.endswith('stalls.jsonl'), path
    records = {}
    try:
        qa.dismiss_splash()
        # 1. A bpy.app.timers function: timers run in the notifiers phase, kind timer.
        qa.eval('bpy.app.timers.register(drv._stall_fns[0], first_interval=0.05); result=True')
        records['timer'] = wait_record(qa, 'timer', 'qa_stall_timer', 2)
        assert crumb(records['timer'], 'timer', 'qa_stall_timer')['d'] == 0

        # 2. An operator run from a timer: the timer is depth 0, the operator depth 1.
        qa.eval('bpy.app.timers.register(drv._stall_fns[1], first_interval=0.05); result=True')
        records['op'] = wait_record(qa, 'op', 'QA_OT_stall', 2)
        assert crumb(records['op'], 'op', 'QA_OT_stall')['d'] == 1, records['op']
        assert crumb(records['op'], 'timer', 'qa_stall_timer_op')['d'] == 0

        # 3. bpy.app.handlers.depsgraph_update_post, fired by a real scene edit made from
        #    the harness pump timer: the handler nests under that timer (notifiers phase).
        qa.eval('bpy.app.handlers.depsgraph_update_post.append(drv._stall_fns[2]); '
                'bpy.context.scene["qa_stall_armed"] = True; '
                'bpy.ops.mesh.primitive_cube_add(location=(7, 7, 7)); result=True')
        records['handler'] = wait_record(qa, 'handler', 'qa_stall_handler', 2)
        handler = crumb(records['handler'], 'handler', 'qa_stall_handler')
        assert handler['n'].startswith('depsgraph_update_post:') and handler['d'] >= 1, handler

        # 4. A Python viewport draw handler: draw phase, kind draw_cb under the region draw.
        qa.eval('drv._stall_draw_handle = bpy.types.SpaceView3D.draw_handler_add('
                'drv._stall_fns[3], (), "WINDOW", "POST_PIXEL")\n'
                'for a in bpy.context.screen.areas:\n'
                '    a.tag_redraw()\n'
                'result=True')
        records['draw_cb'] = wait_record(qa, 'draw_cb', 'qa_stall_draw', 3)
        region = crumb(records['draw_cb'], 'draw', 'View3D/WINDOW')
        assert crumb(records['draw_cb'], 'draw_cb', 'qa_stall_draw')['d'] == region['d'] + 1, records

        # 5. A 1.2 s Python stall: the watchdog thread must have written a py_stack line
        #    for that iteration naming the sleeping timer, joined to the record on `it`.
        qa.eval('bpy.app.timers.register(drv._stall_fns[4], first_interval=0.05); result=True')
        records['py_stack'] = wait_record(qa, 'timer', 'qa_stall_timer_long', 2)
        stacks = records['py_stack'].get('py_stacks') or []
        assert stacks and any('qa_stall_timer_long' in f for f in stacks[0]['stack']), records['py_stack']
        assert stacks[0]['stalled_ms'] >= 400 and stacks[0]['it'] == records['py_stack']['it'], stacks[0]

        (out / 'records.json').write_text(json.dumps(records, indent=1))
        return {'stalls_attributed': len(records), 'log': path, 'evidence': str(out)}
    finally:
        qa.eval(TEARDOWN)
        qa.eval('bpy.ops.object.select_all(action="DESELECT"); '
                'o = bpy.data.objects.get("Cube.001") or bpy.data.objects.get("Cube")\n'
                'if o and tuple(round(v) for v in o.location) == (7, 7, 7):\n'
                '    bpy.data.objects.remove(o)\n'
                'result=True')


if __name__ == '__main__':
    run_scenario('stall_monitor_e2e', run)
