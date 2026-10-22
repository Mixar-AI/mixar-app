# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The scene-flag listener runs ``on_finish`` per scene as its flag clears,
while the Generate progress bar is WindowManager-wide: the hooks that complete
it must wait until no scene is still generating."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"


def _on_finish_source(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_on_finish":
            return ast.unparse(node)
    raise AssertionError(f"no _on_finish in {path}")


@pytest.mark.parametrize("rel, flag", [
    ("ui/operators/lookdev_scene_ops.py", "mixie_lookdev_is_generating"),
    ("core/scene_gen_queue.py", "mixie_segment_to_3d_is_generating"),
])
def test_progress_completes_only_when_no_scene_still_generates(rel, flag):
    body = _on_finish_source(MOODBOARD / rel)
    assert "complete_progress" in body
    assert "bpy.data.scenes" in body
    assert flag in body
    assert body.index(flag) < body.index("complete_progress(")
