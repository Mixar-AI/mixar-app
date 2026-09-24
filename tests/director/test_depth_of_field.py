# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Depth of field, in the slot the redundant Output row left behind.

It was the one camera control the Cinema surface could not reach at all: a
director could choose the lens, the projection and the aspect, and then had
to leave Cinema Mode entirely to decide what was sharp.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from mixar.modules.director.constants import (
    FSTOP_PRESETS,
    FSTOP_SLIDER_MAX,
    FSTOP_SLIDER_MIN,
)
from mixar.modules.director.core import dof

ROOT = Path(__file__).resolve().parents[2]
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
DIRECTOR = ROOT / "src/scripts/mixar/modules/director"
POPUP = (VIEW3D / "view3d_director_popup_dof.cc").read_text(encoding="utf-8")
LEFT = (VIEW3D / "view3d_director_cinema_left.cc").read_text(encoding="utf-8")
HEADER = (VIEW3D / "view3d_director_cinema_tokens.hh").read_text(encoding="utf-8")


# -------------------------------------------------------------------------
# The logic Blender has no property for.


class _Dof:
    def __init__(self, **kwargs):
        self.use_dof = kwargs.get("use_dof", False)
        self.focus_object = kwargs.get("focus_object", None)
        self.focus_distance = kwargs.get("focus_distance", 10.0)
        self.aperture_fstop = kwargs.get("aperture_fstop", 2.8)


def _camera(dof_settings=None):
    return SimpleNamespace(
        type='CAMERA',
        data=SimpleNamespace(dof=dof_settings if dof_settings is not None else _Dof()),
    )


def test_a_non_camera_has_no_dof():
    assert dof.camera_dof(None) is None
    assert dof.camera_dof(SimpleNamespace(type='MESH', data=None)) is None


def test_focusing_switches_depth_of_field_on():
    """A focus object that leaves the switch off does nothing visible."""
    settings = _Dof()
    camera = _camera(settings)
    target = object()
    assert dof.set_focus_object(camera, target) is True
    assert settings.focus_object is target
    assert settings.use_dof is True


def test_a_camera_is_never_its_own_focus():
    camera = _camera()
    assert dof.set_focus_object(camera, camera) is False
    assert dof.set_focus_object(camera, None) is False


def test_focusing_records_the_distance_it_focused_at(monkeypatch):
    settings = _Dof(focus_distance=999.0)
    camera = _camera(settings)
    monkeypatch.setattr(dof, "focus_distance_to", lambda _cam, _t: 4.25)
    dof.set_focus_object(camera, object())
    assert settings.focus_distance == pytest.approx(4.25)


def test_releasing_holds_the_distance_it_was_focused_at(monkeypatch):
    """Without the measurement the image jumps the moment the object is
    released, to whatever `focus_distance` last happened to hold."""
    target = object()
    settings = _Dof(use_dof=True, focus_object=target, focus_distance=999.0)
    camera = _camera(settings)
    monkeypatch.setattr(dof, "focus_distance_to", lambda _cam, _t: 7.5)
    assert dof.clear_focus_object(camera) is True
    assert settings.focus_object is None
    assert settings.focus_distance == pytest.approx(7.5)
    # And it stays on: releasing is not switching off.
    assert settings.use_dof is True


def test_releasing_nothing_reports_nothing():
    camera = _camera(_Dof(use_dof=True))
    assert dof.clear_focus_object(camera) is False


def test_an_unmeasurable_distance_leaves_the_stored_one_alone(monkeypatch):
    settings = _Dof(use_dof=True, focus_object=object(), focus_distance=3.0)
    camera = _camera(settings)
    monkeypatch.setattr(dof, "focus_distance_to", lambda _cam, _t: None)
    assert dof.clear_focus_object(camera) is True
    assert settings.focus_distance == pytest.approx(3.0)


def test_the_distance_is_measured_to_the_visual_centre(monkeypatch):
    """An origin is very often nowhere near the middle of the thing — the
    feet of a character, the world origin of an imported mesh — and focusing
    there puts the plane of focus in front of or behind the subject."""
    from mixar.modules.director.core import tracking

    # `mathutils` is a mock in this suite, so the two operations the function
    # actually performs — subtract, then read the length — are stood in for.
    class _Vec:
        def __init__(self, z):
            self.z = z

        def __sub__(self, other):
            return _Vec(self.z - other.z)

        @property
        def length(self):
            return abs(self.z)

    camera = SimpleNamespace(matrix_world=SimpleNamespace(translation=_Vec(0.0)))
    monkeypatch.setattr(
        tracking, "world_bounding_sphere", lambda _obj: (_Vec(6.0), 1.0)
    )
    assert dof.focus_distance_to(camera, object()) == pytest.approx(6.0)

    # No geometry: the origin is the only thing there is to measure to.
    monkeypatch.setattr(tracking, "world_bounding_sphere", lambda _obj: None)
    target = SimpleNamespace(matrix_world=SimpleNamespace(translation=_Vec(2.0)))
    assert dof.focus_distance_to(camera, target) == pytest.approx(2.0)


def test_a_degenerate_measurement_is_none():
    camera = SimpleNamespace(matrix_world=None)
    assert dof.focus_distance_to(camera, object()) is None


# -------------------------------------------------------------------------
# The surface.


def _define(name: str) -> float:
    match = re.search(rf"^#define {name} (-?[0-9.]+)f?\s*$", HEADER, re.M)
    assert match is not None, name
    return float(match.group(1))


