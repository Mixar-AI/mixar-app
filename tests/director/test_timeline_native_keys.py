# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The dock's strip is the camera's own keys, every one of them a handle.

A recorded take keys every frame the timeline plays (`core/record.py`, the
`JITTER` key type) but mints beats only at the shot's cadence. The strip once
drew beats alone; then it drew every key but let only the beats be clicked,
so most of what it showed could not be touched. Every key column is a real
key now, selected, dragged and deleted as Blender's own, and a keyframe that
carries an image is ringed.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
KEYS = (VIEW3D / "view3d_director_timeline_keys.cc").read_text(encoding="utf-8")
DRAW = (VIEW3D / "view3d_director_timeline_draw.cc").read_text(encoding="utf-8")
STATE = (VIEW3D / "view3d_director_state.cc").read_text(encoding="utf-8")
DIRECTOR_HH = (VIEW3D / "view3d_director.hh").read_text(encoding="utf-8")
RUNTIME = (VIEW3D / "view3d_director_timeline.hh").read_text(encoding="utf-8")
INTERACTION = (VIEW3D / "view3d_director_timeline_interaction.cc").read_text(encoding="utf-8")
QA = (VIEW3D / "view3d_director_qa_targets.cc").read_text(encoding="utf-8")


def _block(source: str, start: str) -> str:
    body = source[source.index(start) :]
    return body[: body.index("\n}\n") + 3]


def _color(source: str, name: str) -> list[float]:
    """The components of a `constexpr uchar NAME[4] = {...};` literal."""
    marker = f"{name}[4] = {{"
    body = source[source.index(marker) + len(marker) :]
    return [float(part.strip().rstrip("f")) for part in body[: body.index("}")].split(",")]


def test_the_keys_are_blenders_own_keylist():
    """The object row of a Dope Sheet summary: the object's action and its
    camera data's, so lens keys count too."""
    collect = _block(KEYS, "bool director_timeline_collect_keys(")
    assert "ob_to_keylist(&ads, camera, keylist, 0, {view_start, view_end});" in collect
    assert "ED_keylist_prepare_for_direct_access(keylist);" in collect
    assert collect.count("ED_keylist_free(keylist);") == 2  # both exits


def test_every_visible_column_becomes_a_hit():
    collect = _block(KEYS, "bool director_timeline_collect_keys(")
    assert "runtime->key_hits.append(hit);" in collect
    # Selection and shape come from the keylist, not from Director.
    assert "hit.selected = (key.sel & SELECT) != 0;" in collect
    assert "hit.key_type = int(key.key_type);" in collect
    # Placed with the dock's own frame->pixel mapping.
    assert "(key.cfra - view_start) * frames_to_px" in collect
    # A take keyed every frame: rects never wider than the gap, never too
    # small to aim at.
    assert "std::max(3.0f * u, std::min(10.0f * u, frames_to_px * 0.5f))" in collect


def test_the_bar_spans_the_keylists_ends():
    """The keylist carries the nearest key past each edge of the view, so
    its ends are where the animation goes on off screen."""
    collect = _block(KEYS, "bool director_timeline_collect_keys(")
    assert "*r_first = keys[0].cfra;" in collect
    assert "*r_last = keys[key_len - 1].cfra;" in collect


def test_they_are_drawn_with_the_timelines_shader_and_sizes():
    painter = _block(KEYS, "void director_timeline_draw_keys(")
    assert "immBindBuiltinProgram(GPU_SHADER_KEYFRAME_SHAPE);" in painter
    assert "emit_key_dot(hit.x," in painter
    assert "eBezTriple_KeyframeType(hit.key_type)," in painter
    assert "hit.selected," in painter
    # The Timeline's key size (`channel_ui_data_init`).
    assert "float(U.widget_unit) * 0.5f" in painter
    assert "immBegin(GPU_PRIM_POINTS, int(runtime.key_hits.size()));" in painter


def test_a_key_is_a_green_dot_not_a_themed_diamond():
    """The dock is one camera's row on a neutral grey span: the marks carry
    Director's accent, and the theme's per-type key colours would only say
    which recorder wrote them."""
    dot = _block(KEYS, "void emit_key_dot(")
    assert "GPU_KEYFRAME_SHAPE_CIRCLE" in dot
    assert "selected ? KEY_FILL_SELECTED : KEY_FILL" in dot
    # The per-type SIZE scaling is still the Timeline's.
    assert "case BEZT_KEYTYPE_JITTER:" in dot and "size *= 0.8f;" in dot
    # Green, and the selected one brighter.
    fill = _color(KEYS, "KEY_FILL")
    selected = _color(KEYS, "KEY_FILL_SELECTED")
    assert fill[1] > fill[0] and fill[1] > fill[2]
    assert selected[1] > fill[1]
    # Nothing reads the theme's key-type slots any more.
    assert "draw_keyframe_shape(" not in KEYS


def test_the_strip_order_is_span_rings_keys():
    strip = _block(DRAW, "void draw_strip(")
    fill = strip.index("ui::draw_roundbox_4fv_ex(&runtime->strip_bounds,")
    rings = strip.index("draw_still_rings(*runtime, cy);")
    keys = strip.index("director_timeline_draw_keys(*runtime, region, cy);")
    assert fill < rings < keys
    # Keys draw with no beats at all — a first take still recording.
    assert "if (state.beats.is_empty())" not in strip


def test_the_bar_covers_every_key_and_every_beat():
    strip = _block(DRAW, "void draw_strip(")
    assert "director_timeline_collect_keys(\n      state.shot_camera, runtime, strip_y, strip_h, &first, &last);" in strip
    assert "for (const DirectorBeatView &beat : state.beats) {" in strip


def test_the_nearest_column_wins_a_shared_rect():
    body = _block(INTERACTION, "const DirectorTimelineKeyHit *key_at_event(")
    assert "std::abs(float(event->mval[0]) - hit.x)" in body
    assert "distance < best_distance" in body


def test_beats_sit_on_their_keys():
    attach = _block(DRAW, "void attach_beats(")
    assert "std::abs(float(beat.frame) - hit.frame) <= 0.5f" in attach
    assert "hit.beat = beat.index;" in attach
    assert "int beat = -1;" in RUNTIME


def test_the_view_fits_keys_as_well_as_beats():
    content = _block(DRAW, "void content_range(")
    assert "director_timeline_camera_key_range(state.shot_camera, &first, &last)" in content
    assert "content_range(state, &first, &last);" in _block(DRAW, "void reset_view(")


def test_qa_sees_every_key():
    assert 'key.surface = "director_key";' in QA
    assert 'beat.surface = "director_beat";' in QA


def test_the_camera_reaches_the_painter():
    assert "Object *shot_camera = nullptr;" in DIRECTOR_HH
    assert "r_state->shot_camera = camera;" in STATE
    assert "bool has_still = false;" in DIRECTOR_HH
    assert 'director_prop(&beat_ptr, "image")' in STATE


def test_the_file_is_built():
    cmake = (VIEW3D / "CMakeLists.txt").read_text(encoding="utf-8")
    assert "view3d_director_timeline_keys.cc" in cmake
