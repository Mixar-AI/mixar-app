# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Every OpenGL viewport capture must arm the scene's output format.

On Blender 5 a scene whose output is FFMPEG rejects PNG outright until
`media_type` is IMAGE, so a capture that only sets `filepath` dies on any
scene configured for video -- or simply left that way by Director's guide
render. `scribble_mark/core/freeze.py` and `director/core/capture.py` both
document the ordering; the island pane capture and the chat screenshot
operator were written without it.

The restore has to be in a `finally` too: the screenshot operator used to
restore after the render, so a failure left the user's own output path,
resolution and format clobbered.
"""

import ast
from pathlib import Path

import pytest

_MODULES = Path(__file__).parents[1] / "src/scripts/mixar/modules"

CAPTURES = {
    "island pane": _MODULES / "agent_bubble/ui/operators/pane_capture_ops.py",
    "chat screenshot": _MODULES / "space_mixie_chat/ui/operators/screenshot_ops.py",
    "scribble freeze": _MODULES / "scribble_mark/core/freeze.py",
    "director capture": _MODULES / "director/core/capture.py",
}


@pytest.mark.parametrize("name,path", sorted(CAPTURES.items()))
def test_a_capture_arms_the_output_format(name, path):
    src = path.read_text(encoding="utf-8")
    assert "render.opengl" in src, f"{name}: no OpenGL capture here any more"
    assert "file_format" in src, f"{name}: does not set file_format"
    assert "media_type" in src, f"{name}: does not set media_type"
    # media_type must be armed BEFORE file_format, or the assignment is refused.
    arms_png = min(i for q in ("'", '"')
                   if (i := src.find(f"file_format = {q}PNG{q}")) != -1)
    assert src.index("media_type") < arms_png, f"{name}: sets file_format before media_type"


@pytest.mark.parametrize("name,path", sorted(CAPTURES.items()))
def test_a_capture_restores_the_scene_in_a_finally(name, path):
    """A failed capture must not leave the user's render settings changed."""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    guarded = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Try) and node.finalbody
        and "render.opengl" in (ast.get_source_segment(src, node) or "")
    ]
    assert guarded, f"{name}: the capture is not wrapped in try/finally"
    restored = "\n".join(
        ast.get_source_segment(src, stmt) or "" for stmt in guarded[0].finalbody
    )
    assert "file_format" in restored, f"{name}: does not restore file_format"
