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


def test_generation_strips_use_the_bounded_shared_flow():
    # Actual bounds, failed-wrap stability and oversize are compiled/executed
    # in test_mixar_ui_ranges, rather than inferred from source ordering.
    assert "ui::MixarFlow" in TAB3D_PARAMS
    assert "ui::MixarFlow" in MEDIA
    assert "f->place(width, placed)" in TAB3D_PARAMS


def test_the_params_strip_never_returns_a_bottom_below_its_floor():
    body = _function(TAB3D_PARAMS, "float agent_ui_tab3d_params_draw(")
    tail = body[body.rindex("return ") :]
    assert "y_floor" in tail, (
        "the params strip must clamp its reported bottom to the floor the "
        "caller reserved for the prompt box"
    )


def test_hidden_parameters_remain_reachable_through_settings():
    for source in (TAB3D, MEDIA):
        assert "pane_settings_button(" in source
    assert "PANE_SETTINGS_W" in TAB3D
    assert "PANE_SETTINGS_W" in MEDIA
    assert "PANE_SETTINGS_W" in SPLAT_PAINT
    assert "pane_schema_param_visible(" in TAB3D_PARAMS
    media_util = (CPP / "agent_ui_tabmedia_util.cc").read_text(encoding="utf-8")
    splat = (CPP / "agent_ui_tabsplat.cc").read_text(encoding="utf-8")
    assert "pane_schema_param_visible(" in media_util
    assert "pane_schema_param_visible(" in splat
    operator = (ROOT / "src/scripts/mixar/modules/agent_bubble/ui/operators/pane_settings_ops.py").read_text()
    assert "draw_service_params(surface, self.service_key, self.model_slug)" in operator
    assert "has_params(self.service_key, self.model_slug)" in operator


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


def test_bottom_row_and_generate_use_shared_composer_geometry():
    """The compiled geometry tests exercise short/empty/scaled composer bounds."""
    bottom = _function(KIT_CC, "float pane_bottom_row_ymin(")
    generate = _function(KIT_CC, "rctf pane_generate_rect(")
    assert "composer_layout(box, u).action_bottom" in bottom
    assert "layout.action_bottom" in generate and "layout.action_top" in generate


def test_all_generation_fields_use_the_shared_reservation():
    for name, source in PANE_SOURCES.items():
        assert "pane_prompt_field_rect(" in source, name
        assert "pane_prompt_fits(" in source, name
    field = _function(KIT_CC, "rctf pane_prompt_field_rect(")
    assert "layout.field_bottom" in field and "layout.field_top" in field


# -------------------------------------------------------------------------
# Truncation


def test_truncated_text_gets_an_ellipsis():
    """A bare chop reads as a DIFFERENT string: "ReproCone" rendered as
    "ReproCon" looked like the wrong result, not a shortened name."""
    body = _function(KIT_CC, "void pane_fit_text(")
    # The compatibility buffer still only shrinks; Unicode fitting is shared.
    assert "fitted.size() < capacity" in body
    assert "mixar_fit_text(text, max_w, size)" in body
    shared = (CPP.parent / "interface/mixar/text.cc").read_text()
    assert 'const char *ellipsis = "…"' in shared
    assert "end > 0" in shared and "0xc0) == 0x80" in shared
    assert re.search(r'if \(budget < 0\.0f\)\s*\{\s*return "";', shared)


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
    assert "pane_segmented_layout(" in body
    assert "ui::MixarFlow" in body
    assert "choice(mode_items, mode_count" in body
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
