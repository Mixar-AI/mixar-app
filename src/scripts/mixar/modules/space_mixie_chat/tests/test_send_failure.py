# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""A refused or undelivered message is ONE agent message in plain language.

Never a delivery label on the user's bubble, never the raw exception text,
a status code or a stack trace, and never silence.
"""

from types import SimpleNamespace

import pytest
from _open_run_support import _scene, clean_state  # noqa: F401 — autouse fixture
from mixar.modules.space_mixie_chat.core import queue_processor, send_failure
from mixar.modules.space_mixie_chat.core.send_failure import (
    MSG_FAILED,
    MSG_NOT_DELIVERED,
    MSG_OFFLINE,
    MSG_TOO_LARGE,
    MSG_UPDATE,
    plain_text,
    refusal_text,
)


@pytest.mark.parametrize('result,text', [
    ({'ok': False, 'undelivered': True}, MSG_NOT_DELIVERED),
    # A send the client could not make, by the status its raise carried.
    ({'ok': False, 'unsent': True, 'status_code': 503}, MSG_OFFLINE),
    ({'ok': False, 'unsent': True}, MSG_OFFLINE),  # a dead socket's plain exception
    ({'ok': False, 'unsent': True, 'status_code': 426}, MSG_UPDATE),
    ({'ok': False, 'unsent': True, 'status_code': 413}, MSG_TOO_LARGE),
    ({'ok': False, 'unsent': True, 'status_code': 500}, MSG_FAILED),
    ({'ok': False}, MSG_FAILED),
    ({'ok': False, 'message': ''}, MSG_FAILED),
    # Server sentences written for people pass through as they are.
    ({'ok': False, 'message': 'The previous command is still starting. Please try again.'},
     'The previous command is still starting. Please try again.'),
    ({'ok': False, 'message': 'Please sign in again'}, 'Please sign in again'),
    # Protocol talk, exceptions and transport errors never reach the chat.
    ({'ok': False, 'message': 'Command ID was already used for different content'}, MSG_FAILED),
    ({'ok': False, 'message': 'Invalid agent command fields'}, MSG_FAILED),
    ({'ok': False, 'message': 'Session unavailable'}, MSG_FAILED),
    ({'ok': False, 'message': 'Agent command failed. Please try again.'}, MSG_FAILED),
    ({'ok': False, 'message': "KeyError: 'session_id'"}, MSG_FAILED),
    ({'ok': False, 'message': 'Traceback (most recent call last):\n  File "x.py"'}, MSG_FAILED),
    ({'ok': False, 'message': 'HTTP 500: Internal Server Error'}, MSG_FAILED),
    ({'ok': False, 'message': 'The read operation timed out'}, MSG_OFFLINE),
    ({'ok': False, 'message': 'Connection lost; delivery is uncertain'}, MSG_OFFLINE),
    ({'ok': False, 'message': 'Connection error: [Errno 61] Connection refused'}, MSG_OFFLINE),
])
def test_refusal_text(result, text):
    assert refusal_text(result) == text


def test_an_http_body_message_is_shown_without_its_envelope():
    assert plain_text('HTTP 403: {"detail": {"message": "That request is not allowed."}}') \
        == 'That request is not allowed.'


@pytest.mark.parametrize('raw,text', [
    # A provider SDK's raw error: the provider's own sentence, without the envelope.
    ('Error code: 429 - {"error": {"message": "You exceeded your current quota, please check '
     'your plan and billing details.", "type": "insufficient_quota"}}',
     'You exceeded your current quota, please check your plan and billing details.'),
    ("Error code: 401 - {'error': {'message': 'Incorrect API key provided.', 'code': 'invalid_api_key'}}",
     'Incorrect API key provided.'),
    ('{"error": {"message": "Your credit balance is too low."}}', 'Your credit balance is too low.'),
    # Still filtered: no readable message, or a message that is itself technical.
    ('Error code: 500 - {"error": {}}', MSG_FAILED),
    ("Error code: 400 - {'error': {'message': 'KeyError: messages'}}", MSG_FAILED),
    ('Error code: 429 - {not json', MSG_FAILED),
    ('AuthenticationError: invalid x-api-key', MSG_FAILED),
])
def test_a_providers_raw_error_shows_its_message(raw, text):
    assert plain_text(raw) == text


@pytest.mark.parametrize('text', [MSG_NOT_DELIVERED, MSG_OFFLINE, MSG_FAILED, MSG_UPDATE, MSG_TOO_LARGE])
def test_the_friendly_texts_survive_a_second_pass(text):
    """handle_command_error words the message, then the shared error path
    passes it through plain_text again: that must not change it."""
    assert plain_text(text) == text


# ---------------------------------------------------------------------------
# handle_command_error: the one place a refusal is shown
# ---------------------------------------------------------------------------


@pytest.fixture
def chat(monkeypatch):
    from mixar.modules.space_mixie_chat.core import byok_notice, executor, lane_scene_sweep
    shown = SimpleNamespace(messages=[], ended=[], cards=[])
    monkeypatch.setattr(queue_processor, 'add_agent_message',
                        lambda scene, text: shown.messages.append(text))
    monkeypatch.setattr(queue_processor.EventProcessor, '_redraw_ui', lambda self: None)
    monkeypatch.setattr(executor, 'get_executor', lambda: SimpleNamespace(
        end_agent_turn=lambda sid, checkpoint=False: shown.ended.append(sid)))
    monkeypatch.setattr(lane_scene_sweep, 'schedule_lane_scene_sweep', lambda **kw: None)

    def present_refusal(result, data, scene):
        if byok_notice.byok_error_code(result, data):
            shown.cards.append(result)
            return True
        return False

    monkeypatch.setattr(byok_notice, 'present_refusal', present_refusal)
    shown.processor = queue_processor.EventProcessor()
    return shown


def _loading_scene(state):
    scene = _scene(state=state)
    loader = scene.mixie_chat_messages.add()
    loader.sender, loader.loader_visible = 'AGENT', True
    return scene, loader


@pytest.mark.parametrize('message,text', [
    ("ValueError: bad payload", MSG_FAILED),
    # A deliberate drop on the stream path; a refusal is never silent.
    ('The read operation timed out', MSG_OFFLINE),
])
def test_a_refused_send_is_one_plain_message(chat, message, text):
    scene, _ = _loading_scene('IDLE')
    chat.processor.handle_command_error({'ok': False, 'message': message}, scene)
    assert chat.messages == [text]
    assert scene.mixie_chat_state == 'IDLE'


def test_an_undelivered_send_says_so_once(chat):
    scene, _ = _loading_scene('IDLE')
    chat.processor.handle_command_error({'ok': False, 'undelivered': True}, scene)
    assert chat.messages == [MSG_NOT_DELIVERED]


def test_a_refused_interjection_is_shown_and_its_turn_keeps_running(chat):
    scene, loader = _loading_scene('BUSY')
    chat.processor.handle_command_error(
        {'ok': False, 'message': 'Invalid agent command fields'}, scene, interjection=True)
    assert chat.messages == [MSG_FAILED]
    assert scene.mixie_chat_state == 'BUSY' and loader.loader_visible is True
    assert chat.ended == []  # the running turn's undo bracket is untouched


def test_a_byok_refused_interjection_shows_the_card_and_keeps_the_turn(chat):
    scene, loader = _loading_scene('BUSY')
    result = {'ok': False, 'status_code': 409, 'code': 'byok_key_required', 'provider': 'openai'}
    chat.processor.handle_command_error(result, scene, interjection=True)
    assert chat.cards == [result] and chat.messages == []
    assert scene.mixie_chat_state == 'BUSY' and loader.loader_visible is True and chat.ended == []


def test_a_byok_refused_send_shows_the_card_and_ends_the_turn(chat):
    scene, loader = _loading_scene('BUSY')
    result = {'ok': False, 'status_code': 409, 'code': 'byok_key_required', 'provider': 'openai'}
    chat.processor.handle_command_error(result, scene)
    assert chat.cards == [result] and chat.messages == []
    assert scene.mixie_chat_state == 'IDLE' and loader.loader_visible is False


def test_the_strings_are_marked_for_translation():
    src = send_failure.__file__
    text = open(src, encoding='utf-8').read()
    for msgid in (MSG_NOT_DELIVERED, MSG_OFFLINE, MSG_FAILED):
        assert f'n_("{msgid}")' in text
