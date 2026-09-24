# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Send snapshots live ink in its own view; a sketch needs no typed sentence."""

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mixar.modules.scribble_mark.core import chat_bridge, freeze_session, pending
from mixar.modules.scribble_mark.core.stroke_capture import StrokeBuffer


@pytest.fixture(autouse=True)
def clear_pending():
    pending.clear()
    yield
    pending.clear()


def setup_live(monkeypatch, *, matches=True, same_scene=True):
    scene = object()
    window = SimpleNamespace(scene=scene if same_scene else object())
    area, region = object(), object()
    override = Mock(return_value=nullcontext())
    context = SimpleNamespace(scene=scene, temp_override=override)
    ink = StrokeBuffer(8, 128)
    ink.begin((10, 20))
    ink.extend((40, 50), 1)
    operator = SimpleNamespace(
        _ink=ink,
        _area_ptr=1, _region_ptr=2,
        _session=SimpleNamespace(matches=lambda r: matches),
        _commit_pending=Mock(),
    )
    monkeypatch.setattr(freeze_session, 'resolve', lambda *args: (window, area, region))
    pending.bind(operator)
    return context, operator, override, (window, area, region)


def test_send_flushes_before_idle_in_the_viewport_window(monkeypatch):
    context, operator, override, (window, area, region) = setup_live(monkeypatch)
    assert pending.flush(context)
    assert not operator._ink.drawing
    operator._commit_pending.assert_called_once_with(context)
    override.assert_called_once_with(window=window, area=area, region=region)


@pytest.mark.parametrize('kwargs', [{'matches': False}, {'same_scene': False}])
def test_never_reprojects_ink_through_a_different_frame_or_scene(monkeypatch, kwargs):
    context, operator, override, _ = setup_live(monkeypatch, **kwargs)
    assert not pending.flush(context)
    operator._commit_pending.assert_not_called()
    override.assert_not_called()


def test_file_load_clears_the_pending_operator(monkeypatch):
    context, operator, _, _ = setup_live(monkeypatch)
    pending.clear()
    assert not pending.flush(context)
    operator._commit_pending.assert_not_called()


@pytest.mark.parametrize(('payload', 'expected'), [
    (None, ''),
    ({'marks': [{}], 'intent': 'sketch', 'sketch': {'strokes': [{}]}},
     'Build what I drew in this sketch.'),
    ({'marks': [{}], 'intent': 'point'},
     'Use these marks as context; ask me what to change if it is unclear.'),
])
def test_ink_only_message_honors_the_reading_without_inventing_an_edit(monkeypatch, payload, expected):
    monkeypatch.setattr(chat_bridge.mark_store, 'build_context', lambda *args, **kwargs: payload)
    monkeypatch.setattr(chat_bridge.mark_store, 'intent_override', lambda wm: 'AUTO')
    assert chat_bridge.default_message(object(), object()) == expected


def test_flush_precedes_empty_check_but_attachments_follow_connection_preflight():
    source = (Path(__file__).resolve().parents[2] /
              'src/scripts/mixar/modules/space_mixie_chat/ui/operators/chat_ops.py').read_text()
    assert source.index('chat_bridge.flush_for_send') < source.index('Cannot send empty message')
    assert source.index('WebSocket not ready') < source.index('chat_bridge.prepare_for_send')


def test_send_with_no_new_strokes_does_not_commit_again(monkeypatch):
    context, operator, override, _ = setup_live(monkeypatch)
    operator._ink.clear()
    assert not pending.flush(context)
    operator._commit_pending.assert_not_called()
    override.assert_not_called()
