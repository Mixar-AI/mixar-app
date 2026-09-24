# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Viewport typing edits the draft; Enter submits through the normal composer."""
import ast
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from mixar.modules.scribble_mark.core import prompt_input
from mixar.modules.space_mixie_chat.core import scribble, ui_utils


def event(kind='A', text='', **kwargs):
    return NS(type=kind, unicode=text, value='PRESS', ctrl=False, oskey=False,
              alt=False, shift=False, mouse_x=50, mouse_y=50, **kwargs)


@pytest.fixture
def draft(monkeypatch):
    scene = NS(mixie_chat_input='Build ')
    context = NS(scene=scene, window_manager=NS(clipboard='', mixar_mark_armed=True))
    release, redraw = Mock(), Mock()
    monkeypatch.setattr(scribble, 'release_composer', release)
    monkeypatch.setattr(ui_utils, 'redraw_chat_areas', redraw)
    return context, release, redraw, Mock()


@pytest.mark.parametrize('text', ['a', 'v', 'V', ' ', 'G', '!', 'é', '猫', '🖌', '\u0301'])
def test_literal_input_preserves_existing_draft_and_unicode(draft, text):
    context, release, redraw, report = draft
    assert prompt_input.handle(context, event(text=text), report)
    assert context.scene.mixie_chat_input == 'Build ' + text
    release.assert_called_once()
    redraw.assert_called_once()
    report.assert_not_called()


@pytest.mark.parametrize('modifiers', [{'alt': True}, {'alt': True, 'ctrl': True}])
def test_option_and_altgr_text_is_kept(draft, modifiers):
    context, _, _, report = draft
    key = event(text='€')
    vars(key).update(modifiers)
    assert prompt_input.handle(context, key, report)
    assert context.scene.mixie_chat_input == 'Build €'


def test_backspace_and_shift_enter_edit_text_without_a_submit_marker(draft):
    context, _, _, report = draft
    context.scene.mixie_chat_input = 'Paint 🖌'
    assert prompt_input.handle(context, event('BACK_SPACE'), report)
    assert context.scene.mixie_chat_input == 'Paint '
    key = event('RET')
    key.shift = True
    assert prompt_input.handle(context, key, report)
    assert context.scene.mixie_chat_input == 'Paint \n'
    context.scene.mixie_chat_input = ''
    assert prompt_input.handle(context, event('BACK_SPACE'), report)
    assert context.scene.mixie_chat_input == ''


@pytest.mark.parametrize('kind', ['RET', 'NUMPAD_ENTER'])
@pytest.mark.parametrize('text', ['', 'Build ', 'x' * prompt_input.CHAT_INPUT_MAXLEN])
def test_enter_sends_after_releasing_edit_without_mutating_draft(draft, monkeypatch, kind, text):
    from mixar.modules.space_mixie_chat.ui.properties import chat_props
    context, release, _, report = draft
    context.scene.mixie_chat_input = text
    def send():
        release.assert_called_once()
        assert context.scene.mixie_chat_input == text
    submit = Mock(side_effect=send)
    monkeypatch.setattr(chat_props, '_execute_send_message', submit)
    assert prompt_input.handle(context, event(kind), report)
    submit.assert_called_once()
    report.assert_not_called()


@pytest.mark.parametrize('changes', [{'is_repeat': True}, {'value': 'RELEASE'}])
def test_held_or_released_enter_does_not_send_again(draft, monkeypatch, changes):
    from mixar.modules.space_mixie_chat.ui.properties import chat_props
    context, release, _, report = draft
    submit = Mock()
    monkeypatch.setattr(chat_props, '_execute_send_message', submit)
    key = event('RET')
    vars(key).update(changes)
    prompt_input.handle(context, key, report)
    submit.assert_not_called()
    release.assert_not_called()


