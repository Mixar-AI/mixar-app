# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Real producers preserve brief activity without delaying execution or state."""

import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

# Load the production producer modules without core/__init__ starting network
# clients. The separate namespace leaves other suites' package state untouched.
MODULE = (Path(__file__).resolve().parents[1] / 'src/scripts/mixar/modules/space_mixie_chat')
for name, path in [('cat_pulse_contract', MODULE), ('cat_pulse_contract.core', MODULE/'core')]:
    package = ModuleType(name)
    package.__path__ = [str(path)]
    sys.modules[name] = package
SessionState = importlib.import_module('cat_pulse_contract.constants').SessionState
cat_activity = importlib.import_module('cat_pulse_contract.core.cat_activity')
slot_processor = importlib.import_module('cat_pulse_contract.core.slot_processor')
steps_recorder = importlib.import_module('cat_pulse_contract.core.steps_recorder')
SessionManager = importlib.import_module('cat_pulse_contract.core.session').SessionManager


class Rows(list):
    def add(self):
        row = SimpleNamespace()
        self.append(row)
        return row


class Bubble(SimpleNamespace):
    def __setitem__(self, name, value):
        setattr(self, name, value)


@pytest.fixture
def fixture(monkeypatch):
    clock = [1_800_000_000.125]
    monkeypatch.setattr(cat_activity.time, 'time', lambda: clock[0])
    monkeypatch.setattr(steps_recorder, 'bump_layout_epoch', lambda scene: None)
    monkeypatch.setattr(steps_recorder, 'redraw_chat_areas', lambda: None)
    monkeypatch.setattr(slot_processor, '_bump_layout_epoch', lambda scene: None)
    bubble = Bubble(sender='AGENT', bubble_id='current', step_items=Rows(),
                    thinking_active=False, thinking_text='', thinking_collapsed=True,
                    thinking_start_time=0.0, thinking_duration_ms=0, ephemeral='',
                    content='', text='')
    scene = SimpleNamespace(name='CatPulseTest', mixie_chat_state='BUSY',
                            mixie_chat_is_busy=True, mixie_session_id='session',
                            mixie_chat_messages=[bubble], mixie_chat_cat_activity='',
                            mixie_chat_cat_activity_until='')
    processor = slot_processor.SlotEventProcessor.__new__(slot_processor.SlotEventProcessor)
    processor._reparse_content_markdown = lambda *args, **kwargs: None
    yield scene, bubble, processor, clock
    SessionManager._active_scenes.discard(scene.name)


@pytest.mark.parametrize(('tool', 'activity'), [('get_scene', 'READING'),
                                               ('execute_bpy_script', 'WORKING')])
def test_synchronous_step_start_and_end_leave_readable_activity(fixture, tool, activity):
    scene, bubble, _, clock = fixture
    # Matches the executor: both producers run before any UI draw can happen.
    steps_recorder.record_step_start(scene, 'request', tool)
    steps_recorder.record_step_end(scene, 'request', {'success': True})
    assert bubble.step_items[0].status == 'DONE'
    assert scene.mixie_chat_state == 'BUSY'
    assert scene.mixie_chat_cat_activity == activity
    assert float(scene.mixie_chat_cat_activity_until) == pytest.approx(clock[0] + .9, abs=1e-6)
    assert abs(float(scene.mixie_chat_cat_activity_until) - clock[0] - .9) < 1e-6
    assert isinstance(scene.mixie_chat_cat_activity_until, str)


def test_content_and_completion_in_one_batch_keep_only_finishing_reaction(fixture):
    scene, bubble, processor, _ = fixture
    processor._apply_content_slot(bubble, {'set': 'The scene is ready.'}, scene)
    # Same state path as SSE completion, with no draw between content and IDLE.
    SessionManager.set_state(scene, SessionState.IDLE)
    slot_processor.finalize_turn(scene)
    assert scene.mixie_chat_cat_activity == 'RESPONDING'
    assert scene.mixie_chat_state == 'IDLE'
    assert not scene.mixie_chat_is_busy
    assert bubble.content == 'The scene is ready.'


