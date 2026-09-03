# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layout contracts of the agent island's generation panes.

Source-level, like the rest of the island's C++ surface (see
``test_agent_bubble_panes.py``): these are draw-geometry rules with no
importable Python half.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "src/source/blender/editors/space_agent_bubble"

KIT_CC = (CPP / "agent_ui_pane_kit.cc").read_text(encoding="utf-8")
KIT_HH = (CPP / "agent_ui_pane_kit.hh").read_text(encoding="utf-8")
TAB3D = (CPP / "agent_ui_tab3d.cc").read_text(encoding="utf-8")
TAB3D_PARAMS = (CPP / "agent_ui_tab3d_params.cc").read_text(encoding="utf-8")
MEDIA = (CPP / "agent_ui_tabmedia.cc").read_text(encoding="utf-8")
SPLAT = (CPP / "agent_ui_tabsplat.cc").read_text(encoding="utf-8")
SPLAT_PAINT = (CPP / "agent_ui_tabsplat_paint.cc").read_text(encoding="utf-8")

PANE_SOURCES = {
    "agent_ui_tab3d.cc": TAB3D,
    "agent_ui_tabmedia.cc": MEDIA,
    "agent_ui_tabsplat_paint.cc": SPLAT_PAINT,
}


def _function(source: str, signature_start: str) -> str:
    """The body of the first function whose text starts with `signature_start`."""
    start = source.index(signature_start)
    depth = 0
    for i in range(source.index("{", start), len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
    raise AssertionError(f"unterminated function at {signature_start!r}")


# -------------------------------------------------------------------------
# The prompt box is reserved FIRST (Generate is a paid action)


def test_every_pane_clamps_its_strip_against_the_params_floor():
    """The prompt box is claimed before the params get their room.

    Params that overflow used to push the strip bottom down until the box fell
    under PANE_BOX_MIN_H — at which point NO text field was created at all,
    while Upload Reference and Generate stayed wired. Generate then submitted
    whatever stale `prompt` string was still on the tab group. Every pane must
    therefore floor its strip at `pane_params_floor`.
    """
    for name, source in PANE_SOURCES.items():
        assert "pane_params_floor(" in source, (
            f"{name}: does not reserve the prompt box before the params strip"
        )


def test_flow_place_tests_the_floor_before_it_consumes_the_row():
    """The off-by-one behind the vanishing prompt field.

    `flow_place` wrapped by decrementing `f->y_top` and only THEN tested the
    floor, so the row that did not fit was consumed anyway — and the strip
    bottom the caller reads back (`y_top - PANE_ROW_H`) sat a whole row below
    the floor it had just been given.
    """
    body = _function(TAB3D_PARAMS, "bool flow_place(")
    floor_test = body.index("y_top - h < f->y_floor")
    committed = [m.start() for m in re.finditer(r"f->y_top\s*=", body)]
    assert committed, "flow_place never commits a row"
    assert all(pos > floor_test for pos in committed), (
        "flow_place mutates f->y_top before testing the floor"
    )


def test_the_params_strip_never_returns_a_bottom_below_its_floor():
    body = _function(TAB3D_PARAMS, "float agent_ui_tab3d_params_draw(")
    tail = body[body.rindex("return ") :]
    assert "y_floor" in tail, (
        "the params strip must clamp its reported bottom to the floor the "
        "caller reserved for the prompt box"
    )


def test_params_that_do_not_fit_are_reported_not_silently_dropped():
    """A schema that outgrows the strip elides inside it, with a count."""
    body = _function(TAB3D_PARAMS, "float agent_ui_tab3d_params_draw(")
    assert "elided" in body and "more" in body


def test_generate_is_armed_only_where_the_prompt_field_exists():
    """A paid action must never submit a prompt the user cannot see or edit."""
    assert "prompt_ok" in TAB3D
    assert "&& prompt_ok" in MEDIA, (
        "the Media pane's can_generate must consult the prompt's visibility"
    )
    assert "rects.prompt_ok" in SPLAT, (
        "the Splat pane must gate its Generate button on prompt_ok"
    )
    assert "prompt_ok" in SPLAT_PAINT


def test_the_splat_field_never_falls_back_over_its_own_chip_row():
    """The old fallback dropped the field to `prompt_box.ymin`, so its
    embossed chrome covered Upload / Capture / the Moodboard switch —
    invisible, and still eating their clicks."""
    body = _function(SPLAT_PAINT, "void splat_pane_rects_build(")
    assert "r->prompt_field.ymin = r->prompt_box.ymin;" not in body


# -------------------------------------------------------------------------
# Bottom row


def test_the_bottom_row_is_clamped_inside_its_box():
    """At a short box the 44u row was placed at `ymin + 16u` and stuck out
    through the box TOP, floating Upload and Generate over the params strip —
    and because the OPS block wins overlapping clicks, the params underneath
    became unreachable."""
    body = _function(KIT_CC, "float pane_bottom_row_ymin(")
    assert "box.ymax" in body, "pane_bottom_row_ymin does not clamp against the box top"
    assert "std::min" in body or "std::max" in body


def test_the_generate_rect_cannot_spill_over_the_box_top():
    body = _function(KIT_CC, "rctf pane_generate_rect(")
    assert "std::min" in body and "box.ymax" in body


# -------------------------------------------------------------------------
# Truncation


def test_truncated_text_gets_an_ellipsis():
    """A bare chop reads as a DIFFERENT string: "ReproCone" rendered as
    "ReproCon" looked like the wrong result, not a shortened name."""
    body = _function(KIT_CC, "void pane_fit_text(")
    assert "\\xE2\\x80\\xA6" in body, "pane_fit_text does not append an ellipsis"
    # Still UTF-8 aware — never split a multi-byte sequence.
    assert "0xC0) == 0x80" in body
    # And it must only ever SHRINK the caller's fixed buffer.
    assert "orig_len" in body


def test_the_kit_documents_the_ellipsis_for_callers():
    assert "ellipsis" in KIT_HH


# -------------------------------------------------------------------------
# Splat strip: catalog labels, measured widths, clamped runs


def test_the_splat_mode_toggle_is_measured_not_design_width():
    """`p_mode`'s labels come from the live catalog, and `pane_label_centre`
    never clips — at the design's fixed Text/Image split a longer mode label
    spilled into the model chip. The LOD track next to it already learned
    this; the mode toggle now shares the measurement."""
    body = _function(SPLAT_PAINT, "void splat_pane_rects_build(")
    assert "pane_segmented_layout(\n        strip_x" in body or re.search(
        r"pane_segmented_layout\([^;]*r->mode_seg", body, re.S
    ), "the splat mode toggle is not laid out from measured labels"
    intern = (CPP / "agent_ui_tabsplat_intern.hh").read_text(encoding="utf-8")
    for dead in ("SPLAT_MODE_W", "SPLAT_MODE_SPLIT", "SPLAT_MODEL_X", "SPLAT_LOD_X"):
        assert dead not in intern, f"{dead} is a fixed x/width for a catalog label"


def test_the_splat_strip_and_bottom_row_are_clamped_to_the_panel():
    """Two unclamped runs: the measured LOD track grew rightward from a fixed
    x with no test against the panel edge (six catalog LODs ran off the
    region), and the bottom row accumulated left-to-right past Generate —
    only `pane_ref_thumbs_paint` honoured a max_x."""
    body = _function(SPLAT_PAINT, "void splat_pane_rects_build(")
    assert "strip_max_x" in body and "panel.xmax" in body
    assert "row_max_x" in body and "btn_generate.xmin" in body


def test_the_splat_pane_scales_every_label_with_the_island():
    """`AGENT_DU` is window-width independent; `u` scales with the island. The
    empty-reference hint was the one label in any pane using AGENT_DU, so it
    changed size relative to everything around it on every resize."""
    for name, source in PANE_SOURCES.items():
        assert "AGENT_DU(" not in source, f"{name}: AGENT_DU in a pane file"


def test_the_splat_reference_hint_stays_clear_of_generate():
    body = _function(SPLAT_PAINT, "void splat_pane_paint(")
    hint = body[body.index("no image added") :]
    assert "max_x" in hint, "the empty-reference hint can print over Generate"
