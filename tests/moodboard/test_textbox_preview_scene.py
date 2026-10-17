# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Add Text's cursor-following preview box is pinned to the scene it was added
to, and every way out of the modal (cancel(), ESC, window deactivate) removes
it and balances ``begin_preview``."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "src/scripts/mixar/modules/moodboard/ui/operators"


def _operator():
    tree = ast.parse((OPS / "textbox_add_ops.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "MIXIE_OT_moodboard_add_textbox":
            return {f.name: f for f in node.body if isinstance(f, ast.FunctionDef)}
    raise AssertionError("MIXIE_OT_moodboard_add_textbox not found")


def test_the_operator_defines_cancel_that_discards_the_preview():
    methods = _operator()
    assert "cancel" in methods
    assert "_discard_preview" in ast.unparse(methods["cancel"])
    discard = ast.unparse(methods["_discard_preview"])
    assert "boxes.remove(self._tb_index)" in discard
    assert "end_preview(scene" in discard


def test_modal_never_uses_the_live_context_scene():
    modal = ast.unparse(_operator()["modal"])
    assert "context.scene" not in modal
    assert "self._preview_scene()" in modal
    assert "WINDOW_DEACTIVATE" in modal


def test_the_scene_is_pinned_by_session_uid_at_invoke():
    methods = _operator()
    assert "self._scene_uid = scene.session_uid" in ast.unparse(methods["invoke"])
    assert "session_uid" in ast.unparse(methods["_preview_scene"])


def test_the_operator_is_registered_exactly_once():
    ids = []
    for path in OPS.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "class MIXIE_OT_moodboard_add_textbox(" in text:
            ids.append(path.name)
    assert ids == ["textbox_add_ops.py"]
    tree = ast.parse((OPS / "textbox_add_ops.py").read_text(encoding="utf-8"))
    classes = next(
        n for n in tree.body
        if isinstance(n, ast.Assign) and n.targets[0].id == "classes"
    )
    assert "MIXIE_OT_moodboard_add_textbox" in ast.unparse(classes.value)
