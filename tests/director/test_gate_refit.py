# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The camera gate refits when the camera FRAME changes shape.

The fit runs once per layout change, so the director's own zoom and pan
survive. Its key held the region size, the stage and the camera object —
and not the frame's shape. Switching the aspect from 16:9 to 9:16 reshaped
the border at the old zoom, so the portrait frame overflowed the stage (only
its upper half showed) until something that WAS keyed changed: dragging the
timeline dock resized the region, and the frame snapped into place.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = (ROOT / "src/source/blender/editors/space_view3d/view3d_director_cinema_gate.cc").read_text(
    encoding="utf-8"
)


def _block(start: str) -> str:
    body = GATE[GATE.index(start):]
    return body[: body.index("\n}\n") + 3]


def test_the_fit_key_carries_the_frames_shape():
    key = _block("bool fit_matches(")
    for field in ("render_x", "render_y", "pixel_x", "pixel_y", "sensor_fit"):
        assert f"a.{field} == b.{field}" in key, field
    # The layout inputs it already had stay in it.
    for field in ("winx", "winy", "camera"):
        assert f"a.{field} == b.{field}" in key, field
    assert "BLI_rcti_compare(&a.stage, &b.stage)" in key


def test_the_key_is_filled_from_the_scene_and_the_lens():
    fit = _block("void cinema_fit_camera_gate(")
    assert "fit.render_x = scene->r.xsch;" in fit
    assert "fit.render_y = scene->r.ysch;" in fit
    assert "fit.pixel_x = scene->r.xasp;" in fit
    assert "fit.pixel_y = scene->r.yasp;" in fit
    assert "id_cast<const Camera *>(v3d->camera->data)->sensor_fit" in fit
    assert "v3d->camera->type == OB_CAMERA" in fit
    # Filled BEFORE the comparison, or the new key never takes part.
    assert fit.index("fit.render_x = scene->r.xsch;") < fit.index("fit_matches(*record, fit)")


def test_the_camera_data_type_is_reachable():
    assert '#include "DNA_camera_types.h"' in GATE
    assert '#include "DNA_scene_types.h"' in GATE
