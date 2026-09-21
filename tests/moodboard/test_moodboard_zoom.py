# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Trackpad pinch zooms the moodboard canvas, never selected-item scale."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"
SPACE_MIXIE = ROOT / "src/source/blender/editors/space_mixie"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_pinch_zooms_the_view_and_never_writes_item_scale():
    zoom = _read(SPACE_MIXIE / "mixie_moodboard_ops_zoom.cc")
    invoke = zoom.split("moodboard_zoom_invoke(")[1].split("/** \\name Moodboard Ensure-Visible")[0]

    assert "v2d->cur" in invoke
    assert "view2d_curRect_validate" in invoke
    assert "RNA_property_float_set" not in invoke
    assert '"scale"' not in invoke
    assert '"selected"' not in invoke
    assert "MOODBOARD_IMAGE_MIN_SCALE" not in invoke
    assert "any_selected" not in invoke


def test_pinch_operator_is_named_as_canvas_zoom():
    zoom = _read(SPACE_MIXIE / "mixie_moodboard_ops_zoom.cc")
    assert 'ot->name = "Zoom Moodboard"' in zoom
    assert "Zoom selected images" not in zoom.lower()
    assert 'ot->description = "Zoom the moodboard canvas"' in zoom


def test_pinch_keymap_is_bound_in_c_and_addon():
    space = _read(SPACE_MIXIE / "space_mixie.cc")
    keymap = _read(MOODBOARD / "ui/keymap.py")

    assert 'WM_keymap_add_item(keymap, "MIXIE_OT_moodboard_zoom"' in space
    assert "MOUSEZOOM" in space
    assert "Zoom selected images" not in space

    assert "'mixie.moodboard_zoom'" in keymap
    assert "type='TRACKPADZOOM'" in keymap
    bind = keymap.split("'mixie.moodboard_zoom'")[1][:160]
    assert "TRACKPADZOOM" in bind
