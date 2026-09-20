# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""A freeze exposes its whole input surface and restores the drawer on exit."""
from contextlib import nullcontext
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from mixar.modules.scribble_mark.core import drawer_guard, freeze_session


def setup(monkeypatch, *, amount=1.0, target=1, workspace="Zen Mode"):
    wm = NS(mixar_moodboard_drawer_amount=amount, mixar_moodboard_drawer_target=target,
            mixar_moodboard_drawer_width=480.0)
    window = NS(workspace=NS(name=workspace))
    area = NS(as_pointer=lambda: 11, tag_redraw=Mock())
    region = NS(as_pointer=lambda: 12)
    context = NS(window_manager=wm, temp_override=Mock(return_value=nullcontext()))
    def set_drawer(**kwargs):
        wm.mixar_moodboard_drawer_amount = kwargs['amount']
        wm.mixar_moodboard_drawer_target = int(kwargs['target'])
        return {'FINISHED'}
    setter = Mock(side_effect=set_drawer)
    monkeypatch.setattr(drawer_guard.bpy.ops.view3d, 'moodboard_drawer_set', setter)
    monkeypatch.setattr(freeze_session, 'resolve', lambda *a: (window, area, region))
    return context, window, area, region, setter


@pytest.mark.parametrize(('amount', 'target'), [(1.0, 1), (.4, 1), (.4, 0)])
def test_open_or_sliding_drawer_restores_original_intent_after_resize(monkeypatch, amount, target):
    context, window, area, region, setter = setup(monkeypatch, amount=amount, target=target)
    guard = drawer_guard.DrawerGuard()
    assert guard.suspend(context, window, area, region)
    assert context.window_manager.mixar_moodboard_drawer_amount == 0
    assert context.window_manager.mixar_moodboard_drawer_target == 0
    # Refreezing must not overwrite the saved open state with the temporary 0.
    assert guard.suspend(context, window, area, region)
    guard.restore(context)
    guard.restore(context)
    assert setter.call_count == 2
    assert context.window_manager.mixar_moodboard_drawer_amount == amount
    assert context.window_manager.mixar_moodboard_drawer_target == target
    assert context.window_manager.mixar_moodboard_drawer_width == 480


@pytest.mark.parametrize('kwargs', [{'amount': 0, 'target': 0}, {'workspace': 'Layout'}])
def test_uncovered_viewport_needs_no_drawer_change(monkeypatch, kwargs):
    context, window, area, region, setter = setup(monkeypatch, **kwargs)
    guard = drawer_guard.DrawerGuard()
    assert guard.suspend(context, window, area, region)
    guard.restore(context)
    setter.assert_not_called()


def test_missing_viewport_still_restores_drawer_preferences(monkeypatch):
    context, window, area, region, setter = setup(monkeypatch)
    guard = drawer_guard.DrawerGuard()
    guard.suspend(context, window, area, region)
    monkeypatch.setattr(freeze_session, 'resolve', lambda *a: (None, None, None))
    guard.restore(context)
    assert setter.call_count == 1
    assert context.window_manager.mixar_moodboard_drawer_amount == 1
    assert context.window_manager.mixar_moodboard_drawer_target == 1


def test_cancelled_close_refuses_invisible_ink_and_restores_state(monkeypatch):
    context, window, area, region, setter = setup(monkeypatch)
    setter.side_effect = lambda **kwargs: {'CANCELLED'}
    guard = drawer_guard.DrawerGuard()
    assert not guard.suspend(context, window, area, region)
    assert context.window_manager.mixar_moodboard_drawer_amount == 1
    assert context.window_manager.mixar_moodboard_drawer_target == 1


def test_capture_exception_restores_the_drawer(monkeypatch):
    context, window, area, region, setter = setup(monkeypatch)
    session = freeze_session.FreezeSession()
    monkeypatch.setattr(session, '_take_frame', Mock(side_effect=RuntimeError('capture failed')))
    with pytest.raises(RuntimeError, match='capture failed'):
        session.take(context, window, area, region)
    assert context.window_manager.mixar_moodboard_drawer_amount == 1
    assert context.window_manager.mixar_moodboard_drawer_target == 1


@pytest.mark.parametrize('event_type', ['MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'MIDDLEMOUSE'])
def test_live_pointer_events_cannot_pan_the_underlying_canvas(event_type):
    # Execute the actual modal method without Blender's mocked Operator base.
    import ast
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / (
        'src/scripts/mixar/modules/scribble_mark/ui/operators/mark_draw_ops.py')
    node = next(n for n in ast.walk(ast.parse(path.read_text()))
                if isinstance(n, ast.FunctionDef) and n.name == 'modal')
    namespace = {'overlay': NS(point_in_region=lambda *a: True)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
    region = NS(x=100, y=20)
    operator = NS(_region=lambda c: region, _ink=NS(drawing=True), _extend_stroke=Mock())
    context = NS(window_manager=NS(mixar_mark_armed=True))
    event = NS(type=event_type, value='NOTHING', mouse_x=150, mouse_y=80)
    assert namespace['modal'](operator, context, event) == {'RUNNING_MODAL'}
    if event_type != 'MIDDLEMOUSE':
        operator._extend_stroke.assert_called_once_with((50.0, 60.0))
    else:
        operator._extend_stroke.assert_not_called()
