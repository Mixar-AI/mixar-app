# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run the inline text modals without Blender's mocked Operator base."""

import ast
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / 'src/scripts/mixar/modules/moodboard'


def modal(kind):
    constants = ast.parse((MODULE / 'constants.py').read_text())
    navigation = next(n for n in constants.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == 'TEXTBOX_NAVIGATION_EVENTS'
                              for t in n.targets))
    tree = ast.parse((MODULE / 'ui/operators/textbox_ops.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
               and n.name == f'MIXIE_OT_moodboard_{kind}_textbox')
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'modal')
    state = {'index': 0, 'value': 'Draft', 'original': 'Original',
             'select_all': False, 'armed': False}
    scope = {'_EDIT': state, '_CARET': '|', '_tag_moodboard_redraw': Mock()}
    exec(compile(ast.Module(body=[navigation, fn], type_ignores=[]), '<text modal>', 'exec'), scope)
    return scope['modal'], state


@pytest.mark.parametrize('kind', ['add', 'edit'])
@pytest.mark.parametrize('event_type', [
    'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'WHEELLEFTMOUSE', 'WHEELRIGHTMOUSE',
    'TRACKPADZOOM', 'TRACKPADPAN',
])
def test_navigation_passes_through_without_changing_draft(kind, event_type):
    fn, state = modal(kind)
    before = state.copy()
    box = NS(text='Draft|', position_x=20, position_y=40)
    context = NS(scene=NS(mixie_moodboard_textboxes=[box]))
    event = NS(type=event_type, value='NOTHING' if event_type.startswith('TRACKPAD') else 'PRESS')
    assert fn(NS(), context, event) == {'PASS_THROUGH'}
    assert state == before
    assert vars(box) == {'text': 'Draft|', 'position_x': 20, 'position_y': 40}


@pytest.mark.parametrize('finish,expected,status', [
    ('RET', 'Draft!', 'FINISHED'), ('ESC', 'Original', 'CANCELLED'),
])
def test_edit_can_continue_and_confirm_or_cancel_after_navigation(finish, expected, status):
    fn, state = modal('edit')
    box = NS(text='Draft|')
    context = NS(scene=NS(mixie_moodboard_textboxes=[box]))
    operator = NS(report=Mock())
    assert fn(operator, context, NS(type='TRACKPADZOOM', value='NOTHING')) == {'PASS_THROUGH'}
    assert fn(operator, context, NS(type='A', value='PRESS', unicode='!')) == {'RUNNING_MODAL'}
    assert box.text == 'Draft!|'
    assert fn(operator, context, NS(type=finish, value='PRESS')) == {status}
    assert box.text == expected
