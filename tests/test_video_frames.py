# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The shared video frame sampler (``common/utils/video_frames.py``) through a
fake in-process decoder: spacing, the midpoint, clamps, time ranges, the
error codes and JPEG fidelity. Both ``context_folder.view_video`` and
``moodboard.view_video`` sit on top of it."""

import base64
import io
from pathlib import Path

import pytest
from PIL import Image

from mixar.modules.common.utils import video_frames
from mixar.modules.common.utils.video_frames import VideoFrameError, sample_frames

FRAME_COUNT, FPS, SIZE = 240, 24.0, (320, 180)


def _colour(index: int):
    """A solid colour that encodes the frame index."""
    return (index % 256, (index * 7) % 256, 40)


def fake_decoder(calls, frame_count=FRAME_COUNT, fps=FPS, size=SIZE):
    """A stand-in for ``imbuf.mixar_movie_frames`` with the same tuple contract."""

    def decode(filepath, indices, max_dim):
        calls.append((Path(filepath).name, list(indices), max_dim))
        width, height = size
        scale = min(1.0, max_dim / max(width, height))
        w, h = max(1, round(width * scale)), max(1, round(height * scale))
        wanted = sorted({min(frame_count - 1, max(0, int(i))) for i in indices})
        frames = [(i, w, h, bytes(_colour(i) + (255,)) * (w * h)) for i in wanted]
        return frame_count, fps, width, height, frames

    return decode


@pytest.fixture
def calls():
    calls = []
    video_frames.set_decoder_for_tests(fake_decoder(calls))
    yield calls
    video_frames.reset_decoder_for_tests()


def _indices(result):
    return [frame["frame_index"] for frame in result["frames"]]


def _decode(frame):
    return Image.open(io.BytesIO(base64.b64decode(frame["image_base64"])))


def test_default_sample_spans_the_whole_clip_evenly(calls):
    result = sample_frames("/anywhere/clip.mp4")
    assert set(result) == {"frame_count", "fps", "duration_s", "width", "height", "frames"}
    assert (result["frame_count"], result["fps"], result["duration_s"]) == (240, 24.0, 10.0)
    assert (result["width"], result["height"]) == SIZE
    assert _indices(result) == [0, 48, 96, 144, 192, 239]
    times = [frame["t_s"] for frame in result["frames"]]
    assert times == sorted(times) and times[0] == 0.0 and times[-1] == round(239 / 24, 3)
    assert all(frame["mime"] == "image/jpeg" for frame in result["frames"])
    # A tiny metadata probe of frame 0, then the real sample at the default size.
    assert calls == [("clip.mp4", [0], 64), ("clip.mp4", [0, 48, 96, 144, 192, 239], 768)]


def test_one_frame_is_the_midpoint_and_the_count_is_clamped(calls):
    assert _indices(sample_frames("clip.mp4", count=1)) == [120]
    assert len(sample_frames("clip.mp4", count=50)["frames"]) == 8
    assert len(sample_frames("clip.mp4", count=50, max_count=3)["frames"]) == 3
    assert len(sample_frames("clip.mp4", count=0)["frames"]) == 1
    # A non-number falls back to the default rather than failing.
    assert len(sample_frames("clip.mp4", count="six")["frames"]) == 6


def test_a_time_range_restricts_the_sample(calls):
    result = sample_frames("clip.mp4", start_s=2, end_s=4, count=3)
    assert _indices(result) == [48, 72, 96]
    assert all(2.0 <= frame["t_s"] <= 4.0 for frame in result["frames"])
    # Strings of seconds are accepted; an end past the clip clamps to it.
    assert _indices(sample_frames("clip.mp4", start_s="9", end_s=99, count=2)) == [216, 239]


@pytest.mark.parametrize("start_s, end_s", [(4, 2), (3, 3), (12, None), (0, 0), ("x", None),
                                            (None, "nan")])
def test_an_empty_or_out_of_clip_range_is_refused(calls, start_s, end_s):
    with pytest.raises(VideoFrameError) as info:
        sample_frames("clip.mp4", start_s=start_s, end_s=end_s)
    assert info.value.code == "invalid_range"


def test_a_build_without_the_decoder_says_so():
    video_frames.set_decoder_for_tests(None)
    try:
        with pytest.raises(VideoFrameError) as info:
            sample_frames("clip.mp4")
    finally:
        video_frames.reset_decoder_for_tests()
    assert info.value.code == "video_decoder_unavailable"
    assert "update Mixar" in info.value.message


@pytest.mark.parametrize("failure", [ValueError("Not a decodable movie file"),
                                     RuntimeError("ffmpeg"), OSError(2, "gone", "/secret/clip.mp4")])
def test_an_undecodable_file_is_reported_without_the_path(failure):
    def broken(filepath, indices, max_dim):
        raise failure

    video_frames.set_decoder_for_tests(broken)
    try:
        with pytest.raises(VideoFrameError) as info:
            sample_frames("/secret/clip.mp4")
    finally:
        video_frames.reset_decoder_for_tests()
    assert info.value.code == "unreadable_video" and "/secret" not in info.value.message


@pytest.mark.parametrize("meta", [(FRAME_COUNT, FPS, *SIZE, []), (0, FPS, *SIZE, []), (10, 0.0, *SIZE, [])])
def test_no_frames_or_bad_metadata_is_unreadable(meta):
    video_frames.set_decoder_for_tests(lambda filepath, indices, max_dim: meta)
    try:
        with pytest.raises(VideoFrameError) as info:
            sample_frames("clip.mp4")
    finally:
        video_frames.reset_decoder_for_tests()
    assert info.value.code == "unreadable_video"


def test_frames_are_jpegs_of_the_decoded_pixels_within_max_dim(calls):
    result = sample_frames("clip.mp4", count=4, max_dim=128)
    for frame in result["frames"]:
        image = _decode(frame)
        assert image.format == "JPEG" and image.size == (128, 72)
        expected = _colour(frame["frame_index"])
        pixel = image.convert("RGB").getpixel((64, 36))
        assert all(abs(a - b) <= 6 for a, b in zip(pixel, expected)), (pixel, expected)
    # max_dim is clamped to the cap (never above it) and frames are never upscaled.
    big = sample_frames("clip.mp4", count=1, max_dim=5000)
    assert calls[-1][2] == 1024
    assert max(_decode(big["frames"][0]).size) == SIZE[0]
    sample_frames("clip.mp4", count=1, max_dim=5000, max_frame_dim=256)
    assert calls[-1][2] == 256
    sample_frames("clip.mp4", count=1, max_dim=1)
    assert calls[-1][2] == 64


def test_the_sampler_never_imports_bpy():
    source = Path(video_frames.__file__).read_text()
    assert "import bpy" not in source and "bpy." not in source
