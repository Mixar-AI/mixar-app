# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Stop on a steerable run says, once, that typing would have steered it.

In production many Stops were followed by a correction or the same prompt
resent: users stopped to redirect a run that a typed message would have
joined (core/composer_send.py:is_interjection).
"""
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def hint(monkeypatch):
    from mixar.modules.common import notifications
    from mixar.modules.space_mixie_chat.core import steer_hint

    store = MagicMock()
    monkeypatch.setattr(notifications, 'get_notification_store', lambda: store)
    monkeypatch.setattr(steer_hint, '_shown', False)
    return steer_hint, store


def test_the_first_user_stop_on_a_steerable_run_shows_the_tip_once(hint):
    steer_hint, store = hint
    assert steer_hint.after_stop(True, 'stop_button') is True
    assert steer_hint.after_stop(True, 'escape_key') is False
    assert store.push.call_count == 1
    kwargs = store.push.call_args.kwargs
    assert kwargs['id'] == steer_hint.TOAST_ID and kwargs['ttl_ms'] == 9000


@pytest.mark.parametrize('steerable, origin', [
    (False, 'stop_button'),           # routing / quick edit: Send is refused there
    (True, 'question_dismissed'),     # Stop dismissed a question, not a run
    (True, 'new_chat'),               # the app cancelled, not the user's Stop
])
def test_no_tip_when_typing_could_not_have_steered(hint, steerable, origin):
    steer_hint, store = hint
    assert steer_hint.after_stop(steerable, origin) is False
    store.push.assert_not_called()


def test_steerable_mirrors_the_interjection_rule():
    from mixar.modules.space_mixie_chat.constants import SessionState
    from mixar.modules.space_mixie_chat.core import steer_hint

    session = MagicMock()
    for state, run_open, expected in [(SessionState.BUSY, True, True),
                                      (SessionState.BUSY, False, False),
                                      (SessionState.IDLE, True, False)]:
        session.get_state.return_value = state
        session.run_open.return_value = run_open
        assert steer_hint.steerable(session, object()) is expected


def test_a_failing_toast_never_breaks_stop(monkeypatch):
    from mixar.modules.common import notifications
    from mixar.modules.space_mixie_chat.core import steer_hint

    def boom():
        raise RuntimeError("no toast host")

    monkeypatch.setattr(notifications, 'get_notification_store', boom)
    monkeypatch.setattr(steer_hint, '_shown', False)
    assert steer_hint.after_stop(True, 'stop_button') is False
    assert steer_hint._shown is False


def test_the_stop_operator_reads_steerability_before_closing_the_run():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "ui/operators/session_ops.py").read_text()
    read_at = src.index("was_steerable = steer_hint.steerable(session, scene)")
    closed_at = src.index('session.set_run(scene, "", False)\n        session.set_connected(scene)')
    assert read_at < closed_at < src.index("steer_hint.after_stop(was_steerable, origin)")
