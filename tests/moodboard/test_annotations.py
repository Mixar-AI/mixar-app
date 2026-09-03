# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Contracts for image-attached moodboard freehand annotations."""

import math
from pathlib import Path

from mixar.modules.moodboard.core.annotation_geometry import (
    canvas_to_image_normalized,
)


ROOT = Path(__file__).resolve().parents[2]
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"
MIXIE_CPP = ROOT / "src/source/blender/editors/space_mixie"


def _assert_point_close(actual, expected):
    assert math.isclose(actual[0], expected[0], abs_tol=1e-9)
    assert math.isclose(actual[1], expected[1], abs_tol=1e-9)


def test_canvas_coordinates_map_to_normalized_image_space():
    assert canvas_to_image_normalized(75, 50, 0, 0, 100, 100) == (0.75, 0.5)


def test_canvas_coordinates_follow_image_rotation():
    coords = canvas_to_image_normalized(
        50,
        25,
        0,
        0,
        100,
        100,
        rotation=90.0,
    )

    _assert_point_close(coords, (0.25, 0.5))


def test_canvas_coordinates_follow_image_flips():
    horizontal = canvas_to_image_normalized(
        75,
        50,
        0,
        0,
        100,
        100,
        flip_horizontal=True,
    )
    vertical = canvas_to_image_normalized(
        50,
        75,
        0,
        0,
        100,
        100,
        flip_vertical=True,
    )

    _assert_point_close(horizontal, (0.25, 0.5))
    _assert_point_close(vertical, (0.5, 0.25))


def test_invalid_display_size_fails_closed():
    assert canvas_to_image_normalized(0, 0, 0, 0, 0, 100) is None


def test_annotation_properties_are_persistent_and_image_attached():
    props = (MOODBOARD / "ui/moodboard_annotation_props.py").read_text(encoding="utf-8")
    images = (MOODBOARD / "ui/moodboard_properties.py").read_text(encoding="utf-8")
    registration = (MOODBOARD / "ui/moodboard_scene_registration.py").read_text(encoding="utf-8")

    assert "class MixieMoodboardAnnotationPoint" in props
    assert "class MixieMoodboardAnnotationStroke" in props
    assert "options={'SKIP_SAVE'}" not in props
    assert "annotations: CollectionProperty(" in images
    assert "show_annotations: BoolProperty(" in images
    registered_classes = registration[registration.index("classes = (") :]
    assert registered_classes.index(
        "MixieMoodboardAnnotationPoint,"
    ) < registered_classes.index("MixieMoodboardImage,")


def test_annotation_tool_exposes_complete_editing_workflow():
    operators = (MOODBOARD / "ui/operators/annotation_ops.py").read_text(encoding="utf-8")
    toolbar = (MOODBOARD / "ui/moodboard_toolbar.py").read_text(encoding="utf-8")
    duplicate = (MOODBOARD / "ui/operators/transform_ops.py").read_text(encoding="utf-8")

    assert 'bl_idname = "mixie.moodboard_annotate_tool"' in operators
    assert 'bl_idname = "mixie.moodboard_undo_annotation"' in operators
    assert 'bl_idname = "mixie.moodboard_clear_annotations"' in operators
    assert 'bl_options = {"REGISTER", "UNDO"}' in operators
    assert '"BLOCKING"' not in operators
    assert 'self.report({"INFO"}, "Annotation stroke added")' in operators
    # The toolbar's annotate slot is hidden for now — the gaming workflow
    # puts a direct Multi-Lasso button there instead. The annotation
    # operators and settings popover stay registered for the popover class
    # (and future re-surfacing), but the toolbar draw must not show them.
    assert 'row.operator(\n            "mixie.moodboard_lasso_tool"' in toolbar
    assert 'row.operator(\n            "mixie.moodboard_annotate_tool"' not in toolbar
    assert 'bl_idname = "MIXIE_PT_annotation_tools_popover"' in toolbar
    assert "MIXIE_PT_annotation_tools_popover," in toolbar  # still registered
    assert 'col.prop(state, "annotation_color"' in toolbar
    assert 'col.prop(state, "annotation_width"' in toolbar
    assert "for original_stroke in orig_img.annotations" in duplicate


def test_native_renderer_draws_annotations_inside_image_transform():
    renderer = (MIXIE_CPP / "mixie_draw_moodboard_images.cc").read_text(encoding="utf-8")
    annotations = (MIXIE_CPP / "mixie_draw_moodboard_annotations.cc").read_text(encoding="utf-8")
    cmake = (MIXIE_CPP / "CMakeLists.txt").read_text(encoding="utf-8")

    matrix_push = renderer.index("GPU_matrix_push();")
    draw_call = renderer.index("mixie_draw_moodboard_annotations(")
    matrix_pop = renderer.index("GPU_matrix_pop();")
    assert matrix_push < draw_call < matrix_pop
    assert "GPU_PRIM_LINE_STRIP" in annotations
    assert "show_annotations" in annotations
    assert "mixie_draw_moodboard_annotations.cc" in cmake
