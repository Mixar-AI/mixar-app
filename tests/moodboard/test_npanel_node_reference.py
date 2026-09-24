# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""N-panel 'use selected' references must include selected node results."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"
COMMON = ROOT / "src/scripts/mixar/modules/common"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_image_gen_npanel_uses_the_shared_reference_stills():
    drawers = _read(MOODBOARD / "ui/sidebar_panel_drawers.py")
    helpers = _read(MOODBOARD / "ui/sidebar_ui_helpers.py")
    tabs = _read(MOODBOARD / "ui/sidebar_tab_drawers.py")
    ops = _read(MOODBOARD / "ui/operators/imagegen_ops.py")
    popup = _read(MOODBOARD / "ui/operators/popup_imagegen_ops.py")
    counts = _read(COMMON / "utils/mixie_space_utils.py")

    assert "selected_reference_stills" in drawers
    assert "item.selected and is_still_item" not in drawers
    assert "selected_reference_stills" in helpers
    assert "first_selected_reference_still" in helpers
    assert "selected_reference_stills" in ops
    assert "item.selected and is_still_item" not in ops
    assert "selected_reference_stills" in popup
    assert "selected_reference_stills" in counts
    assert "first_selected_reference_still" in counts
    assert "selected_reference_still_entries" in tabs
    assert "img_item is selected_item" not in tabs


def test_video_gen_selection_walks_exportable_media():
    media = _read(MOODBOARD / "core/media_utils.py")
    video_fn = media.split("def get_selected_moodboard_video_inputs")[1].split(
        "def get_selected_moodboard_media_inputs"
    )[0]
    mixed_fn = media.split("def get_selected_moodboard_media_inputs")[1]
    assert "selected_exportable_media" in video_fn
    assert "selected_exportable_media" in mixed_fn
    assert 'getattr(item, "selected", False) and is_video_item' not in video_fn


def test_in_place_edits_still_ignore_node_owned_results():
    menus = _read(MOODBOARD / "ui/moodboard_menus.py")
    for operator in (
        "mixie.moodboard_crop_tool",
        "mixie.rotate_images",
        "mixie.flip_horizontal",
        "mixie.flip_vertical",
    ):
        before = menus.split(operator)[0]
        assert "selected_exportable_media" not in before[-400:]
        assert "selected_reference_stills" not in before[-400:]
