# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""A scene render start and the UI gates during a bake name the bake: no backend needed.

render_scene_image / render_scene_video are read-only scripts, so they pass the
script gate during the agent's own bake and reach scene_render's busy check.
Their ``busy`` / ``another_render_running`` reply must carry ``render_kind``
``bake`` (so the backend waits the bake out instead of telling the user that
someone else is rendering), and the ui_control / scene-tab gates must say
"Wait for the bake to finish" with ``render_kind`` ``bake``. The same Cycles
bake as bake_gate_e2e runs on the Cube; the start goes through the REAL
``mixar.scene_render_start`` operator, the gates through their real functions.

Fixed build: PASS. Unfixed build (feature/mixar-blastoff 7c16538a5): ScenarioFail
at ``busy_reply_names_bake`` (the reply has no ``render_kind``), and the gates
still say "Wait for the render to finish".
QA_HARNESS, MIXAR_QA_PORT, QA_SCENARIO_OUT select harness, app and evidence.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario  # noqa: E402
from bake_gate_e2e import SETUP, START  # noqa: E402

DURING = '''
from mixar.modules.common.ui_control.constants import UIError
from mixar.modules.common.ui_control.core import ownership
from mixar.modules.mcp_bridge.core import scene_tabs
from mixar.modules.scene_render.constants import RESPONSE_NS
alive = bpy.app.is_job_running('OBJECT_BAKE')
ns = bpy.app.driver_namespace
ns.pop(RESPONSE_NS, None)
with bpy.context.temp_override(window=drv.main_window()):
    bpy.ops.mixar.scene_render_start(job_key='c' * 32, kind='image')
reply = dict(ns.pop(RESPONSE_NS))
gates = {}
for name, gate in (('ui_control', ownership.available), ('scene_tab', scene_tabs._gate)):
    try:
        gate()
        gates[name] = None
    except UIError as exc:
        gates[name] = exc.result()
result = {'bake_alive': alive, 'reply': reply, 'gates': gates}
'''


def run(qa):
    output = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/bake-render-busy-evidence')).resolve()
    output.mkdir(parents=True, exist_ok=True)
    qa.step('reset', qa.cmd, 'reset_state')
    qa.step('dismiss_splash', qa.dismiss_splash)
    qa.step('setup', qa.eval, SETUP)
    try:
        qa.step('bake_start', qa.eval, START)
        qa.step('bake_running', qa.wait, "bpy.app.is_job_running('OBJECT_BAKE')", timeout=15)
        during = qa.step('render_and_gates_during_bake', qa.eval, DURING)
        if not during['bake_alive']:
            raise ScenarioFail('bake finished before the render start was answered; raise SAMPLES or SIZE')
        qa.step('during_bake', qa.snap, str(output / 'during-bake.png'))
        qa.step('busy_reply_names_bake', _expect_bake_reply, during['reply'])
        qa.step('gates_name_bake', _expect_bake_gates, during['gates'])
    finally:  # never hand a running bake to the next scenario
        qa.wait("not bpy.app.is_job_running('OBJECT_BAKE')", timeout=600)
    return {'reply': during['reply'], 'gates': during['gates'], 'output': str(output)}


def _expect_bake_reply(reply):
    """The unfixed build fails here: the busy reply did not say what was running."""
    expected = {'status': 'busy', 'error': 'another_render_running', 'render_kind': 'bake'}
    if any(reply.get(key) != value for key, value in expected.items()):
        raise ScenarioFail(f'scene_render busy reply does not name the bake: {reply}')
    return reply


def _expect_bake_gates(gates):
    for name, refusal in gates.items():
        if not refusal or refusal.get('error_type') != 'render_in_progress' \
                or refusal.get('render_kind') != 'bake' or 'bake' not in refusal.get('error', ''):
            raise ScenarioFail(f'{name} gate does not name the bake: {refusal}')
    return gates


if __name__ == '__main__':
    run_scenario('bake_render_busy_reply', run)
