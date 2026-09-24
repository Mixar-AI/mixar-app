# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Sketch push-to-talk: the chat composer's hold-left-Option/Alt gesture."""
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from mixar.modules.scribble_mark.core import push_to_talk as P
from mixar.modules.space_mixie_chat.core import voice

ROOT = Path(__file__).resolve().parents[2]


class Clock:
    now = 100.0

    def __call__(self):
        return self.now


def ev(kind, value='PRESS', **mods):
    base = dict(ctrl=False, oskey=False, shift=False, alt=kind == 'LEFT_ALT', is_repeat=False)
    base.update(mods)
    return NS(type=kind, value=value, **base)


@pytest.fixture
def talk(monkeypatch):
    calls = []
    state = {'owned': False}

    def begin(context):
        calls.append('begin')
        state['owned'] = True
        return 'started'

    def end(discard=False):
        calls.append('discard' if discard else 'end')
        state['owned'] = False

    monkeypatch.setattr(P, 'VOICE_INPUT_SUPPORTED', True)
    monkeypatch.setattr(voice, 'push_to_talk_begin', begin)
    monkeypatch.setattr(voice, 'push_to_talk_end', end)
    monkeypatch.setattr(voice, 'is_listening', lambda wm=None: state['owned'])
    clock = Clock()
    return P.HoldToTalk(clock), clock, calls


def hold(h, clock):
    assert h.handle(None, ev('LEFT_ALT'), True)
    clock.now += P.HOLD_SECONDS + 0.01
    assert not h.handle(None, ev('TIMER', 'NOTHING'), True)


def test_same_key_and_delay_as_the_chat_composer():
    native = (ROOT / 'src/source/blender/editors/interface/interface_text_dictation.cc').read_text()
    assert 'HOLD_SECONDS = 0.30' in native and P.HOLD_SECONDS == 0.30
    assert 'EVT_LEFTALTKEY' in native and P.TRIGGER == 'LEFT_ALT'


def test_hold_starts_and_release_keeps_the_words(talk):
    h, clock, calls = talk
    hold(h, clock)
    assert calls == ['begin'] and h.started
    assert h.handle(None, ev('LEFT_ALT', 'RELEASE'), False)  # release off-viewport still ends
    assert calls == ['begin', 'end'] and not h.started


def test_tap_is_not_talk(talk):
    h, clock, calls = talk
    assert h.handle(None, ev('LEFT_ALT'), True)
    clock.now += P.HOLD_SECONDS / 2
    h.handle(None, ev('TIMER', 'NOTHING'), True)
    assert h.handle(None, ev('LEFT_ALT', 'RELEASE'), True)
    clock.now += 1
    h.handle(None, ev('TIMER', 'NOTHING'), True)
    assert calls == []


def test_option_character_chord_cancels_the_wait_and_keeps_the_key(talk):
    h, clock, calls = talk
    h.handle(None, ev('LEFT_ALT'), True)
    assert not h.handle(None, ev('E', alt=True), True)  # routed on as typing
    clock.now += 1
    h.handle(None, ev('TIMER', 'NOTHING'), True)
    assert calls == []


def test_esc_drops_the_words_without_leaving_sketch(talk):
    h, clock, calls = talk
    hold(h, clock)
    assert h.handle(None, ev('ESC'), True)
    assert calls == ['begin', 'discard']


def test_drawing_while_talking_keeps_the_hold(talk):
    h, clock, calls = talk
    hold(h, clock)
    assert not h.handle(None, ev('LEFTMOUSE'), True)
    assert not h.handle(None, ev('MOUSEMOVE', 'NOTHING'), True)
    assert h.started and calls == ['begin']


@pytest.mark.parametrize('case', ['outside', 'modified', 'repeat', 'listening', 'unsupported'])
def test_hold_only_starts_bare_over_the_viewport(talk, monkeypatch, case):
    h, clock, calls = talk
    inside = case != 'outside'
    mods = {'modified': {'ctrl': True}, 'repeat': {'is_repeat': True}}.get(case, {})
    if case == 'listening':
        monkeypatch.setattr(voice, 'is_listening', lambda wm=None: True)
    if case == 'unsupported':
        monkeypatch.setattr(P, 'VOICE_INPUT_SUPPORTED', False)
    assert not h.handle(None, ev('LEFT_ALT', **mods), inside)
    clock.now += 1
    h.handle(None, ev('TIMER', 'NOTHING'), inside)
    assert calls == []


def test_focus_loss_discards_an_owned_hold(talk):
    h, clock, calls = talk
    hold(h, clock)
    h.handle(None, ev('WINDOW_DEACTIVATE', 'NOTHING'), True)
    assert calls == ['begin', 'discard'] and not h.started


def test_modal_routes_the_hold_before_the_viewport_test():
    source = (ROOT / 'src/scripts/mixar/modules/scribble_mark/ui/operators/'
              'mark_draw_ops.py').read_text()
    talk = source.index('talk.handle(')
    assert talk < source.index('if event.type == "TIMER":') < source.index(
        'inside = overlay.point_in_region(region, event.mouse_x, event.mouse_y)')


def test_voice_status_changes_repaint_the_frozen_hint(talk):
    _, clock, _ = talk
    redraws = []
    h = P.HoldToTalk(clock, on_status=lambda: redraws.append(1))
    wm = NS(mixie_chat_voice_status='')
    context = NS(window_manager=wm)
    for status, expected in (('', 0), ('Listening', 1), ('Listening', 1),
                             ('Finishing', 2), ('', 3)):
        wm.mixie_chat_voice_status = status
        h.handle(context, ev('TIMER', 'NOTHING'), True)
        assert len(redraws) == expected
