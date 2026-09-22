# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""User-facing button copy that was wrong on the blastoff surfaces.

These strings are what a hover or a painted label shows. They are pinned
here because a C++ button and a Python docstring both compile either way.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_cinema_output_label_does_not_say_png_sentence():
    left = _text("src/source/blender/editors/space_view3d/view3d_director_cinema_left.cc")
    assert "Png Sequence" not in left


def test_z_fixed_template_label_has_no_stray_space():
    constants = _text("src/scripts/mixar/modules/director/constants.py")
    left = _text("src/source/blender/editors/space_view3d/view3d_director_cinema_left.cc")
    assert '"Z-Fixed"' in constants
    assert '"Z-Fixed"' in left
    assert "Z- Fixed" not in constants
    assert "Z- Fixed" not in left


def test_generate_tooltip_does_not_say_inference_node():
    ops = _text("src/scripts/mixar/modules/moodboard/ui/operators/node_graph_ops.py")
    assert 'bl_description = "Add this generation to the queue"' in ops
    assert "Submit this inference node to the generation queue" not in ops


def test_mask_and_colour_tooltips_are_user_facing():
    toolbar = _text("src/scripts/mixar/modules/moodboard/ui/moodboard_toolbar.py")
    frames = _text("src/scripts/mixar/modules/moodboard/ui/moodboard_frame_menus.py")
    assert '"""Image mask selection tools"""' in toolbar
    assert "class MIXIE_MT_mask_tools" in toolbar
    assert "Popover panel with all mask selection tools" not in toolbar
    assert '''"""Choose this frame's colour"""''' in frames
    assert "The eight palette pastels" not in frames


def test_empty_painted_buttons_do_not_title_tooltips_with_the_operator_name():
    interface = _text("src/source/blender/editors/interface/interface.cc")
    start = interface.index("std::string button_string_get_label(Button &but)")
    body = interface[start : interface.index("button_context_menu_title_from_button", start)]
    assert "!but.rnaprop" in body
    assert "but.tip_explicit" in body
    assert "but.icon == ICON_NONE" in body
    assert "but.tip_func" in body
    assert "return {};" in body


def test_rna_description_autofill_does_not_count_as_a_caller_tip():
    interface = _text("src/source/blender/editors/interface/interface.cc")
    rna = interface[
        interface.index("static Button *def_but_rna(") : interface.index(
            "static Button *def_but_rna_propname("
        )
    ]
    operator = interface[
        interface.index("static Button *def_but_operator_ptr(") : interface.index(
            "Button *uiDefBut("
        )
    ]
    assert "tip_explicit" not in rna
    assert operator.index("const bool tip_explicit") < operator.index("RNA_struct_ui_description")


def test_media_rename_tooltip_is_grammatical():
    media = _text("src/source/blender/editors/space_mixie/mixie_draw_moodboard_media_actions.cc")
    assert "Edit the name of this image or video in place" in media
    assert "image or video's" not in media