def test_new_content_and_reasoning_override_completed_tool(fixture):
    scene, bubble, processor, _ = fixture
    steps_recorder.record_step_start(scene, 'read', 'get_scene')
    steps_recorder.record_step_end(scene, 'read', {'success': True})
    processor._apply_content_slot(bubble, {'set': 'A response'}, scene)
    assert scene.mixie_chat_cat_activity == 'RESPONDING'
    # A reasoning clear commonly follows final content in the same batch.
    processor._apply_ephemeral_slot(bubble, {'clear': True}, scene)
    assert scene.mixie_chat_cat_activity == 'RESPONDING'
    processor._apply_ephemeral_slot(bubble, {'append': 'Consider the next step'}, scene)
    assert bubble.thinking_active
    assert scene.mixie_chat_cat_activity == ''
    assert scene.mixie_chat_cat_activity_until == ''


@pytest.mark.parametrize('state', [SessionState.AWAITING_INPUT, SessionState.MODIFYING,
                                  SessionState.OFFLINE, SessionState.CONNECTING])
def test_waiting_and_connectivity_clear_pulse_and_reject_late_tool(fixture, state):
    scene, bubble, _, _ = fixture
    steps_recorder.record_step_start(scene, 'read', 'get_scene')
    steps_recorder.record_step_end(scene, 'read', {'success': True})
    SessionManager.set_state(scene, state)
    steps_recorder.record_step_end(scene, 'read', {'success': True})
    assert scene.mixie_chat_cat_activity == ''
    assert scene.mixie_chat_cat_activity_until == ''
    assert scene.mixie_chat_state == state.value.upper()


def test_new_turn_and_cleared_session_do_not_inherit_response(fixture):
    scene, bubble, processor, _ = fixture
    processor._apply_content_slot(bubble, {'append': 'Done'}, scene)
    SessionManager.start_session(scene, 'Continue')
    assert scene.mixie_chat_cat_activity == ''
    processor._apply_content_slot(bubble, {'append': 'Again'}, scene)
    SessionManager.clear_session_id(scene)
    assert scene.mixie_chat_cat_activity == ''
    assert scene.mixie_session_id == ''


@pytest.mark.parametrize('offset', [1.0, -1.0])
def test_expired_or_clock_shifted_response_cannot_survive_idle(fixture, offset):
    scene, bubble, processor, clock = fixture
    processor._apply_content_slot(bubble, {'set': 'Done'}, scene)
    clock[0] += offset
    SessionManager.set_state(scene, SessionState.IDLE)
    assert scene.mixie_chat_cat_activity == ''


def test_internal_or_unmatched_steps_do_not_emit_reactions(fixture):
    scene, bubble, _, _ = fixture
    steps_recorder.record_step_start(scene, 'request', '_scene_snapshot')
    steps_recorder.record_step_end(scene, 'request', {'success': True})
    assert not bubble.step_items
    assert scene.mixie_chat_cat_activity == ''


def test_history_content_while_idle_does_not_reanimate_cat(fixture):
    scene, bubble, processor, _ = fixture
    SessionManager.set_state(scene, SessionState.IDLE)
    processor._apply_content_slot(bubble, {'set': 'Historical reply'}, scene)
    assert scene.mixie_chat_cat_activity == ''


def test_native_bridge_properties_are_transient_decimal_strings():
    source = (Path(__file__).resolve().parents[1] / 'src/scripts/mixar/modules/'
              'space_mixie_chat/ui/properties/cat_activity_props.py').read_text()
    assert source.count('StringProperty(') == 2
    assert source.count("options={'HIDDEN', 'SKIP_SAVE'}") == 2
    assert 'FloatProperty' not in source