def test_enter_send_errors_are_visible_and_preserve_the_draft(draft, monkeypatch):
    from mixar.modules.space_mixie_chat.core import composer_send
    from mixar.modules.space_mixie_chat.ui.properties import chat_props
    context, _, _, report = draft
    monkeypatch.setattr(composer_send, 'can_send', lambda scene: (True, ''))
    monkeypatch.setattr(chat_props.bpy.ops.mixie_chat, 'send_message',
                        Mock(side_effect=RuntimeError('Error: Not connected to server\n')))
    refused = Mock()
    monkeypatch.setattr(chat_props, '_report_send_refused', refused)
    assert prompt_input.handle(context, event('RET'), report)
    refused.assert_called_once_with('Not connected to server')
    assert context.scene.mixie_chat_input == 'Build '
    assert context.window_manager.mixar_mark_armed


@pytest.mark.parametrize('modifier', ['ctrl', 'oskey'])
def test_paste_normalizes_line_endings_and_cannot_send(draft, modifier):
    context, _, _, report = draft
    context.window_manager.clipboard = 'blue\r\nand green\r\x1f'
    key = event('V', 'v')
    setattr(key, modifier, True)
    assert prompt_input.handle(context, key, report)
    assert context.scene.mixie_chat_input == 'Build blue\nand green\n'


@pytest.mark.parametrize('kind,text,changes', [
    ('A', 'a', {'value': 'RELEASE'}), ('Z', 'z', {'ctrl': True}),
    ('Z', 'z', {'oskey': True}), ('C', 'c', {'ctrl': True}),
    ('TAB', '\t', {}), ('ESC', '\x1b', {}), ('DEL', '\x7f', {}),
    ('A', '\x1f', {}), ('MOUSEMOVE', '', {}),
])
def test_non_text_events_do_not_mutate_the_draft(draft, kind, text, changes):
    context, release, redraw, report = draft
    key = event(kind, text)
    vars(key).update(changes)
    assert not prompt_input.handle(context, key, report)
    assert context.scene.mixie_chat_input == 'Build '
    release.assert_not_called()
    redraw.assert_not_called()


def test_release_happens_before_reading_the_live_draft(draft):
    context, release, _, report = draft
    release.side_effect = lambda: setattr(context.scene, 'mixie_chat_input', 'Latest ')
    prompt_input.handle(context, event(text='x'), report)
    assert context.scene.mixie_chat_input == 'Latest x'


def test_capacity_warns_and_keeps_the_existing_text(draft, monkeypatch):
    context, _, _, report = draft
    monkeypatch.setattr(prompt_input, 'CHAT_INPUT_MAXLEN', 6)
    prompt_input.handle(context, event(text='x'), report)
    assert context.scene.mixie_chat_input == 'Build '
    report.assert_called_once()


def test_ctrl_space_is_not_a_voice_shortcut_and_types_nothing(draft, monkeypatch):
    """Sketch talks on held Option/Alt, like the chat (core/push_to_talk.py)."""
    import bpy
    context, release, _, report = draft
    toggle = Mock()
    monkeypatch.setattr(bpy.ops.mixie_chat, 'voice_toggle', toggle, raising=False)
    key = event('SPACE', ' ')
    key.ctrl = True
    assert not prompt_input.handle(context, key, report)
    toggle.assert_not_called()
    assert context.scene.mixie_chat_input == 'Build '
    release.assert_not_called()


@pytest.mark.parametrize('inside', [True, False])
def test_real_modal_routes_only_viewport_typing_and_keeps_ink(draft, inside):
    context, _, _, report = draft
    path = Path(__file__).resolve().parents[2] / (
        'src/scripts/mixar/modules/scribble_mark/ui/operators/mark_draw_ops.py')
    node = next(n for n in ast.walk(ast.parse(path.read_text()))
                if isinstance(n, ast.FunctionDef) and n.name == 'modal')
    namespace = {'overlay': NS(point_in_region=lambda *args: inside),
                 'prompt_input': prompt_input}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
    operator = NS(_region=lambda c: NS(x=0, y=0), _ink=NS(drawing=False),
                  report=report, _undo_last=Mock())
    outcome = namespace['modal'](operator, context, event(text='x'))
    assert outcome == ({'RUNNING_MODAL'} if inside else {'PASS_THROUGH'})
    assert context.scene.mixie_chat_input == ('Build x' if inside else 'Build ')
    assert context.window_manager.mixar_mark_armed
    key = event('Z')
    key.ctrl = True
    namespace['modal'](operator, context, key)
    assert operator._undo_last.call_count == int(inside)
