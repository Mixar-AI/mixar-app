# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Image to 3D queues one job per selected moodboard still.

Both Generate operators (the catalog-driven ``mixie.model_gen_generate`` the
island 3D pane dispatches to, and the legacy ``mixie.image_to_3d_generate``)
used to read only the first selected still, so N references on the strip
produced a single model.
"""

from pathlib import Path
from types import SimpleNamespace

from mixar.modules.moodboard.core.model_gen_inputs import (
    selected_input_images,
    tab_input_images,
)

OPS = Path(__file__).resolve().parents[2] / "src/scripts/mixar/modules/moodboard/ui/operators"


def _image(name):
    return SimpleNamespace(name=name, source="FILE")


def _item(image, *, selected=True, group="", main_group=""):
    return SimpleNamespace(
        image=image, selected=selected, embedded_node_id="",
        turnaround_group=group, turnaround_main_group=main_group, view_type="LEFT",
    )


def _scene(*items):
    return SimpleNamespace(mixie_moodboard_images=list(items), mixie_moodboard_action_nodes=[])


def test_every_selected_still_is_an_input():
    a, b, c = _image("fable.png"), _image("barscene3.png"), _image("other.png")
    scene = _scene(_item(a), _item(b), _item(c, selected=False))
    assert selected_input_images(scene) == [a, b]


def test_companion_view_rides_its_selected_frontal_image():
    front, side, other = _image("front"), _image("side"), _image("other")
    scene = _scene(
        _item(front, main_group="g1"),
        _item(side, group="g1"),
        _item(other),
    )
    assert selected_input_images(scene) == [front, other]


def test_companion_alone_is_still_submitted():
    front, side = _image("front"), _image("side")
    scene = _scene(_item(front, selected=False, main_group="g1"), _item(side, group="g1"))
    assert selected_input_images(scene) == [side]


def test_tab_upload_mode_is_its_single_reference():
    a, up = _image("a"), _image("upload")
    scene = _scene(_item(a))
    assert tab_input_images(scene, SimpleNamespace(use_selected_image=False, reference_image=up)) == [up]
    assert tab_input_images(scene, SimpleNamespace(use_selected_image=False, reference_image=None)) == []
    assert tab_input_images(scene, SimpleNamespace(use_selected_image=True, reference_image=up)) == [a]


def test_model_gen_operator_submits_each_input():
    src = (OPS / "model_gen_ops.py").read_text()
    assert "first_selected_reference_still" not in src
    assert "tab_input_images(scene, tab)" in src
    assert "for image in images:" in src


def test_legacy_operator_submits_each_selected_image():
    src = (OPS / "image_to_3d_ops.py").read_text()
    assert "selected[0].image" not in src
    assert "selected_input_images(scene)" in src
    assert "for img in [image, *extra_images]" in src
