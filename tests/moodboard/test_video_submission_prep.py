# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Video submit prep: one validator, one cached probe.

The sidebar drawer and the node graph must not disagree about what makes a
reference uploadable, and the Video Gen drawer (redrawn at the 15 fps pulse
rate while any node generates) must stop hitting the disk per selected
reference per redraw.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"

sys.path.insert(0, str(ROOT / "src/scripts"))


def _limits():
    return {
        "max_images": 9,
        "max_videos": 3,
        "max_materials": 12,
        "max_video_seconds": 15.0,
        "max_video_bytes": 10 * 1024 * 1024,
        "max_image_bytes": 5 * 1024 * 1024,
        "video_extensions": (".mp4", ".mov"),
    }


def _video(filename="clip.mp4", *, size=1024):
    return {
        "filename": filename,
        "mime_type": "video/mp4",
        "resolved_filepath": f"/tmp/{filename}",
        "file_size_bytes": size,
    }


def _image(*, filename="ref.png", image_name="ref.png"):
    return {"filename": filename, "image_name": image_name, "image": object()}


def _catalog():
    from mixar.modules.moodboard.core import video_generation_catalog

    return video_generation_catalog


def _media_utils():
    from mixar.modules.moodboard.core import media_utils

    media_utils._source_probe_cache.clear()
    return media_utils


# --------------------------------------------------------------------------- #
#  One shared video-input validator (was two diverging copies)
# --------------------------------------------------------------------------- #


def test_video_inputs_pass_through_streaming_metadata():
    inputs = _catalog().build_video_reference_inputs([_video()], _limits())
    assert inputs == [{
        "filename": "clip.mp4",
        "mime_type": "video/mp4",
        "filepath": "/tmp/clip.mp4",
        "file_size_bytes": 1024,
    }]


def test_video_inputs_reject_oversize_before_upload():
    oversized = _video(size=11 * 1024 * 1024)
    with pytest.raises(ValueError, match="too large: clip.mp4"):
        _catalog().build_video_reference_inputs([oversized], _limits())


def test_video_inputs_reject_unsupported_extension():
    with pytest.raises(ValueError, match="Unsupported video reference: clip.avi"):
        _catalog().build_video_reference_inputs([_video("clip.avi")], _limits())


# --------------------------------------------------------------------------- #
#  One shared image-input builder with the compressor injected
# --------------------------------------------------------------------------- #


def test_image_inputs_compress_and_number_in_order():
    def fake_compress(image, service):
        assert service == "video_gen"
        return b"x" * 16

    inputs = _catalog().build_image_reference_inputs(
        [_image(), _image()], _limits(), fake_compress
    )
    assert [item["filename"] for item in inputs] == [
        "reference_1.jpg",
        "reference_2.jpg",
    ]
    assert all(item["mime_type"] == "image/jpeg" for item in inputs)
    assert inputs[0]["bytes"] == b"x" * 16


def test_oversize_image_message_names_the_most_specific_label():
    def big(_image, _service):
        return b"y" * (6 * 1024 * 1024)

    with pytest.raises(ValueError, match="a.png"):
        _catalog().build_image_reference_inputs(
            [_image(filename="a.png")], _limits(), big
        )
    # A packed generated still has no filepath: its datablock name stands in…
    with pytest.raises(ValueError, match="generated_1"):
        _catalog().build_image_reference_inputs(
            [_image(filename="", image_name="generated_1")], _limits(), big
        )
    # …and only a bare dict falls back to the generic word.
    with pytest.raises(ValueError, match="reference"):
        _catalog().build_image_reference_inputs(
            [_image(filename="", image_name="")], _limits(), big
        )


# --------------------------------------------------------------------------- #
#  Source probe: one stat, short TTL for redraws, fresh for submits
# --------------------------------------------------------------------------- #


def _movie_item(filepath, name="clip.mp4"):
    image = SimpleNamespace(
        source="MOVIE", filepath=filepath, name=name,
        size=(1280, 720), frame_duration=48,
    )
    return SimpleNamespace(image=image, selected=True)


def _context_with(*items):
    return SimpleNamespace(
        scene=SimpleNamespace(mixie_moodboard_images=list(items))
    )


def test_probe_reports_directory_as_missing_source(tmp_path):
    module = _media_utils()
    description = module.describe_moodboard_media(
        _movie_item(str(tmp_path)),
        path_resolver=lambda path: path,
    )
    assert description["source_available"] is False
    assert description["file_size_bytes"] == 0


def test_fresh_describe_reflects_removal_immediately(tmp_path):
    module = _media_utils()
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"abc")
    item = _movie_item(str(source))

    first = module.describe_moodboard_media(item, path_resolver=lambda p: p)
    assert first["source_available"] is True and first["file_size_bytes"] == 3

    source.unlink()
    second = module.describe_moodboard_media(item, path_resolver=lambda p: p)
    assert second["source_available"] is False


def test_selection_helper_caches_within_the_ttl_but_submits_fresh(tmp_path):
    module = _media_utils()
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"abc")
    context = _context_with(_movie_item(str(source)))

    cached = module.get_selected_moodboard_media_inputs(context)
    assert cached["all_video_sources_available"] is True

    source.unlink()
    stale = module.get_selected_moodboard_media_inputs(context)
    assert stale["all_video_sources_available"] is True, (
        "the redraw path must reuse the probe inside the TTL"
    )

    submitted = module.get_selected_moodboard_media_inputs(context, fresh=True)
    assert submitted["all_video_sources_available"] is False, (
        "the submit path must never trust the cache"
    )


def test_expired_cache_entry_is_reprobed(tmp_path, monkeypatch):
    module = _media_utils()
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"abc")
    context = _context_with(_movie_item(str(source)))

    module.get_selected_moodboard_media_inputs(context)
    source.unlink()
    monkeypatch.setattr(module, "SOURCE_PROBE_TTL_S", 0.0)

    expired = module.get_selected_moodboard_media_inputs(context)
    assert expired["all_video_sources_available"] is False


# --------------------------------------------------------------------------- #
#  Both submit paths actually route through the shared pieces
# --------------------------------------------------------------------------- #


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_node_execution_shares_the_validator_and_drops_its_own_copy():
    execution = _read(MOODBOARD / "core/node_execution.py")

    assert "build_video_reference_inputs(videos, limits)" in execution
    assert "build_image_reference_inputs(images, limits, compress_for_service)" in execution
    # No second copy of the checks survived.
    assert "Video is too large" not in execution
    assert '"import os"' not in execution and "\nimport os\n" not in execution


def test_sidebar_operator_shares_the_validator_and_restats_fresh():
    ops = _read(MOODBOARD / "ui/operators/video_gen_ops.py")

    assert "get_selected_moodboard_media_inputs(context, fresh=True)" in ops
    assert "build_video_reference_inputs(refs[\"videos\"], limits)" in ops
    assert "build_image_reference_inputs(" in ops
    assert "Video is too large" not in ops
    assert "\nimport os\n" not in ops


def test_drawer_redraw_stays_on_the_cached_probe():
    drawer = _read(MOODBOARD / "ui/video_gen_drawer.py")

    assert "get_selected_moodboard_media_inputs(context)" in drawer
    assert "fresh=True" not in drawer
