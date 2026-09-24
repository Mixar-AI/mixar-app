# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The dock's strip shows every key the camera carries, as the Timeline does.

A recorded take keys every frame the timeline plays (`core/record.py`, the
`JITTER` key type) but mints beats only at the shot's cadence when playback
stops. The strip drew beats alone, so the Timeline showed a key per frame
while Cinema Mode showed one a second — and nothing until the take ended.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
KEYS = (VIEW3D / "view3d_director_timeline_keys.cc").read_text(encoding="utf-8")
DRAW = (VIEW3D / "view3d_director_timeline_draw.cc").read_text(encoding="utf-8")
STATE = (VIEW3D / "view3d_director_state.cc").read_text(encoding="utf-8")
DIRECTOR_HH = (VIEW3D / "view3d_director.hh").read_text(encoding="utf-8")


def _block(source: str, start: str) -> str:
    body = source[source.index(start) :]
    return body[: body.index("\n}\n") + 3]


def test_the_keys_are_blenders_own_keylist():
    """The object row of a Dope Sheet summary: the object's action and its
    camera data's, so lens keys count too."""
    painter = _block(KEYS, "void director_timeline_draw_native_keys(")
    assert "ob_to_keylist(&ads, camera, keylist, 0, {view_start, view_end});" in painter
    assert "ED_keylist_prepare_for_direct_access(keylist);" in painter
    assert painter.count("ED_keylist_free(keylist);") == 2  # both exits


def test_they_are_drawn_with_the_timelines_shader_and_sizes():
    painter = _block(KEYS, "void director_timeline_draw_native_keys(")
    assert "immBindBuiltinProgram(GPU_SHADER_KEYFRAME_SHAPE);" in painter
    assert "draw_keyframe_shape(x," in painter
    # Per-key type and selection come from the keylist, not from Director.
    assert "key.key_type," in painter
    assert "(key.sel & SELECT) != 0," in painter
    # The Timeline's key size (`channel_ui_data_init`).
    assert "float(U.widget_unit) * 0.5f" in painter
    # Placed with the dock's own frame->pixel mapping.
    assert "(key.cfra - view_start) / runtime.view_span_frames * width" in painter
    assert "immBegin(GPU_PRIM_POINTS, visible);" in painter


def test_they_draw_under_the_beats_and_with_no_beats_at_all():
    strip = _block(DRAW, "void draw_strip(")
    # A first take still recording has no beats yet.
    empty = strip[strip.index("if (state.beats.is_empty()) {") :]
    assert "director_timeline_draw_native_keys(" in empty[: empty.index("return;")]
    # Over the strip's fill, under the beat handles.
    fill = strip.index("director_timeline_draw_round_rect(runtime->strip_bounds")
    keys = strip.index("director_timeline_draw_native_keys(", fill)
    handles = strip.index("draw_diamond(x, cy, radius, fill);")
    assert fill < keys < handles


def test_the_camera_reaches_the_painter():
    assert "Object *shot_camera = nullptr;" in DIRECTOR_HH
    assert "r_state->shot_camera = camera;" in STATE


def test_the_file_is_built():
    cmake = (VIEW3D / "CMakeLists.txt").read_text(encoding="utf-8")
    assert "view3d_director_timeline_keys.cc" in cmake
