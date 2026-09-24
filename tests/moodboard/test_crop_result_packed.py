# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A canvas Crop result is packed, so it survives a save and reload.

``mixie.moodboard_crop_image`` (C++) writes the crop into a new GENERATED
float image with no file behind it. Unpacked, it reloads as a blank image
while the board still shows its card. ``mixie.moodboard_apply_crop`` packs
every GENERATED image the crop added.

``bpy.types.Operator`` is a ``MagicMock`` here, so the operator is checked at
source level.
"""

import ast
from pathlib import Path

_CROP_OPS = Path(__file__).resolve().parents[2] / (
    "src/scripts/mixar/modules/moodboard/ui/operators/moodboard_crop_ops.py")


def _apply_crop_execute():
    tree = ast.parse(_CROP_OPS.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and \
                node.name == "MIXIE_OT_moodboard_apply_crop":
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and \
                        child.name == "execute":
                    return child
    raise AssertionError("moodboard_crop_ops has no apply_crop execute")


def _calls(node, attr):
    return [
        child for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and child.func.attr == attr
    ]


def test_apply_crop_packs_the_new_image():
    execute = _apply_crop_execute()
    crops = _calls(execute, "moodboard_crop_image")
    packs = _calls(execute, "pack")
    assert crops and packs
    assert packs[0].lineno > crops[0].lineno, "pack after the crop runs"


def test_only_images_the_crop_added_are_packed():
    """Snapshot before the crop, so nothing already on file is re-packed."""
    execute = _apply_crop_execute()
    source = ast.get_source_segment(
        _CROP_OPS.read_text(encoding="utf-8"), execute)
    snapshot = source.index("bpy.data.images.keys()")
    assert snapshot < source.index("moodboard_crop_image(")
    assert "image.name in before" in source
    assert "'GENERATED'" in source


def test_a_pack_failure_does_not_abort_the_crop():
    execute = _apply_crop_execute()
    guarded = [
        child for child in ast.walk(execute)
        if isinstance(child, ast.Try)
        and _calls(ast.Module(body=child.body, type_ignores=[]), "pack")
    ]
    assert guarded
    assert any(
        isinstance(handler.type, ast.Name)
        and handler.type.id == "RuntimeError"
        for handler in guarded[0].handlers
    )
