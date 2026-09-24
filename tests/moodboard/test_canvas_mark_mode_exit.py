# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Picking another canvas tool releases canvas Annotate/Erase.

Annotate is sticky by design (release keeps the pencil armed), so the Text
tool and the image tools must hand it off explicitly; otherwise the first
click after placing a text box drew a stroke again.
"""

import ast
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from mixar.modules.moodboard.core import canvas_mark_mode
from mixar.modules.moodboard.ui import moodboard_edit_state

ROOT = Path(__file__).resolve().parents[2]
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"


def _context(*, annotating=False, erasing=False):
    return NS(
        scene=NS(mixie_moodboard_show_annotations=False, mixie_moodboard_textboxes=[]),
        window_manager=NS(mixie_moodboard_annotating=annotating,
                          mixie_moodboard_erasing=erasing),
    )


@pytest.fixture(autouse=True)
def quiet_redraw(monkeypatch):
    redraw = Mock()
    monkeypatch.setattr(canvas_mark_mode, "redraw_moodboard_canvases", redraw)
    return redraw


@pytest.mark.parametrize("annotating, erasing", [(True, False), (False, True)])
def test_exit_releases_whichever_mode_is_on(annotating, erasing, quiet_redraw):
    context = _context(annotating=annotating, erasing=erasing)
    assert canvas_mark_mode.exit_canvas_mark_mode(context)
    assert canvas_mark_mode.canvas_mark_mode(context.window_manager) == (False, False)
    quiet_redraw.assert_called_once()


def test_exit_is_a_no_op_when_no_mode_is_on(quiet_redraw):
    context = _context()
    assert not canvas_mark_mode.exit_canvas_mark_mode(context)
    quiet_redraw.assert_not_called()
    assert not canvas_mark_mode.exit_canvas_mark_mode(NS(window_manager=None))


def test_set_mode_reveals_strokes_and_keeps_modes_exclusive():
    context = _context(erasing=True)
    canvas_mark_mode.set_canvas_mark_mode(context, annotating=True)
    assert canvas_mark_mode.canvas_mark_mode(context.window_manager) == (True, False)
    assert context.scene.mixie_moodboard_show_annotations


def test_image_tool_activation_releases_canvas_marks(monkeypatch):
    calls = []
    monkeypatch.setattr(moodboard_edit_state, "exit_canvas_mark_mode",
                        lambda context: calls.append(context))
    context = _context(annotating=True)
    moodboard_edit_state._on_active_tool_update(NS(active_tool="BOX_MASK"), context)
    assert calls == [context]
    # Cancelling a tool (back to NONE) never touches the pencil.
    moodboard_edit_state._on_active_tool_update(NS(active_tool="NONE"), context)
    assert calls == [context]


def test_active_tool_property_carries_the_update_hook():
    source = (MOODBOARD / "ui/moodboard_edit_state.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    state = next(node for node in tree.body
                 if isinstance(node, ast.ClassDef) and node.name == "MoodboardEditToolState")
    active_tool = next(node for node in state.body
                       if isinstance(node, ast.AnnAssign) and node.target.id == "active_tool")
    keywords = {kw.arg: kw.value for kw in active_tool.annotation.keywords}
    assert keywords["update"].id == "_on_active_tool_update"


def _textbox_ops_scope():
    source = ast.parse((MOODBOARD / "ui/operators/textbox_ops.py").read_text(encoding="utf-8"))
    source.body = [node for node in source.body
                   if not isinstance(node, (ast.Import, ast.ImportFrom))]
    exits = []
    scope = {
        "Operator": object, "IntProperty": Mock(), "StringProperty": Mock(),
        "format_shortcut": lambda key: key,
        "TEXTBOX_TEXT_DEFAULT": "Text", "TEXTBOX_WIDTH_DEFAULT": 10,
        "TEXTBOX_HEIGHT_DEFAULT": 4, "TEXTBOX_FONT_SIZE_DEFAULT": 12,
        "get_moodboard_viewport_center": lambda: (0.0, 0.0),
        "find_moodboard_canvas_region": lambda context: None,
        "redraw_moodboard_canvases": Mock(),
        "release_moodboard_image_entry": Mock(),
        "exit_canvas_mark_mode": lambda context: exits.append(context) or True,
    }
    exec(compile(source, "textbox_ops.py", "exec"), scope)
    return scope, exits


class _Boxes(list):
    def add(self):
        item = NS()
        self.append(item)
        return item


def test_text_tool_releases_canvas_marks_on_invoke_and_execute():
    scope, exits = _textbox_ops_scope()
    op = scope["MIXIE_OT_moodboard_add_textbox"]()
    op.text = ""
    op.report = Mock()
    context = _context(annotating=True)
    context.scene.mixie_moodboard_textboxes = _Boxes()
    context.scene.mixie_moodboard_images = []
    # No visible canvas region: invoke falls through to execute, and the
    # pencil is released before the box exists either way.
    assert op.invoke(context, NS(mouse_x=0, mouse_y=0)) == {"FINISHED"}
    assert exits and exits[0] is context
    assert len(context.scene.mixie_moodboard_textboxes) == 1
