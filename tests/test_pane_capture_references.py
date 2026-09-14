# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""A capture must be included by Image Gen's uploaded-reference branch."""
import ast
from pathlib import Path
from types import SimpleNamespace


class Collection(list):
    def add(self):
        item = SimpleNamespace()
        self.append(item)
        return item


def test_capture_selects_uploaded_references_instead_of_board_selection():
    # Operator classes are mocked outside Blender. Run the real plain helper;
    # replace only the unrelated canvas-placement import.
    path = Path(__file__).resolve().parents[1] / (
        "src/scripts/mixar/modules/agent_bubble/ui/operators/pane_capture_ops.py"
    )
    tree = ast.parse(path.read_text())
    helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                  and n.name == "_attach_to_imagegen")
    helper.body = [n for n in helper.body if not isinstance(n, ast.ImportFrom)]
    namespace = {"place_new_moodboard_item": lambda scene, item: None}
    exec(compile(ast.Module(body=[helper], type_ignores=[]), str(path), "exec"), namespace)
    tab = SimpleNamespace(reference_images=Collection(), use_reference_images=True)
    scene = SimpleNamespace(mixie_moodboard_images=Collection(),
                            mixie_moodboard_sidebar=SimpleNamespace(tab_imagegen=tab))
    image = SimpleNamespace(name="Captured viewport", size=(1280, 720))
    namespace["_attach_to_imagegen"](scene, image, "/tmp/capture.png")
    assert tab.use_reference_images is False
    assert tab.reference_images[0].image is image
    assert scene.mixie_moodboard_images[0].image is image
    assert scene.mixie_moodboard_images[0].selected is False