def test_the_native_tokens_mirror_the_python_constants():
    assert _define("FSTOP_SLIDER_MIN") == FSTOP_SLIDER_MIN
    assert _define("FSTOP_SLIDER_MAX") == FSTOP_SLIDER_MAX
    assert dof.FSTOP_MIN == FSTOP_SLIDER_MIN
    assert dof.FSTOP_MAX == FSTOP_SLIDER_MAX


def test_the_travel_covers_every_preset():
    """A preset the slider cannot reach leaves the handle pinned to an end
    while the value sits outside it."""
    assert FSTOP_SLIDER_MIN < min(FSTOP_PRESETS)
    assert FSTOP_SLIDER_MAX > max(FSTOP_PRESETS)


def test_the_popup_presets_are_the_python_ones():
    listed = POPUP.split("const float presets[preset_count] = {", 1)[1].split("}", 1)[0]
    values = tuple(float(part.strip().rstrip("f")) for part in listed.split(","))
    assert values == FSTOP_PRESETS


def test_the_row_took_the_output_rows_slot():
    """Third row of the output card, at the same pitch as the other two."""
    assert '"Depth of Field",' in LEFT
    assert "242.0f + CINEMA_ROW_PITCH * 2.0f," in LEFT
    assert "view3d_director_dof_popup_create," in LEFT
    # And the card grew back to hold three rows: y 208 + 3 * 68 + caption.
    card = LEFT.split("const rctf card1 = cinema_design_rect(", 1)[1].split(";", 1)[0]
    height = float(card.rsplit(",", 1)[1].strip().rstrip("f)"))
    assert height >= 208.0 + 3 * 68.0 - 208.0  # the three rows fit inside it
    assert 208.0 + height <= 439.0  # ... and it still clears the card below


def test_the_popup_binds_blenders_own_properties():
    """Everything Blender already expresses as a value; no range, unit or
    default is restated."""
    for prop in ("use_dof", "focus_distance", "aperture_fstop"):
        assert f'"{prop}"' in POPUP


def test_the_popup_is_in_the_build():
    sources = (VIEW3D / "CMakeLists.txt").read_text(encoding="utf-8")
    assert "view3d_director_popup_dof.cc" in sources
    intern = (VIEW3D / "view3d_director_overlay_intern.hh").read_text(encoding="utf-8")
    assert "view3d_director_dof_popup_create" in intern


def test_the_popup_never_branches_on_what_its_own_rows_change():
    """It stays open (BLOCK_KEEP_OPEN) and a block-button popup cannot re-lay
    itself, so a row that appears only once `use_dof` is on would still be
    absent the moment after the toggle above turned it on — which is the whole
    flow the user hit: switch it on, watch the popup vanish, reopen it."""
    # `use_dof` is a toggle IN this popup, and the focus object is set and
    # cleared by rows in it, so neither may gate what gets drawn.
    assert "RNA_property_boolean_get(&dof_ptr, use_prop)" not in POPUP
    assert "if (focus == nullptr) {" not in POPUP
    # Every row, unconditionally.
    for prop in ("use_dof", "focus_distance", "aperture_fstop"):
        assert f'"{prop}"' in POPUP


def test_the_focus_caption_cannot_name_a_stale_object():
    """A label naming the focus object would keep naming the old one the
    moment Pick or Release changed it; the left column's row carries the
    live name and redraws every frame."""
    assert '"Focusing on %s"' not in POPUP
    assert 'director_popup_section_label(block, "Focus", y, width);' in POPUP


def test_the_tracked_subject_row_may_still_branch():
    """It can only change from OUTSIDE the popup — the top strip's
    eyedropper — so it cannot go stale under the pointer."""
    assert "if (tracked != nullptr && tracked != focus) {" in POPUP


# -------------------------------------------------------------------------
# One eyedropper, two purposes.


def test_the_eyedropper_serves_focus_as_well_as_tracking():
    ops = (DIRECTOR / "ui/operators/track_ops.py").read_text(encoding="utf-8")
    assert "purpose: EnumProperty(" in ops
    assert "'FOCUS'" in ops
    assert "set_focus_object(shot.camera, target)" in ops
    assert "clear_focus_object(shot.camera)" in ops
    # And the popup reaches it through the same operator, not a second modal.
    assert '"MIXAR_OT_director_pick_track_target"' in POPUP
    assert 'RNA_enum_set_identifier(C, ptr, "purpose", "FOCUS")' in POPUP


def test_focus_on_subject_is_offered_only_when_there_is_one():
    """A row that can only report "pick a subject first" is not a control."""
    assert "if (tracked != nullptr && tracked != focus) {" in POPUP
    ops = (DIRECTOR / "ui/operators/dof_ops.py").read_text(encoding="utf-8")
    subject = ops.split("if self.mode == 'CLEAR':", 1)[1]
    assert 'self.report({\'ERROR\'}, "Pick a subject with the eyedropper first")' in subject


def test_choosing_a_stop_switches_depth_of_field_on():
    """Otherwise the preset does nothing visible."""
    ops = (DIRECTOR / "ui/operators/dof_ops.py").read_text(encoding="utf-8")
    execute = ops.split("class MIXAR_OT_director_set_fstop", 1)[1]
    assert "dof.aperture_fstop = float(self.fstop)" in execute
    assert "dof.use_dof = True" in execute
