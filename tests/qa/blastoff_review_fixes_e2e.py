# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""No-credit replay for dismissed cards, document fences and journal recovery.

Run against a fresh isolated Dev app started by $QA_HARNESS/run_qa_app.sh:
    QA_HARNESS=/path/to/mixar-qa-harness python3 tests/qa/blastoff_review_fixes_e2e.py
Uses MIXAR_QA_PORT and QA_SCENARIO_OUT. No backend jobs or real user data.
"""

import os
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(os.environ["QA_HARNESS"]) / "scenarios"))
from lib import ScenarioFail, run_scenario


ITEMS = [
    {"id": "qa-canopy", "text": "Build the canopy.", "status": "FAILED"},
    {"id": "qa-brakes", "text": "Build the brakes.", "status": "FAILED"},
]
CARDS = "bpy.data.window_managers[0].mixar_agent_cards"
IMPORT_CARDS = "from mixar.modules.agent_panel.core import cards\n"

SETUP_PROTOCOL = '''
import tempfile
from types import SimpleNamespace
from mixar.modules.common.agent_execution import bindings, document
from mixar.modules.common.agent_execution.journal import Journal
assert not bindings._by_run, "Use a fresh isolated app with no real agent turns"
assert document._registered, "Document undo/load handlers must be registered by bootstrap"
scratch = tempfile.TemporaryDirectory(prefix="mixar-review-qa-")
drv._review_fixture = SimpleNamespace(scratch=scratch, journals=[])
journal = Journal(scratch.name + "/journal.sqlite")
drv._review_fixture.journals.append(journal)
identity = document.document_identity()
w = drv.main_window()
a = next(a for a in w.screen.areas if a.type == 'VIEW_3D')
r = next(r for r in a.regions if r.type == 'WINDOW')
with bpy.context.temp_override(window=w, area=a, region=r):
    bpy.ops.ed.undo_push(message="QA document baseline")
activation = bindings.activate(
    {'run_id': 'qa-run', 'session_id': 'qa-session', 'turn_epoch': 1}, journal=journal)
assert activation['success'] and activation['document_id'] == identity['document_id']
assert bindings.bind_task(
    {'run_id': 'qa-run', 'turn_epoch': 1, 'task_id': 'qa-task', 'fence_token': 1},
    journal=journal)['success']
drv._review_fixture.identity = identity
with bpy.context.temp_override(window=w, area=a, region=r):
    bpy.ops.mesh.primitive_cube_add('EXEC_DEFAULT', True, location=(4, 0, 0))
    bpy.context.object.name = "QA_Review_Undo"
result = True
'''

UNDO = '''
w = drv.main_window()
a = next(a for a in w.screen.areas if a.type == 'VIEW_3D')
r = next(r for r in a.regions if r.type == 'WINDOW')
with bpy.context.temp_override(window=w, area=a, region=r):
    assert bpy.ops.ed.undo() == {'FINISHED'}
result = True
'''

CHECK_PROTOCOL = '''
import uuid
from mixar.modules.common.agent_execution import bindings, commit, document
journal = drv._review_fixture.journals[0]
identity = document.document_identity()
assert identity['document_epoch'] > drv._review_fixture.identity['document_epoch']
assert identity['document_id'] == drv._review_fixture.identity['document_id']
assert bpy.data.objects.get('QA_Review_Undo') is None
activation = bindings.activate(
    {'run_id': 'qa-run', 'session_id': 'qa-session', 'turn_epoch': 1}, journal=journal)
params = dict(run_id='qa-run', turn_epoch=1, task_id='qa-task', fence_token=1,
              operation_id='qa-commit', payload_hash='qa-payload',
              collection_name='QA_Review', artifact_id=str(uuid.uuid4()), content_hash='0' * 64)
publish = commit.append_collection(params, journal=journal)
assert not activation['success'] and not publish['success']
assert activation['error_type'] == publish['error_type'] == 'stale_epoch'
assert journal.op_get('qa-commit') is None
fresh = bindings.activate(
    {'run_id': 'qa-new-run', 'session_id': 'qa-session', 'turn_epoch': 2}, journal=journal)
assert fresh['success'] and fresh['document_epoch'] == identity['document_epoch']
result = True
'''

CHECK_JOURNAL = '''
from mixar.modules.common.agent_execution.journal import Journal, RUNNING, UNKNOWN, APPLIED
fixture = drv._review_fixture
first = fixture.journals[0]
def running(journal, operation_id):
    journal.op_prepare(operation_id, run_id='qa-journal', task_id=operation_id, generation=0,
                       fence=1, payload_hash='qa', document_id='qa', document_epoch=1,
                       artifact_id='qa')
    journal.op_set_state(operation_id, RUNNING)
running(first, 'qa-first')
second = Journal(first.path)
fixture.journals.append(second)
assert second.op_get('qa-first')['state'] == RUNNING
running(second, 'qa-second')
first.close()
third = Journal(first.path)
fixture.journals.append(third)
assert third.op_get('qa-first')['state'] == UNKNOWN
assert third.op_get('qa-second')['state'] == RUNNING
second.op_set_state('qa-second', APPLIED, {'verified': True})
assert third.op_get('qa-second')['receipt'] == {'verified': True}
result = True
'''

CLEANUP = '''
from mixar.modules.agent_panel.core import cards
from mixar.modules.common.agent_execution import bindings, document
cards.clear_cards()
bindings.reset()
document.set_run_active(False)
document.clear_foreground_tasks()
fixture = getattr(drv, '_review_fixture', None)
if fixture:
    for journal in fixture.journals:
        journal.close()
    fixture.scratch.cleanup()
    del drv._review_fixture
result = True
'''


def evaluate(qa, code):
    assert qa.eval(code) is True


def wait_for_settled_cards(qa):
    """Targets exist mid-entrance; capture only after their geometry settles."""
    deadline = time.monotonic() + 10
    previous = None
    stable_since = time.monotonic()
    while time.monotonic() < deadline:
        widgets = qa.find(surface="agent_panel_card")["widgets"]
        geometry = [(w["index"], w["rect"]) for w in widgets]
        now = time.monotonic()
        if geometry != previous:
            previous, stable_since = geometry, now
        elif len(widgets) == 2 and now - stable_since >= 0.3:
            return
        time.sleep(0.1)
    raise ScenarioFail("the two card targets did not finish their entrance")


def run(qa):
    out = Path(os.environ.get("QA_SCENARIO_OUT") or tempfile.mkdtemp(prefix="mixar-review-qa-"))
    out.mkdir(parents=True, exist_ok=True)
    evaluate(qa, 'import os; assert os.environ.get("MIXAR_QA") == "1"; result=True')
    qa.cmd("wait_login", timeout=90)
    qa.wait("hasattr(bpy.context.window_manager, 'mixar_agent_cards')", timeout=30)
    try:
        qa.step("seed two failed cards", evaluate, qa, IMPORT_CARDS +
                f"cards.clear_cards()\nassert cards.mirror_todo_items({ITEMS!r}) == 2\nresult=True")
        qa.wait("len(drv.find(surface='agent_panel_card')) == 2", timeout=15)
        qa.step("wait for initial entrance to finish", wait_for_settled_cards, qa)
        qa.cmd("snap", path=str(out / "before-dismiss.png"),
               target={"surface": "agent_panel_card"},
               annotate={"surface": "agent_panel_card"}, margin=400)
        qa.step("dismiss through the real panel", qa.click, surface="agent_panel_dismiss", index=0)
        qa.wait(f"[c.task_id for c in {CARDS}] == ['qa-brakes']", timeout=10)
        for index in range(3):
            qa.step(f"restream {index + 1} preserves dismissal", evaluate, qa, IMPORT_CARDS +
                    f"assert cards.mirror_todo_items({ITEMS!r}) == 0\n"
                    f"assert not {CARDS}\n"
                    "assert 'qa-canopy' in cards._dismissed_task_ids\nresult=True")
        qa.wait("not drv.find(surface='agent_panel_card')", timeout=10)
        qa.cmd("snap", path=str(out / "after-restream.png"), area="VIEW_3D")
        qa.step("new turn forgets the old dismissal", evaluate, qa, IMPORT_CARDS +
                f"cards.clear_cards()\nassert cards.mirror_todo_items({ITEMS!r}) == 2\nresult=True")
        qa.wait("len(drv.find(surface='agent_panel_card')) == 2", timeout=15)
        qa.step("wait for next-turn entrance to finish", wait_for_settled_cards, qa)
        qa.cmd("snap", path=str(out / "next-turn.png"),
               target={"surface": "agent_panel_card"}, margin=400)
        evaluate(qa, IMPORT_CARDS + "cards.clear_cards()\nresult=True")
        qa.step("activate a real document and add an undo step", evaluate, qa, SETUP_PROTOCOL)
        qa.step("undo through Blender", evaluate, qa, UNDO)
        qa.step("activation and commit refuse the stale document", evaluate, qa, CHECK_PROTOCOL)
        qa.step("recover only the abandoned journal owner", evaluate, qa, CHECK_JOURNAL)
        qa.cmd("snap", path=str(out / "after-undo.png"), area="VIEW_3D")
        return {"credits_spent": 0, "snapshots": [str(path) for path in sorted(out.glob("*.png"))]}
    finally:
        evaluate(qa, CLEANUP)


if __name__ == "__main__":
    run_scenario("blastoff_review_fixes", run)
