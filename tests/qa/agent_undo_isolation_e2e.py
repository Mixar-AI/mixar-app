#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit interleaved agent/manual tabs and worker-lane undo ownership.

Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT; see docs/modules/undo-validation.md. Uses real
request routing, script execution, terminal handling and native undo/redo.
Three independent clean-file cases; inspect the framed viewport screenshots.
"""

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
sys.path.insert(0, str(Path(__file__).parent))
from lib import ScenarioFail, run_scenario
from undo_turn_fixture import INSTALL, RESTORE, capture, output_dir, reset, walk, write_results


SETUP = '''
import json
from mixar.modules.space_mixie_chat.ui.operators.scene_tab_ops import new_scene_tab, switch_scene_tab
from mixar.modules.space_mixie_chat.core.main_thread_routing import route_request, restore_after
from mixar.modules.common.agent_execution.pump import execute_request
from mixar.modules.common.agent_execution.request import ExecutionRequest
from mixar.modules.space_mixie_chat.core.executor import get_executor
w = drv.main_window()
manual = w.scene
manual.name = 'UndoManual'
manual.mixie_session_id = 'qa-undo-inter-Manual'
obj = next(o for o in manual.objects if o.type == 'MESH')
obj.name = 'QA_MANUAL'
obj.location.x = 0
for label in ('A', 'B'):
    scene = new_scene_tab('Undo' + label)
    scene.mixie_session_id = 'qa-undo-inter-' + label
    mesh = bpy.data.meshes.new('QA_' + label)
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new('QA_' + label, mesh)
    scene.collection.objects.link(obj)
    bpy.context.window_manager.mixar_undo_push('QA baseline ' + label, scene=scene)
switch_scene_tab(manual)
bpy.context.window_manager.mixar_undo_push('QA manual baseline', scene=manual)
bpy.data.objects['QA_MANUAL'].location.x = 7
bpy.context.window_manager.mixar_undo_push('QA manual edit', scene=manual)
ex = get_executor()
ex.begin_agent_turn('qa-undo-inter-A')
ex.begin_agent_turn('qa-undo-inter-B')
routes = []
for label, x in [('A', 1), ('B', 10), ('A', 2), ('B', 20)]:
    sid = 'qa-undo-inter-' + label
    target, switched, error = route_request(sid, 'execute_bpy_script', 'qa-undo-inter')
    assert not error, error
    try:
        req = ExecutionRequest(request_id='qa-undo-inter-' + label,
                               script=f"bpy.data.objects['QA_{label}'].location.x = {x}",
                               tool_name='execute_blender_code', session_id=sid)
        reply = execute_request(req, ex)
        assert reply.get('success'), reply
    finally:
        restore_after(switched)
    routes.append({'tab': label, 'x': x, 'window': w.scene.name})
for label in ORDER:
    ex.end_agent_turn('qa-undo-inter-' + label, checkpoint=True)
result = {
    'script_routes': routes,
    'history': json.loads(bpy.context.window_manager.mixar_undo_history),
    'values': {label: float(bpy.data.objects['QA_' + label].location.x)
               for label in ('A', 'B', 'MANUAL')},
    'window': w.scene.name,
    'uids': {s.name: s.session_uid for s in bpy.data.scenes},
}
'''

STATE = '''
result = {
    'values': {label: float(bpy.data.objects['QA_' + label].location.x)
               for label in ('A', 'B', 'MANUAL')},
    'window': drv.main_window().scene.name,
    'scenes': sorted(s.name for s in bpy.data.scenes),
}
'''

LANE_COMPLETE = '''
import json
from mixar.modules.space_mixie_chat.core.queue_processor import get_event_processor
lane = bpy.data.scenes.new('Workspace_QA_Lane')
lane.mixie_session_id = 'agentlane:qa-undo-inter-A:1'
lane['mixar_workspace_main_session'] = 'qa-undo-inter-A'
w = drv.main_window()
w.scene = lane
get_event_processor()._handle_agent_complete_internal(bpy.data.scenes['UndoA'])
history = json.loads(bpy.context.window_manager.mixar_undo_history)
uid = bpy.data.scenes['UndoA'].session_uid
steps = [h['name'] for h in history['steps']
         if h['tab_uid'] == uid and h['name'].startswith('Mixie')]
window_after_complete = w.scene.name
w.scene = bpy.data.scenes['UndoManual']
bpy.data.scenes.remove(lane)
get_event_processor()._handle_agent_complete_internal(bpy.data.scenes['UndoB'])
bpy.context.window_manager.mixar_undo_push('QA manual after lane cleanup', scene=w.scene)
result = {'steps': steps, 'window_after_complete': window_after_complete}
'''


def tab_walk(qa, operation, tab):
    name = 'MANUAL' if tab == 'Manual' else tab
    walk(qa, operation, tab='Undo' + tab, object_name='QA_' + name)
    return qa.eval(STATE)


def interleaved(qa, order):
    setup = qa.eval('ORDER = ' + repr(order) + '\n' + SETUP)
    steps = {
        label: [h['name'] for h in setup['history']['steps']
                if h['tab_uid'] == setup['uids']['Undo' + label] and h['name'].startswith('Mixie')]
        for label in ('A', 'B')
    }
    states = {}
    checks = {
        'two_owned_steps_each': all(v == ['Mixie Chat Turn', 'Mixie Chat Script'] for v in steps.values()),
        'routing_returns_manual': all(r['window'] == 'UndoManual' for r in setup['script_routes']),
    }
    for tab in ('A', 'B', 'Manual'):
        undone = states[tab + '_undo'] = tab_walk(qa, 'undo', tab)
        redone = states[tab + '_redo'] = tab_walk(qa, 'redo', tab)
        expected = dict(setup['values'])
        expected['MANUAL' if tab == 'Manual' else tab] = 0
        checks[tab + '_undo_isolated'] = undone['values'] == expected
        checks[tab + '_redo_isolated'] = redone['values'] == setup['values']
        checks[tab + '_view_retained'] = undone['window'] == 'Undo' + tab == redone['window']
    checks['no_lanes_or_phantoms'] = all(
        state['scenes'] == ['UndoA', 'UndoB', 'UndoManual'] for state in states.values())
    return {'case': 'interleaved_' + ''.join(order), 'setup': setup,
            'step_names': steps, 'states': states, 'checks': checks, 'ok': all(checks.values())}


def worker_lane(qa):
    setup = qa.eval('ORDER = []\n' + SETUP)
    closing = qa.eval(LANE_COMPLETE)
    undone, redone = tab_walk(qa, 'undo', 'A'), tab_walk(qa, 'redo', 'A')
    checks = {
        'closing_step_owned_by_parent': closing['steps'] == ['Mixie Chat Turn', 'Mixie Chat Script'],
        'completion_keeps_lane_view': closing['window_after_complete'] == 'Workspace_QA_Lane',
        'undo_parent_only': undone['values'] == {'A': 0, 'B': 20, 'MANUAL': 7},
        'redo_parent_complete': redone['values'] == setup['values'],
        'lane_not_resurrected': all(s['scenes'] == ['UndoA', 'UndoB', 'UndoManual']
                                  for s in (undone, redone)),
        'view_stays_parent': undone['window'] == 'UndoA' == redone['window'],
    }
    return {'case': 'worker_lane', 'checks': checks, 'closing': closing,
            'undo': undone, 'redo': redone, 'ok': all(checks.values())}


def run(qa):
    out = output_dir('agent-undo-isolation')
    cases = [('interleaved_AB', lambda: interleaved(qa, ['A', 'B'])),
             ('interleaved_BA', lambda: interleaved(qa, ['B', 'A'])),
             ('worker_lane', lambda: worker_lane(qa))]
    rows = []
    for name, exercise in cases:
        reset(qa)
        try:
            qa.eval(INSTALL)
            row = qa.step(name, exercise)
            rows.append(row)
            write_results(out, rows)
            capture(qa, out / (name + '.png'))
            if not row['ok']:
                raise ScenarioFail(f'{name}: {row["checks"]}')
        finally:
            qa.eval(RESTORE)
    return {'cases': rows, 'backend_turns': 0}


if __name__ == '__main__':
    run_scenario('agent_undo_isolation_e2e', run)
