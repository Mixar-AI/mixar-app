# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

import importlib
from types import SimpleNamespace as NS
from unittest.mock import patch
from uuid import UUID
from pathlib import Path
import runpy
import pytest

from mixar.modules.common.analytics import journey_events as journey


def context(prompt='private prompt /Users/person/secret.png'):
    return NS(area=NS(type='AGENT_BUBBLE'), scene=NS(
        mixie_moodboard_sidebar=NS(tab_imagegen=NS(prompt=prompt))))


def test_attempt_and_result_share_only_structure_and_correlation():
    with patch.object(journey, 'capture') as emit:
        attempt = journey.generation_attempt(context(), 'MixieMoodboardTabImageGenProps')
        journey.generation_dispatch(context(), attempt, 'cancelled')
    first, last = emit.call_args_list
    assert first.args[0] == 'generation.attempted'
    assert last.args[0] == 'generation.dispatch_result'
    assert first.args[1] == attempt
    assert last.args[1] == {**attempt, 'outcome': 'cancelled'}
    assert set(attempt) == {'attempt_id', 'capability', 'surface', 'has_prompt', 'prompt_length_bucket'}
    assert attempt['capability'] == 'image_gen'
    assert attempt['surface'] == 'agent_island'
    assert attempt['has_prompt'] is True
    UUID(attempt['attempt_id'])
    assert 'private' not in str(attempt)


def test_every_dispatch_owner_has_a_safe_capability():
    source = Path(__file__).resolve().parents[1] / 'src/scripts/mixar/modules/moodboard/core/prompt_submit.py'
    assert set(journey.OWNERS) == set(runpy.run_path(str(source))['PROMPT_TAB_DISPATCH'])


def test_unknown_owner_and_error_text_never_leak():
    with patch.object(journey, 'capture') as emit:
        attempt = journey.generation_attempt(context(), '/private/customer/file')
        journey.generation_dispatch(context(), attempt, '/private/error/trace')
    assert emit.call_count == 1
    assert attempt['capability'] == 'unknown'
    assert '/private' not in str(attempt)


def test_navigation_seeds_deduplicates_and_does_not_reset_dwell():
    journey.reset_navigation()
    with patch.object(journey, 'capture') as emit, patch.object(journey, 'is_enabled', return_value=True), \
            patch.object(journey.time, 'monotonic', side_effect=[10, 15, 20]):
        journey.tab_changed(context(), 'AGENT')
        journey.tab_changed(context(), 'AGENT')
        journey.tab_changed(context(), 'IMAGE')
    emit.assert_called_once()
    assert emit.call_args.args[1] == {
        'tab': 'IMAGE', 'previous_tab': 'AGENT', 'previous_duration_seconds': 10,
        'origin_surface': 'agent_island',
    }


def test_opt_out_navigation_is_seeded_without_emission():
    journey.reset_navigation()
    with patch.object(journey, 'capture') as emit, patch.object(journey, 'is_enabled', return_value=False):
        journey.tab_changed(context(), 'AGENT')
        journey.tab_changed(context(), 'IMAGE')
    emit.assert_not_called()
    assert journey._previous_tab == 'IMAGE'


def test_semantic_actions_distinguish_modal_start_from_completion():
    with patch.object(journey, 'capture') as emit:
        journey.operator_outcome('mixar.generations_add_asset', {'FINISHED'}, context())
        journey.operator_outcome('mixar.generations_add_asset', {'CANCELLED'}, context())
        journey.operator_outcome('mixar.generations_add_library', {'RUNNING_MODAL'}, context())
        journey.operator_outcome('unknown.user_content', {'FINISHED'}, context())
    assert [call.args[1]['outcome'] for call in emit.call_args_list] == [
        'finished', 'cancelled', 'modal_started']
    assert set(emit.call_args.args[1]) == {'feature', 'action', 'outcome', 'surface'}


def test_delivery_discards_batch_after_consent_revoked():
    capture = importlib.import_module('mixar.modules.common.analytics.capture')
    with patch.object(capture, 'is_enabled', return_value=False), patch.object(capture, '_post_batch') as post:
        capture._send([{'event': 'ui.action'}])
    post.assert_not_called()


def test_app_session_is_stable_across_conversations():
    capture = importlib.import_module('mixar.modules.common.analytics.capture')
    with patch.object(capture, 'get_config', return_value={}), \
            patch.object(capture, 'get_environment', return_value='Dev'), \
            patch.object(capture, 'get_ui_mode', return_value='ai'):
        a = capture._common_properties(NS(scene=NS(mixie_session_id='conversation-a')))
        b = capture._common_properties(NS(scene=NS(mixie_session_id='conversation-b')))
    assert a['session_id'] != b['session_id']
    assert a['app_session_id'] == b['app_session_id']
    UUID(a['app_session_id'])
    assert a['telemetry_schema_version'] == 2


def test_analytics_failure_cannot_break_actions():
    with patch.object(journey, 'capture', side_effect=RuntimeError('offline')):
        assert journey.generation_attempt(context(), 'MixieMoodboardTabImageGenProps') == {}
        journey.generation_dispatch(context(), {}, 'dispatched')
        journey.operator_outcome('mixar.generations_add_asset', {'FINISHED'}, context())


def test_operator_exception_is_counted_without_swallowing_or_recording_text():
    capture = importlib.import_module('mixar.modules.common.analytics.capture')
    def execute(self, context):
        raise RuntimeError('/private/customer/file')
    wrapped = capture._operator_wrapper(execute, 'mixar.generations_add_asset', with_event=False)
    with patch.object(journey, 'capture') as emit, patch.object(capture, 'capture'), \
            pytest.raises(RuntimeError, match='/private/customer/file'):
        wrapped(None, context())
    assert emit.call_args.args[1]['outcome'] == 'error'
    assert '/private' not in str(emit.call_args)
