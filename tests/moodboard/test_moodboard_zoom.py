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


INTERFACE = ROOT / "src/source/blender/editors/interface"


def _function(source, signature):
    start = source.index("{", source.rindex(signature))
    depth = 1
    end = start + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


def test_canvas_text_navigation_bypasses_both_input_handlers():
    source = _read(INTERFACE / "interface_handlers.cc")
    for name in ("static int handle_button_event(", "static int handler_region_menu("):
        body = _function(source, name)
        guard = body.index("moodboard_text_navigation_event(C, but, event)")
        assert "BUTTON_STATE_TEXT_EDITING" in body[:guard]
        assert "BUTTON_STATE_TEXT_SELECTING" in body[:guard]
        assert "return WM_UI_HANDLER_CONTINUE;" in body[guard:guard + 140]
        # The edit must survive navigation: neither commit nor cancel it first.
        assert "button_activate_exit" not in body[:guard]
        assert "handle_button_event(C" not in body[:guard]


def test_canvas_navigation_is_scoped_and_includes_pinch():
    body = _read(INTERFACE / "interface_moodboard_navigation.hh")
    for event in ("MOUSEZOOM", "MOUSEPAN", "WHEELUPMOUSE", "WHEELDOWNMOUSE"):
        assert event in body
    assert "CTX_wm_region_popup(C)" in body
    assert "BLI_rcti_isect_pt_v(&region->winrct, event->xy)" in body
    assert "area->spacetype == SPACE_MIXIE && region->regiontype == RGN_TYPE_WINDOW" in body
    assert "area->spacetype == SPACE_VIEW3D && region->regiontype == RGN_TYPE_TOOL_PROPS" in body
    assert "ButtonType::Text, ButtonType::TextBox" in body
    assert "ButtonType::SearchMenu" not in body
    assert "RGN_TYPE_UI" not in body
