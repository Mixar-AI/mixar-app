# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Essential UI signals must stay sparse, consent-gated and content-free."""

import importlib
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

from mixar.modules.common.analytics import essential_events as essential
from mixar.modules.common.analytics.constants import IGNORED_OPERATORS

cap = importlib.import_module('mixar.modules.common.analytics.capture')


def context(uid=1, directing=True):
    return NS(area=NS(type='VIEW_3D'), scene=NS(
        session_uid=uid, name='/private/customer/project',
        mixar_director=NS(is_directing=directing)))


@pytest.fixture(autouse=True)
def isolated_tracking():
    essential.reset_cinema_sessions()
    essential._drawer_open_reported = False
    with patch.object(essential, 'is_enabled', return_value=True), \
            patch.object(essential, '_has_auth_token', return_value=True):
        yield
    essential.reset_cinema_sessions()
    essential._drawer_open_reported = False


def test_cinema_duration_enriches_one_exit_without_adding_events():
    ctx = context()
    with patch.object(essential.time, 'monotonic', side_effect=[10, 15, 22.34]), \
            patch.object(cap, 'capture') as emit:
        cap._capture_operator_result('mixar.director_enter', {'FINISHED'}, ctx)
        cap._capture_operator_result('mixar.director_new_shot', {'FINISHED'}, ctx)
        ctx.scene.mixar_director.is_directing = False
        cap._capture_operator_result('mixar.director_finish', {'FINISHED'}, ctx)
    assert emit.call_count == 3
    assert emit.call_args.args == ('product.operator', {
        'operator': 'mixar.director_finish', 'success': True, 'duration_seconds': 12.3})
    assert '/private' not in str([call.args for call in emit.call_args_list])


def test_scene_clocks_are_independent_and_failed_exits_keep_the_clock():
    a, b = context(1), context(2)
    with patch.object(essential.time, 'monotonic', side_effect=[10, 20, 40, 50]):
        essential.cinema_operator_properties('mixar.director_enter', {'FINISHED'}, a)
        essential.cinema_operator_properties('mixar.director_start', {'FINISHED'}, b)
        assert essential.cinema_operator_properties('mixar.director_finish', {'CANCELLED'}, a) == {}
        a.scene.mixar_director.is_directing = False
        b.scene.mixar_director.is_directing = False
        assert essential.cinema_operator_properties('mixar.director_finish', {'FINISHED'}, a) == {'duration_seconds': 30}
        assert essential.cinema_operator_properties('mixar.director_lock', {'FINISHED'}, b) == {'duration_seconds': 30}
        assert essential.cinema_operator_properties('mixar.director_finish', {'FINISHED'}, a) == {}


def test_unobserved_or_reset_cinema_entry_has_no_invented_duration():
    ctx = context()
    essential.cinema_operator_properties('mixar.director_enter', {'CANCELLED'}, ctx)
    assert essential._cinema_started == {}
    essential.cinema_operator_properties('mixar.director_enter', {'FINISHED'}, ctx)
    essential.reset_cinema_sessions()
    ctx.scene.mixar_director.is_directing = False
    assert essential.cinema_operator_properties('mixar.director_finish', {'FINISHED'}, ctx) == {}


@pytest.mark.parametrize('gate', ['is_enabled', '_has_auth_token'])
def test_drawer_discovery_only_counts_first_eligible_open(gate):
    with patch.object(essential, 'capture') as emit:
        with patch.object(essential, gate, return_value=False):
            essential.capture_scene_drawer_open(context())
        emit.assert_not_called()
        essential.capture_scene_drawer_open(context())
        essential.capture_scene_drawer_open(context())
    emit.assert_called_once()
    assert emit.call_args.args == ('ui.action', {
        'feature': 'scene_drawer', 'action': 'open',
        'outcome': 'finished', 'surface': 'viewport'})
    assert 'mixie_chat.track_scene_drawer_open' in IGNORED_OPERATORS


def test_analytics_failure_does_not_break_or_consume_discovery():
    with patch.object(essential, 'capture', side_effect=RuntimeError('offline')):
        essential.capture_scene_drawer_open(context())
    assert essential._drawer_open_reported is False


def test_scribble_signal_is_a_boolean_on_one_existing_send_event():
    ctx = context()
    ctx.scene.mixie_chat_mode = 'AGENT'
    payload = {'marks': [{'label': '/private/customer/drawing', 'points': [1, 2, 3]}]}
    with patch.object(essential, 'capture') as emit:
        essential.capture_agent_message(ctx, [], False, False, payload)
        essential.capture_agent_message(ctx, [], False, False, None)
    assert emit.call_count == 2
    assert [call.args[0] for call in emit.call_args_list] == ['agent.message_sent'] * 2
    assert [call.args[1]['has_scribble'] for call in emit.call_args_list] == [True, False]
    assert '/private' not in str([call.args for call in emit.call_args_list])
    assert set(emit.call_args.args[1]) == {
        'mode', 'has_attachments', 'is_modify', 'is_awaiting_input',
        'plan_enabled', 'auto_mode', 'model', 'has_scribble'}
