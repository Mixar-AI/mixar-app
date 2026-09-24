# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Warm moodboard redraws must not lock an ImBuf just to learn a tile's size.

Graph layout, hit-testing and the sRGB texture cache share one draw stamp
(session uid, depsgraph update count, last frame, requested movie frame).
These pins live in C++ draw code that pytest cannot execute.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPACE_MIXIE = ROOT / "src/source/blender/editors/space_mixie"


def _read(name: str) -> str:
    return (SPACE_MIXIE / name).read_text(encoding="utf-8")


def _function(source: str, signature: str) -> str:
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"unclosed function: {signature}")


def test_srgb_cache_returns_before_locking_a_warm_image():
    source = _read("mixie_draw_moodboard_texture_cache.cc")
    stamp = _function(source, "static bool image_draw_stamp")
    assert "session_uid == 0" in stamp
    assert "runtime == nullptr" in stamp
    assert "runtime->update_count" in stamp
    assert "lastframe" in stamp

    body = _function(source, "gpu::Texture *mixie_moodboard_srgb_texture")
    head, acquired, tail = body.partition("BKE_image_acquire_ibuf")
    assert acquired
    assert "image_draw_stamp" in head
    assert "return " in head
    assert "GPU_texture_update" in tail
    assert "ibuf->x == it->second.width" in tail


def test_image_size_hits_the_stamp_cache_before_acquire():
    source = _read("mixie_draw_moodboard_texture_cache.cc")
    body = _function(source, "bool mixie_moodboard_image_size")
    head, acquired, _tail = body.partition("BKE_image_acquire_ibuf")
    assert acquired
    assert "s_image_size_cache" in head
    assert "return true" in head
    assert "IMAGE_SIZE_CACHE_MAX" in source


def test_aspect_map_survives_the_gpu_eviction_sweep():
    source = _read("mixie_draw_moodboard_texture_cache.cc")
    frame_end = _function(source, "void mixie_moodboard_texture_cache_frame_end")
    freed = _function(source, "void mixie_moodboard_free_texture_cache")
    assert "s_image_size_cache" not in frame_end
    assert "s_srgb_tex_cache" in frame_end
    assert "s_image_size_cache.clear()" in freed


def test_graph_media_rect_reads_cached_aspect():
    body = _function(
        _read("mixie_moodboard_graph_geometry.cc"),
        "bool moodboard_graph_media_rect",
    )
    assert "mixie_moodboard_image_aspect" in body
    assert "BKE_image_acquire_ibuf" not in body


def test_layout_callers_do_not_lock_for_aspect():
    expectations = {
        "mixie_select.cc": "mixie_moodboard_image_aspect",
        "mixie_moodboard_ops_box_select.cc": "mixie_moodboard_image_aspect",
        "mixie_draw_moodboard_tools.cc": "mixie_moodboard_image_aspect",
        "mixie_attachment_geometry.cc": "mixie_moodboard_image_size",
    }
    for name, helper in expectations.items():
        text = _read(name)
        assert "BKE_image_acquire_ibuf" not in text, name
        assert helper in text, name


def test_annotation_caps_rotate_one_cached_semicircle():
    source = _read("mixie_draw_moodboard_annotations.cc")
    ribbon = _function(source, "static void draw_stroke_ribbon")
    assert "cap_unit_circle()" in ribbon
    assert "circle.cos_v" in ribbon
    assert "std::cos(angle)" not in ribbon
    assert "std::cos(angle)" in source
