# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""The explicit Handwriting control preserves annotation and active dictation."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from mixar.modules.space_mixie_chat.core import scribble

SOURCE = Path(__file__).resolve().parents[1] / (
    'src/scripts/mixar/modules/space_mixie_chat/ui/operators/ink_ops.py')


def operator():
    tree = ast.parse(SOURCE.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
               and n.name == 'MIXIE_CHAT_OT_ink_toggle')
    cls.bases = [ast.Name(id='object', ctx=ast.Load())]
    scope = {'__package__': 'mixar.modules.space_mixie_chat.ui.operators'}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])),
                 str(SOURCE), 'exec'), scope)
    instance = scope[cls.name]()
    instance.report = MagicMock()
    return instance


def context(ink=False, voice=False):
    return SimpleNamespace(scene=object(), window=None, area=None, window_manager=SimpleNamespace(
        mixar_mark_armed=True, mixie_chat_ink_visible=ink,
        mixie_chat_voice_listening=voice))


def test_explicit_open_releases_text_buffer_and_preserves_annotation(monkeypatch):
    ctx = context()
    release = MagicMock()
    monkeypatch.setattr(scribble, 'release_composer', release)
    monkeypatch.setattr(scribble, '_redraw', lambda: None)
    assert operator().execute(ctx) == {'FINISHED'}
    release.assert_called_once()
    assert ctx.window_manager.mixie_chat_ink_visible
    assert ctx.window_manager.mixar_mark_armed


def test_voice_is_not_cancelled_or_covered_by_handwriting(monkeypatch):
    ctx = context(voice=True)
    release = MagicMock()
    monkeypatch.setattr(scribble, 'release_composer', release)
    op = operator()
    assert op.execute(ctx) == {'CANCELLED'}
    release.assert_not_called()
    assert not ctx.window_manager.mixie_chat_ink_visible
    assert ctx.window_manager.mixie_chat_voice_listening
    assert ctx.window_manager.mixar_mark_armed
    op.report.assert_called_once()


def test_close_flushes_handwriting_without_stopping_annotation(monkeypatch):
    ctx = context(ink=True)
    flush = MagicMock()
    monkeypatch.setattr(scribble, 'flush_pending_ink', flush)
    monkeypatch.setattr(scribble, '_redraw', lambda: None)
    assert operator().execute(ctx) == {'FINISHED'}
    flush.assert_called_once()
    assert not ctx.window_manager.mixie_chat_ink_visible
    assert ctx.window_manager.mixar_mark_armed
