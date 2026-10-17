#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit real-app agent undo budgets, terminal paths and redo preservation.

Use an isolated Dev app with per-tab undo. Set QA_HARNESS, MIXAR_QA_PORT and
QA_SCENARIO_OUT; see docs/modules/undo-validation.md. Cancels are captured locally and restored in a
finally block. Tool payloads are representative reads/writes, not full backend
tool implementations. Stream errors may retain BUSY; release the synthetic
UI state before testing native undo. Inspect the captured viewport.
"""

from dataclasses import dataclass
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
sys.path.insert(0, str(Path(__file__).parent))
from lib import ScenarioFail, run_scenario
from undo_turn_fixture import (
    ENDINGS, IDLE, INSTALL, RESTORE, TURN_RESULT, TURN_SETUP,
    capture, output_dir, reset, walk, write_results,
)


WRITE = '''
sm.set_state(s, SessionState.BUSY)
for x in (1, 2, 3):
    ex.begin_agent_turn(sid)
    script(f"bpy.data.objects['QA_UNDO_OBJECT'].location.x = {x}")
'''
READ = '''
from mixar.modules.space_mixie_chat.constants import AGENT_UNDO_NEUTRAL_TOOLS
assert AGENT_UNDO_NEUTRAL_TOOLS, 'The read-only tool contract must be populated'
for tool in sorted(AGENT_UNDO_NEUTRAL_TOOLS):
    script("__RESULT__ = {'objects': len(bpy.data.objects)}", tool)
'''
LONG_WRITE = '''
for x in range(1, 42):
    script(f"bpy.data.objects['QA_UNDO_OBJECT'].location.x = {x}")
'''
RENDER = '''
script("bpy.data.objects['QA_UNDO_OBJECT'].location.x = 5", 'render_scene_image')
'''


@dataclass(frozen=True)
class Case:
    name: str
    body: str
    ending: str
    steps: int
    roundtrip: bool = False
    duplicate: bool = False


def lifecycle_cases():
    for ending in ('complete', 'stream_error', 'inband_error', 'abort', 'replay_unavailable'):
        yield Case(ending, WRITE, ending, 2, roundtrip=True, duplicate=ending == 'complete')
    yield Case('all_neutral_tools', READ, 'complete', 0)
    yield Case('empty_complete', '', 'complete', 0)
    yield Case('refused_without_work', '', 'refused', 0)
    for ending in ('end_all', 'end_default', 'tab_cleanup', 'load_pre'):
        yield Case(ending, WRITE, ending, 1)
    yield Case('long_grouped_turn', LONG_WRITE, 'complete', 2, roundtrip=True)
    yield Case('render_is_effectful', RENDER, 'complete', 2, roundtrip=True)


def lifecycle(qa, case):
    row = qa.eval(f'CASE = {case.name!r}\n' + TURN_SETUP + case.body
                  + '\n' + ENDINGS[case.ending] + '\n' + TURN_RESULT)
    checks = {'step_budget': row['delta'] == case.steps, 'turn_closed': not row['turns']}
    if case.duplicate:
        repeated = qa.eval('''
import json
from mixar.modules.space_mixie_chat.core.queue_processor import get_event_processor
s = drv.main_window().scene
get_event_processor()._handle_agent_complete_internal(s)
result = len([h for h in json.loads(bpy.context.window_manager.mixar_undo_history)['steps']
              if h['tab_uid'] == s.session_uid])
''')
        checks['duplicate_terminal_does_not_push'] = repeated == row['after_steps']
    if case.roundtrip:
        qa.eval(IDLE)
        row['undo'] = undone = walk(qa, 'undo')
        row['redo'] = redone = walk(qa, 'redo')
        checks.update(
            undo_restores_start=undone['x'] == 0,
            redo_restores_final=redone['x'] == row['x'],
            window_stays_on_tab=undone['scene'] == row['scene'] == redone['scene'],
            idle_stays_idle=undone['state'] == 'IDLE' == redone['state'],
            session_identity_preserved=undone['sid'] == row['session_id'] == redone['sid'],
        )
    row.update(expected_steps=case.steps, checks=checks, ok=all(checks.values()))
    return row


def cleanup_preserves_redo(qa, ending):
    row = lifecycle(qa, Case('redo_' + ending, WRITE, 'complete', 2))
    qa.eval(IDLE)
    row['undo'] = walk(qa, 'undo')
    cleanup = qa.eval('''
import json
from mixar.modules.space_mixie_chat.core.executor import get_executor
from mixar.modules.space_mixie_chat.core.queue_processor import get_event_processor
w = drv.main_window()
s = w.scene
sid = s.mixie_session_id
ex = get_executor()
before = json.loads(bpy.context.window_manager.mixar_undo_history)
''' + ENDINGS[ending] + '''
after = json.loads(bpy.context.window_manager.mixar_undo_history)
result = {'before': before, 'after': after}
''')
    row['redo'] = walk(qa, 'redo')
    row['cleanup'] = cleanup
    row['checks'].update(
        cleanup_does_not_change_history=cleanup['before'] == cleanup['after'],
        undo_restores_start=row['undo']['x'] == 0,
        cleanup_preserves_redo=row['redo']['x'] == 3,
        window_stays_on_tab=row['undo']['scene'] == row['scene'] == row['redo']['scene'],
    )
    row['ok'] = all(row['checks'].values())
    return row


def run(qa):
    out = output_dir('agent-undo-lifecycle')
    cases = [(c.name, lambda c=c: lifecycle(qa, c)) for c in lifecycle_cases()]
    cases.extend(('redo_' + ending, lambda e=ending: cleanup_preserves_redo(qa, e))
                 for ending in ('end_all', 'end_default', 'tab_cleanup'))
    rows = []
    for name, exercise in cases:
        reset(qa)
        try:
            qa.eval(INSTALL)
            row = qa.step(name, exercise)
            rows.append(row)
            write_results(out, rows)
            if not row['ok']:
                raise ScenarioFail(f'{name}: {row["checks"]}')
        finally:
            qa.eval(RESTORE)
    capture(qa, out / 'final-redo.png')
    return {'cases': rows, 'passed': len(rows), 'backend_turns': 0,
            'boundary': 'Real executor/pump/terminal handlers/native history; outbound cancels captured'}


if __name__ == '__main__':
    run_scenario('agent_undo_lifecycle_e2e', run)
