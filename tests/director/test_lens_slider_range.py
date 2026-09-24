# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The lens and orthographic-scale sliders drag over a usable range.

`Camera.lens` ships a 1-5000mm soft range, so every focal length anyone
actually uses sat inside the first few pixels of the drag; `ortho_scale` runs
to 1000, so one pixel was a different shot. Director narrows the slider's
TRAVEL. Text entry still reaches each property's hard range, so nothing is
taken away.
"""

from __future__ import annotations

import re
from pathlib import Path

from mixar.modules.director.constants import (
    LENS_PRESETS_MM,
    LENS_SLIDER_MAX_MM,
    LENS_SLIDER_MIN_MM,
    ORTHO_SCALE_SLIDER_MAX,
    ORTHO_SCALE_SLIDER_MIN,
)

ROOT = Path(__file__).resolve().parents[2]
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
POPUP = (VIEW3D / "view3d_director_popup_lens.cc").read_text(encoding="utf-8")
HEADER = (VIEW3D / "view3d_director_cinema_tokens.hh").read_text(encoding="utf-8")


def _define(name: str) -> float:
    match = re.search(rf"^#define {name} (-?[0-9.]+)f?\s*$", HEADER, re.M)
    assert match is not None, name
    return float(match.group(1))


def test_the_native_tokens_mirror_the_python_constants():
    assert _define("LENS_SLIDER_MIN_MM") == LENS_SLIDER_MIN_MM
    assert _define("LENS_SLIDER_MAX_MM") == LENS_SLIDER_MAX_MM
    assert _define("ORTHO_SCALE_SLIDER_MIN") == ORTHO_SCALE_SLIDER_MIN
    assert _define("ORTHO_SCALE_SLIDER_MAX") == ORTHO_SCALE_SLIDER_MAX


def test_the_lens_travel_covers_every_preset_with_headroom():
    """A preset the slider cannot reach would leave the handle pinned to an
    end while the value sat outside it."""
    assert LENS_SLIDER_MIN_MM < min(LENS_PRESETS_MM)
    assert LENS_SLIDER_MAX_MM > max(LENS_PRESETS_MM)


def test_the_travel_is_a_fraction_of_the_stock_soft_range():
    # Blender's own is 1-5000 for the lens and runs to 1000 for ortho scale.
    assert (LENS_SLIDER_MAX_MM - LENS_SLIDER_MIN_MM) < 5000 / 10
    assert (ORTHO_SCALE_SLIDER_MAX - ORTHO_SCALE_SLIDER_MIN) < 1000 / 40


def test_the_drag_rate_is_usable_on_a_panel_width_row():
    """A slider's drag rate is its RANGE spread over the row's width. The
    Cinema rows are about 216 design px; anything much over a tenth of a unit
    per pixel is a control that cannot be aimed."""
    row_px = 216.0
    assert (ORTHO_SCALE_SLIDER_MAX - ORTHO_SCALE_SLIDER_MIN) / row_px <= 0.1
    # The lens is in millimetres, where a millimetre or so per pixel is right.
    assert (LENS_SLIDER_MAX_MM - LENS_SLIDER_MIN_MM) / row_px <= 1.5


def test_the_lens_slider_is_given_the_range_and_a_one_millimetre_step():
    body = POPUP[POPUP.index('"lens",') - 800 : POPUP.index('"lens",') + 700]
    assert "LENS_SLIDER_MIN_MM," in body
    assert "LENS_SLIDER_MAX_MM," in body
    assert "ui::button_number_slider_step_size_set(slider, 1.0f);" in body
    # A focal length nobody quotes to two places is not shown to two places.
    assert "ui::button_number_slider_precision_set(slider, 0.0f);" in body


def test_the_ortho_scale_slider_is_tuned_in_its_own_group():
    """One button used to bind `ortho_scale` OR `panorama_type` depending on
    the projection, so a numeric range had to be applied conditionally — and
    the panoramic case had nowhere to put its own rows.

    The group is now drawn unconditionally: the popup stays open and cannot
    re-lay itself, so a scale slider that existed only while the camera was
    already orthographic could never be reached by the segment that makes it
    orthographic."""
    body = POPUP[POPUP.index('director_popup_section_label(block, "Orthographic"') :]
    body = body[: body.index("director_popup_state(value")]
    assert '"ortho_scale",' in body
    assert "ORTHO_SCALE_SLIDER_MIN," in body
    assert "ORTHO_SCALE_SLIDER_MAX," in body
    assert "ui::button_number_slider_step_size_set(value, 0.05f);" in body
    assert "ui::button_number_slider_precision_set(value, 2.0f);" in body


def test_the_old_unbounded_form_is_gone():
    """`uiDefButR` with min == max falls back to the RNA soft range, which is
    exactly the range that was unusable."""
    for prop in ('"lens",', '"ortho_scale"'):
        index = POPUP.index(prop)
        window = POPUP[index : index + 400]
        assert not re.search(r"\n\s+0,\n\s+0,\n\s+0,\n", window), prop
