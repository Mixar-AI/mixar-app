# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""An asynchronous voice result only focuses its originating live editor."""
from contextlib import nullcontext
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest


@pytest.fixture
def focus(monkeypatch):
    monkeypatch.setitem(sys.modules, 'mixar.modules.space_mixie_chat.core.voice_input.composer',
                        NS(Draft=object))
    path = Path(__file__).resolve().parents[1] / 'src/scripts/mixar/modules/space_mixie_chat/core/voice.py'
    spec = importlib.util.spec_from_file_location(
        'mixar.modules.space_mixie_chat.core._voice_focus_tests', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._focus_composer


@pytest.mark.parametrize('change', ['none', 'window_closed', 'area_replaced', 'editor_changed', 'scene_changed'])
def test_focus_is_bound_to_origin(focus, monkeypatch, change):
    scene = object()
    area = NS(as_pointer=lambda: 20, type='AGENT_BUBBLE')
    window = NS(as_pointer=lambda: 10, scene=scene, screen=NS(areas=[area]))
    session = NS(window=10, area=20, scene=scene)
    windows = [window]
    if change == 'window_closed':
        windows = []
    elif change == 'area_replaced':
        area.as_pointer = lambda: 21
    elif change == 'editor_changed':
        area.type = 'VIEW_3D'
    elif change == 'scene_changed':
        window.scene = object()
    activate = Mock()
    override = Mock(side_effect=lambda **_: nullcontext())
    monkeypatch.setitem(sys.modules, 'bpy', NS(
        context=NS(window_manager=NS(windows=windows), temp_override=override),
        ops=NS(mixie_chat=NS(focus_composer=activate))))
    focus(session)
    if change == 'none':
        override.assert_called_once_with(window=window, area=area)
        activate.assert_called_once_with()
    else:
        override.assert_not_called()
        activate.assert_not_called()
