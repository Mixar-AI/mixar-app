# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Source-level contracts for native moodboard movie integration.

The interaction code lives in Blender C++ and cannot be invoked from the
standalone pytest process. These assertions pin the registration and event
wiring that makes the compiled behavior reachable.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPACE_MIXIE = ROOT / "src/source/blender/editors/space_mixie"
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_native_drop_accepts_movies_and_validates_the_first_frame():
    dragdrop = _read(SPACE_MIXIE / "mixie_dragdrop.cc")
    drop = _read(SPACE_MIXIE / "mixie_moodboard_ops_drop.cc")

    assert "WM_drag_has_path_file_type(drag, FILE_TYPE_MOVIE)" in dragdrop
    assert "imb_ext_movie" in drop
    assert "BKE_image_acquire_ibuf" in drop
    assert "image->source == IMA_SRC_MOVIE" in drop


def test_preview_is_compiled_and_reachable_from_video_clicks():
    cmake = _read(SPACE_MIXIE / "CMakeLists.txt")
    select = _read(SPACE_MIXIE / "mixie_moodboard_ops_select.cc")
    preview = _read(SPACE_MIXIE / "mixie_moodboard_ops_preview.cc")

    assert "mixie_moodboard_ops_preview.cc" in cmake
    assert "moodboard_open_video_preview" in select
    assert "KM_DBL_CLICK" in select
    assert "WM_window_open_temp" in preview
    assert "ED_space_image_set" in preview
    assert "IMA_ANIM_ALWAYS" in preview


def test_movie_thumbnail_has_a_play_affordance():
    draw = _read(SPACE_MIXIE / "mixie_draw_moodboard_images.cc")

    assert "image->source == IMA_SRC_MOVIE" in draw
    assert "draw_video_play_overlay" in draw
    assert "MOODBOARD_VIDEO_PLAY_RADIUS_PX" in draw


def test_file_picker_keeps_movies_linked_to_their_source():
    image_ops = _read(MOODBOARD / "ui/operators/image_ops.py")

    assert 'getattr(bpy.path, "extensions_movie", ())' in image_ops
    assert "if img.source != 'MOVIE':" in image_ops
    assert "img.pack()" in image_ops
