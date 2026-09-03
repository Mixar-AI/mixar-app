# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The asset-choice fallback render must link the asset inside the rig.

``PreviewRenderRig.__enter__`` sets ``hide_render = True`` on every scene
object that is not part of the rig. ``asset_choice_previews._generate`` used
to link the appended asset into the scene collection BEFORE entering the rig,
so the asset was hidden from its own fallback EEVEE render and every library
asset without an embedded preview got a blank thumbnail. The sibling
implementations (``RenderSession``, ``scene_asset_exporter._attach_preview``)
already enter the rig before appending.

Pinned here: inside ``_generate``, every ``scene_coll`` link call sits within
the ``with PreviewRenderRig`` body (after ``__enter__``, before the render).
"""

import ast
from pathlib import Path

SOURCE = (
    Path(__file__).resolve().parents[1]
    / "src/scripts/mixar/modules/space_mixie_chat/core/asset_choice_previews.py"
)


def _generate_function():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_generate":
            return node
    raise AssertionError("_generate not found in asset_choice_previews.py")


def _with_rig_span(func):
    """(start, end) line span of the ``with PreviewRenderRig`` statement."""
    for node in ast.walk(func):
        if isinstance(node, ast.With):
            src = ast.get_source_segment(SOURCE.read_text(encoding="utf-8"), node) or ""
            if "PreviewRenderRig" in src:
                return node.lineno, node.end_lineno
    raise AssertionError("no 'with PreviewRenderRig' block in _generate")


def _link_call_lines(func):
    lines = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            target = node.func
            attr = target.attr if isinstance(target, ast.Attribute) else None
            if attr in {"link", "children"}:
                lines.add(node.lineno)
    return lines


def test_asset_is_linked_inside_the_render_rig():
    func = _generate_function()
    start, end = _with_rig_span(func)

    # Every scene-collection link call in _generate must be inside the rig
    # block: linking earlier hides the asset from its own render.
    link_lines = {line for line in _link_call_lines(func) if line > start - 10}
    assert link_lines, "expected scene-collection link calls in _generate"
    for line in link_lines:
        assert start < line < end, (
            f"scene link at line {line} is outside the PreviewRenderRig "
            f"block ({start}-{end}) — the rig would hide the asset from "
            "its own fallback render (blank thumbnails)"
        )


def test_frame_camera_stays_inside_the_rig():
    func = _generate_function()
    start, end = _with_rig_span(func)

    frame_calls = [
        node.lineno for node in ast.walk(func)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "frame_camera"
    ]
    assert frame_calls, "expected frame_camera in _generate"
    for line in frame_calls:
        assert start < line < end
