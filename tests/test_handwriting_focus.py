# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Returning to typing waits for layout and never follows a replaced editor."""
from contextlib import nullcontext
from types import SimpleNamespace as NS
from unittest.mock import Mock
import sys

import pytest

from mixar.modules.space_mixie_chat.core import composer_focus


@pytest.mark.parametrize('change', ['none', 'window', 'area', 'scene', 'canvas', 'tab', 'expired'])
def test_focus_is_bounded_and_stays_with_its_origin(monkeypatch, change):
    scene = NS(as_pointer=lambda: 30)
    area = NS(as_pointer=lambda: 20, type='AGENT_BUBBLE')
    window = NS(as_pointer=lambda: 10, scene=scene, screen=NS(areas=[area]))
    wm = NS(windows=[window], mixie_chat_ink_visible=False, mixar_bubble_tab='AGENT')
    context = NS(window=window, area=area, scene=scene, window_manager=wm,
                 temp_override=lambda **kwargs: nullcontext())
    activate = Mock(side_effect=[{'CANCELLED'}, {'FINISHED'}])
    register = Mock()
    now = [10.0]
    monkeypatch.setattr(composer_focus.time, 'monotonic', lambda: now[0])
    monkeypatch.setitem(sys.modules, 'bpy', NS(context=context,
        app=NS(timers=NS(register=register)), ops=NS(mixie_chat=NS(focus_composer=activate))))
    composer_focus.after_redraw(context)
    tick = register.call_args.args[0]
    assert register.call_args.kwargs['first_interval'] == .15
    if change == 'window': wm.windows = []
    if change == 'area': area.type = 'VIEW_3D'
    if change == 'scene': window.scene = NS(as_pointer=lambda: 31)
    if change == 'canvas': wm.mixie_chat_ink_visible = True
    if change == 'tab': wm.mixar_bubble_tab = 'QUEUE'
    if change == 'expired': now[0] = 12.0
    if change == 'none':
        assert tick() == .05  # Composer not rebuilt yet.
        assert tick() is None
        assert activate.call_count == 2
    else:
        assert tick() is None
        activate.assert_not_called()
