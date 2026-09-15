# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run the real quick-prompt execute body without mocked Operator inheritance."""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

PATH = Path(__file__).resolve().parents[1] / 'src/scripts/mixar/modules/space_mixie_chat/ui/operators/quick_prompt_ops.py'


@pytest.mark.parametrize('outcome', [{'FINISHED'}, {'CANCELLED'}, RuntimeError('send failed')])
def test_quick_prompt_preserves_main_draft_for_every_result(outcome):
    tree = ast.parse(PATH.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    execute = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'execute')
    draft = 'An unfinished draft\nwith Unicode: café'
    scene = SimpleNamespace(mixie_chat_input=draft, mixie_chat_mode='AGENT')
    wm = SimpleNamespace(mixie_chat_quick_prompt_input='shortcut text', mixie_chat_quick_prompt_mode='AGENT')
    calls = []
    def send(**kw):
        calls.append(kw)
        assert scene.mixie_chat_input == draft
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    namespace = {
        'DEV_MODE': False, 'MAX_MESSAGE_LENGTH': 100000,
        'get_session_manager': MagicMock(),
        'get_connection_manager': lambda: SimpleNamespace(is_connected=True),
        'can_send': lambda scene: (True, ''),
        'bpy': SimpleNamespace(ops=SimpleNamespace(mixie_chat=SimpleNamespace(send_message=send))),
    }
    exec(compile(ast.Module(body=[execute], type_ignores=[]), str(PATH), 'exec'), namespace)
    invoke = lambda: namespace['execute'](SimpleNamespace(message='', report=MagicMock()),
                                         SimpleNamespace(scene=scene, window_manager=wm))
    if isinstance(outcome, Exception):
        with pytest.raises(RuntimeError, match='send failed'):
            invoke()
    else:
        assert invoke() == outcome
    assert calls == [{'message_override': 'shortcut text'}]
    assert scene.mixie_chat_input == draft
    assert wm.mixie_chat_quick_prompt_input == ('' if outcome == {'FINISHED'} else 'shortcut text')
