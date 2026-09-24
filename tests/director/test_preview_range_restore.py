# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Leaving Director hands the scene's preview range back.

Directing scopes the preview range to the active shot's beats
(`release_preview_range`), which is a SCENE setting the user may have been
using themselves. The session used to leave it that way, so after a director
closed Cinema Mode their own playback was silently confined to whichever shot
they last looked at.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIEWPORT = (
    ROOT / "src/scripts/mixar/modules/director/core/viewport.py"
).read_text(encoding="utf-8")

FRAME_MATH = (
    ROOT / "src/scripts/mixar/modules/director/core/frame_math.py"
).read_text(encoding="utf-8")

_TREE = ast.parse(VIEWPORT)


def _function(name: str) -> str:
    return ast.unparse(
        next(
            node
            for node in ast.walk(_TREE)
            if isinstance(node, ast.FunctionDef) and node.name == name
        )
    )


_RANGE_FIELDS = ("use_preview_range", "frame_preview_start", "frame_preview_end")


def test_entry_remembers_the_whole_preview_range():
    """The flag alone is not enough: restoring `use_preview_range` over a
    range Director rewrote gives the user someone else's range."""
    remember = _function("remember_view")
    for field in _RANGE_FIELDS:
        assert field in remember, field


def test_exit_restores_it():
    restore = _function("restore_view")
    assert "state.get('preview_range', {})" in restore.replace('"', "'")


def test_restoring_never_strands_the_rest_of_the_teardown():
    """A dead or read-only property must not stop the viewport being handed
    back — the same rule the camera and chrome restores already follow."""
    restore = _function("restore_view")
    body = restore[restore.index("preview_range") :]
    assert "except (AttributeError, TypeError)" in body


def test_it_is_written_only_when_it_differs():
    """Every write here is an undo push and a file dirty flag."""
    restore = _function("restore_view")
    body = restore[restore.index("preview_range") :]
    assert "!= preview['use_preview_range']" in body.replace('"', "'")
    assert "if getattr(scene, name) != value:" in FRAME_MATH


def test_the_two_edges_are_written_so_neither_is_clamped_away():
    """Blender clamps `frame_preview_start` to the CURRENT end and the end to
    the current start, so one write in either order silently loses an edge
    whenever the restored window does not overlap the scoped one."""
    assert "def write_preview_range(" in FRAME_MATH
    body = FRAME_MATH[FRAME_MATH.index("def write_preview_range(") :]
    # Start, end, start: the first write gets as far as the old end allows,
    # the second opens the end, the third finishes the start off.
    assert (
        '("frame_preview_start", start),\n'
        '        ("frame_preview_end", end),\n'
        '        ("frame_preview_start", start),'
    ) in body
    # The restore paths go through it rather than writing the two fields.
    assert "write_preview_range(" in _function("restore_view")
    timeline = (
        ROOT / "src/scripts/mixar/modules/director/core/timeline.py"
    ).read_text(encoding="utf-8")
    assert "write_preview_range(scene, scene_state[2], scene_state[3])" in timeline
    # Nothing left assigns an edge on its own — in the core module or in the
    # operators that restore a remembered window on cancel.
    operators = ROOT / "src/scripts/mixar/modules/director/ui/operators"
    sources = [timeline, FRAME_MATH, VIEWPORT] + [
        (operators / name).read_text(encoding="utf-8")
        for name in ("timeline_ops.py", "selection_ops.py")
    ]
    for source in sources:
        for field in ("frame_preview_start", "frame_preview_end"):
            assert not re.search(rf"\.{field}\s*=[^=]", source), field
