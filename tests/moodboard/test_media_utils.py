# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Standalone coverage for moodboard video input metadata."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = (
    Path(__file__).parents[2]
    / "src/scripts/mixar/modules/moodboard/core/media_utils.py"
)


def _load_module():
    spec = spec_from_file_location("moodboard_media_utils_under_test", MODULE_PATH)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _item(image, *, selected=True):
    return SimpleNamespace(image=image, selected=selected)


def test_describe_video_exposes_streamable_source_metadata(tmp_path):
    module = _load_module()
    source = tmp_path / "reference.mp4"
    source.write_bytes(b"video-bytes")
    image = SimpleNamespace(
        source="MOVIE",
        filepath="//reference.mp4",
        name="reference.mp4",
        size=(1920, 1080),
        frame_duration=241,
    )

    result = module.describe_moodboard_media(
        _item(image),
        path_resolver=lambda _path: str(source),
    )

    assert result["media_type"] == "VIDEO"
    assert result["resolved_filepath"] == str(source)
    assert result["filename"] == "reference.mp4"
    assert result["mime_type"] == "video/mp4"
    assert result["file_size_bytes"] == len(b"video-bytes")
    assert result["source_available"] is True
    assert (result["width"], result["height"]) == (1920, 1080)
    assert result["frame_count"] == 241


def test_missing_video_source_is_reported_without_reading_bytes(tmp_path):
    module = _load_module()
    missing = tmp_path / "missing.mov"
    image = SimpleNamespace(
        source="MOVIE",
        filepath=str(missing),
        name="missing.mov",
        size=(1280, 720),
        frame_duration=24,
    )

    result = module.describe_moodboard_media(_item(image))

    assert result["media_type"] == "VIDEO"
    assert result["source_available"] is False
    assert result["file_size_bytes"] == 0
    assert result["mime_type"] == "video/quicktime"


def test_selected_video_inputs_exclude_stills_and_unselected_movies(tmp_path):
    module = _load_module()
    source = tmp_path / "selected.webm"
    source.write_bytes(b"webm")
    selected_video = SimpleNamespace(
        source="MOVIE",
        filepath=str(source),
        name="selected.webm",
        size=(640, 360),
        frame_duration=30,
    )
    unselected_video = SimpleNamespace(
        source="MOVIE",
        filepath=str(source),
        name="unselected.webm",
        size=(640, 360),
        frame_duration=30,
    )
    still = SimpleNamespace(
        source="FILE",
        filepath=str(tmp_path / "still.png"),
        name="still.png",
        size=(256, 256),
    )
    context = SimpleNamespace(
        scene=SimpleNamespace(
            mixie_moodboard_images=[
                _item(selected_video),
                _item(unselected_video, selected=False),
                _item(still),
            ]
        )
    )

    result = module.get_selected_moodboard_video_inputs(context)

    assert result["count"] == 1
    assert result["has_selection"] is True
    assert result["all_sources_available"] is True
    assert result["videos"][0]["image_name"] == "selected.webm"


def test_still_and_video_predicates_are_mutually_exclusive():
    module = _load_module()
    movie = SimpleNamespace(source="MOVIE")
    still = SimpleNamespace(source="FILE")

    assert module.is_video_image(movie) is True
    assert module.is_still_image(movie) is False
    assert module.is_video_item(_item(still)) is False
    assert module.is_still_item(_item(still)) is True


def test_selected_media_inputs_keep_stills_and_movies_in_separate_lists(tmp_path):
    module = _load_module()
    source = tmp_path / "reference.mp4"
    source.write_bytes(b"video")
    movie = SimpleNamespace(
        source="MOVIE",
        filepath=str(source),
        name="reference.mp4",
        size=(1280, 720),
        frame_duration=48,
    )
    still = SimpleNamespace(
        source="FILE",
        filepath=str(tmp_path / "still.png"),
        name="still.png",
        size=(512, 512),
    )
    context = SimpleNamespace(
        scene=SimpleNamespace(
            mixie_moodboard_images=[_item(still), _item(movie)]
        )
    )

    result = module.get_selected_moodboard_media_inputs(context)

    assert result["count"] == 2
    assert [item["image_name"] for item in result["images"]] == ["still.png"]
    assert [item["image_name"] for item in result["videos"]] == ["reference.mp4"]
    assert result["all_video_sources_available"] is True
