# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The actions row sits under the play button: Auto Key and Add Keyframe.

Adding a keyframe is the job in Cinema Mode, and the pair used to live at the
far right of a row whose other half is the ruler — the corner furthest from
the work, and the corner the interpolation dropdown now needs. Under the
transport they are where the eye already is.

`state.auto_key` and `mixar.director_toggle_auto_key` had existed all along
and the compact rail already offered them; the designed surface never did, so
on every viewport big enough to draw it the feature was unreachable.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
ACTIONS = (VIEW3D / "view3d_director_cinema_dock_actions.cc").read_text(encoding="utf-8")
DOCK = (VIEW3D / "view3d_director_cinema_dock.cc").read_text(encoding="utf-8")
STATE = (VIEW3D / "view3d_director_state.cc").read_text(encoding="utf-8")


def _const(source: str, name: str) -> float:
    match = re.search(rf"^constexpr float {name} = (-?[0-9.]+)f;", source, re.M)
    assert match is not None, name
    return float(match.group(1))


def _draw() -> str:
    body = ACTIONS[ACTIONS.index("void cinema_draw_dock_actions(") :]
    return body[: body.index("\n}\n")]


def test_the_dock_hands_the_row_a_centre_line_of_its_own():
    controls = DOCK[DOCK.index("void cinema_draw_dock_controls(") :]
    assert "cinema_draw_dock_actions(" in controls
    assert "row_ymin - (SUB_ROW_GAP + SUB_ROW_H * 0.5f) * u" in controls
    # And it is the LAST group, so it wins any band it shares.
    assert controls.index("cinema_draw_transport(") < controls.index(
        "cinema_draw_dock_actions("
    )


def test_the_row_is_as_tall_as_the_pill_it_holds():
    """SUB_ROW_H is the dock's budget for the row; ACTION_H is what is drawn
    on it. A row shorter than its own content clips it."""
    assert _const(DOCK, "SUB_ROW_H") == _const(ACTIONS, "ACTION_H")


def test_the_height_the_dock_reserves_includes_it():
    body = DOCK[DOCK.index("float cinema_dock_control_height(") :]
    body = body[: body.index("\n}\n")]
    assert "full ? row + (SUB_ROW_GAP + SUB_ROW_H) * u : row" in body


def test_the_group_is_centred_not_the_pill():
    """Centring the pill alone would push Auto Key off to one side of a row
    that is meant to read as one thing."""
    draw = _draw()
    assert "(float(region->winx) - (chips_w + pill_w)) * 0.5f" in draw
    # Floored at the dock's inset: a group wider than the dock starts at
    # the edge rather than off it.
    assert "std::max(" in draw


def test_the_button_is_labelled_and_carries_its_shortcut():
    draw = _draw()
    assert '"Add Keyframe"' in draw
    assert 'const char *key = locked ? nullptr : "I";' in draw
    assert "cinema_keycap(" in draw


def test_a_locked_take_offers_the_take_it_can_actually_make():
    draw = _draw()
    assert '"New Take"' in draw
    assert 'locked ? "MIXAR_OT_director_new_take" : "MIXAR_OT_director_capture_beat"' in draw
    # And it is not offered an Auto Key it could never fire.
    assert "if (!locked) {" in draw


def test_the_pill_is_sized_to_its_own_text():
    """"New Take" and "Add Keyframe" are different widths, and a fixed box
    would clip one of them."""
    draw = _draw()
    assert "cinema_text_width(label, font)" in draw
    assert "const float pill_w = text_w + key_w + ACTION_PAD * 2.0f * u;" in draw


def test_the_label_carries_the_disabled_state():
    """An Emboss::None button paints nothing of its own, so nothing else
    would show that the action cannot fire."""
    draw = _draw()
    assert "enabled ? 1.0f : 0.45f" in draw
    assert "director_overlay_disable_button(but, !enabled);" in draw


def _chip() -> str:
    chip = ACTIONS[ACTIONS.index("void auto_key_chip(") :]
    return chip[: chip.index("\n}\n")]


def test_the_chip_reads_as_armed_not_as_pressed():
    """Green fill for armed, the way every other state chip on the surface
    reads — and it flips RECORD_OFF to RECORD_ON, which is what Blender's own
    timeline does (`rna_scene.cc` ui_icon)."""
    chip = _chip()
    assert "if (armed) {" in chip
    assert "MIXAR_THEME_LOAD(on, Primary);" in chip
    assert "armed ? ICON_RECORD_ON : ICON_RECORD_OFF" in chip
    assert "auto_key_chip(block, C, region, chip, state);" in _draw()


def test_the_chip_is_blenders_own_auto_keying():
    """The Timeline's record button and this chip are ONE switch: an RNA
    toggle on `tool_settings.use_keyframe_insert_auto`, not a Director flag
    behind a Director operator."""
    chip = _chip()
    assert 'RNA_pointer_get(&scene_ptr, "tool_settings")' in chip
    assert '"use_keyframe_insert_auto"' in chip
    assert "cinema_prop_toggle(" in chip
    assert "MIXAR_OT_director_toggle_auto_key" not in ACTIONS
    paint = (VIEW3D / "view3d_director_cinema_paint.cc").read_text(encoding="utf-8")
    toggle = paint[paint.index("ui::Button *cinema_prop_toggle(") :]
    toggle = toggle[: toggle.index("\n}\n")]
    # A plain Toggle, so the caller's glyph is drawn as given.
    assert "ui::ButtonType::Toggle," in toggle
    assert "uiDefIconButR(" in toggle
    # The compact rail's copy of the chip is the same property.
    overlay = (VIEW3D / "view3d_director_overlay.cc").read_text(encoding="utf-8")
    assert '"use_keyframe_insert_auto"' in overlay
    assert "MIXAR_OT_director_toggle_auto_key" not in overlay


def test_it_says_when_a_take_is_actually_going_down():
    """One switch, and it tells you which half of itself is running. The
    status is published by the recorder, never by a second button."""
    chip = _chip()
    assert "state.recording ? ICON_REC" in chip
    assert "Recording a take" in chip


def test_there_is_no_second_auto_key_switch():
    """Blender ships ONE auto-key toggle. A Record chip beside this one asked
    the director to choose between two of our words for the same idea."""
    assert "MIXAR_OT_director_toggle_record" not in ACTIONS
    assert "CHIP_GAP" not in ACTIONS


def test_the_state_reaches_the_painter():
    """Read the way Blender reads it, not back through the Python proxy."""
    assert "r_state->auto_key = animrig::is_autokey_on(scene);" in STATE
    assert '#include "ANIM_keyframing.hh"' in STATE
    assert '"auto_key"' not in STATE


def test_every_control_is_published_for_qa():
    assert 'cinema_qa_record(region, pill, "director_capture"' in _draw()
    assert (
        'cinema_qa_record(region, chip, "director_auto_key", armed ? "on" : "off", -1);'
        in ACTIONS
    )


def test_the_anonymous_icon_row_is_gone():
    assert "tool_icon" not in DOCK
    assert "TOOL_SIZE" not in DOCK
    # And the right-edge action group it replaced.
    assert "draw_primary_action" not in DOCK
