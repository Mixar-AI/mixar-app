# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Capture lifecycle runs independently of provider readiness."""
import importlib.util
from pathlib import Path
import queue
import sys
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest


@pytest.fixture
def rig(monkeypatch):
    monkeypatch.setitem(sys.modules, 'mixar.modules.space_mixie_chat.core.voice_input.composer', NS(Draft=object))
    path = Path(__file__).resolve().parents[1] / 'src/scripts/mixar/modules/space_mixie_chat/core/voice.py'
    spec = importlib.util.spec_from_file_location('mixar.modules.space_mixie_chat.core._capture_tests', path)
    voice = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(voice)
    scene = NS(mixie_chat_input='Keep draft')
    context = NS(scene=scene, window_manager=NS(windows=[NS(as_pointer=lambda: 1)]))
    monkeypatch.setitem(sys.modules, 'bpy', NS(context=context))
    monkeypatch.setitem(sys.modules, 'mixar.modules.auth.core.auth', NS(get_access_token=lambda: 'valid'))
    capture = object()
    aud = NS(_mixar_capture_permission=Mock(return_value=1),
             _mixar_capture_open=Mock(return_value=capture),
             _mixar_capture_read=Mock(return_value=b'\x01\x02'),
             _mixar_capture_stop=Mock(return_value=b'\x03\x04'))
    monkeypatch.setitem(sys.modules, 'aud', aud)
    now = [1.0]
    voice.time = NS(monotonic=lambda: now[0])
    voice._status = Mock()
    voice._toast = Mock()
    voice._identity = lambda _: 'chat'
    voice._attachments = lambda _: ()
    transport = NS(timings={}, events=queue.Queue(), start=Mock(), feed=Mock(), stop=Mock(), cancel=Mock())
    session = NS(scene=scene, window=1, began=1, auth_checked=1, capture=None,
                 state='Permission', ready=False, recording_at=None, max_seconds=180,
                 deadline=241, attachments=(), draft=NS(base='Keep draft', identity='chat'),
                 transport=transport)
    voice._session = session
    return voice, session, aud, now


def test_capture_and_listening_start_without_ready(rig):
    voice, session, aud, _ = rig
    voice._begin_capture(session)
    assert session.capture is aud._mixar_capture_open.return_value
    voice._status.assert_called_with('Listening')
    session.transport.start.assert_called_once()
    assert not session.ready
    voice._tick()
    session.transport.feed.assert_called_with(b'\x01\x02')


def test_stop_before_ready_does_not_reopen_capture_or_reset_finishing(rig):
    voice, session, aud, _ = rig
    voice._begin_capture(session)
    voice.stop()
    session.transport.feed.assert_called_with(b'\x03\x04')
    session.transport.stop.assert_called_once()
    session.transport.events.put({'type': 'ready', 'max_duration_seconds': 180})
    voice._tick()
    assert session.state == 'Finishing' and session.capture is None and session.ready
    aud._mixar_capture_open.assert_called_once()


def test_pending_permission_neither_captures_nor_connects(rig):
    voice, session, aud, _ = rig
    aud._mixar_capture_permission.return_value = 0
    voice._begin_capture(session)
    aud._mixar_capture_open.assert_not_called()
    session.transport.start.assert_not_called()
    voice._status.assert_called_with('Allow microphone')


def test_connection_timeout_stops_capture_and_preserves_draft(rig):
    voice, session, aud, now = rig
    voice._begin_capture(session)
    now[0] = 22
    assert voice._tick() is None
    assert session.scene.mixie_chat_input == 'Keep draft'
    assert voice._session is None
    aud._mixar_capture_stop.assert_called_once()
    session.transport.cancel.assert_called_once()
    assert 'connect' in voice._toast.call_args.args[1]
