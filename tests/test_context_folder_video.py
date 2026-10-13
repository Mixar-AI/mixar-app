# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""``context_folder.view_video``: frame sampling over a folder video through
a fake in-process decoder (``modules/context_folder/core/video.py``)."""

import base64
import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from mixar.modules.context_folder import constants
from mixar.modules.context_folder.core import attach, grants, indexer, rpc, video
from mixar.modules.context_folder.core.errors import ContextFolderError
from mixar.modules.context_folder.core.registry import FolderRegistry, set_registry_for_tests

ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / "src/scripts/mixar/modules/space_mixie_chat"

FRAME_COUNT, FPS, SIZE = 240, 24.0, (320, 180)


class _Folders(list):
    """Fake CollectionProperty for folder AND file rows (file rows also carry ``kind``)."""

    def add(self):
        item = SimpleNamespace(folder_id="", file_id="", name="", kind="")
        self.append(item)
        return item

    def remove(self, index):
        del self[index]


def _scene(session_id="session-1"):
    return SimpleNamespace(mixie_context_folders=_Folders(), mixie_context_files=_Folders(),
                           mixie_context_files_id="", mixie_session_id=session_id)


def _colour(index: int):
    """A solid colour that encodes the frame index."""
    return (index % 256, (index * 7) % 256, 40)


def _fake_decoder(calls, frame_count=FRAME_COUNT, fps=FPS, size=SIZE):
    def decode(filepath, indices, max_dim):
        assert Path(filepath).name == "clip.mp4"
        calls.append((list(indices), max_dim))
        width, height = size
        scale = min(1.0, max_dim / max(width, height))
        w, h = max(1, round(width * scale)), max(1, round(height * scale))
        wanted = sorted({min(frame_count - 1, max(0, int(i))) for i in indices})
        frames = [(i, w, h, bytes(_colour(i) + (255,)) * (w * h)) for i in wanted]
        return frame_count, fps, width, height, frames

    return decode


@pytest.fixture
def folder(tmp_path):
    root = tmp_path / "Shots"
    root.mkdir()
    (root / "clip.mp4").write_bytes(b"not really mp4 bytes")
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(buffer, format="PNG")
    (root / "still.png").write_bytes(buffer.getvalue())
    return root


@pytest.fixture(autouse=True)
def _isolated(tmp_path):
    set_registry_for_tests(FolderRegistry(tmp_path / "registry" / "context_folders.json"))
    grants.clear()
    indexer.clear_cache()
    calls = []
    video.set_decoder_for_tests(_fake_decoder(calls))
    yield calls
    video.reset_decoder_for_tests()
    set_registry_for_tests(None)
    grants.clear()
    indexer.clear_cache()


def _indices(result):
    return [frame["frame_index"] for frame in result["frames"]]


def _decode(frame):
    return Image.open(io.BytesIO(base64.b64decode(frame["image_base64"])))


def test_default_sample_spans_the_whole_clip_evenly(folder, _isolated):
    result = video.sample_video(folder, "clip.mp4")
    assert result["success"] and result["path"] == "clip.mp4"
    assert (result["frame_count"], result["fps"], result["duration_s"]) == (240, 24.0, 10.0)
    assert (result["width"], result["height"]) == SIZE
    assert _indices(result) == [0, 48, 96, 144, 192, 239]
    times = [frame["t_s"] for frame in result["frames"]]
    assert times == sorted(times) and times[0] == 0.0 and times[-1] == round(239 / 24, 3)
    assert all(frame["mime"] == "image/jpeg" for frame in result["frames"])
    # A tiny metadata probe of frame 0, then the real sample at the asked size.
    assert _isolated == [([0], 64), ([0, 48, 96, 144, 192, 239], constants.DEFAULT_VIDEO_FRAME_DIM)]


def test_one_frame_is_the_midpoint_and_the_count_is_capped(folder):
    assert _indices(video.sample_video(folder, "clip.mp4", count=1)) == [120]
    capped = video.sample_video(folder, "clip.mp4", count=50)
    assert len(capped["frames"]) == constants.MAX_VIDEO_FRAMES == 8


def test_a_time_range_restricts_the_sample(folder):
    result = video.sample_video(folder, "clip.mp4", start_s=2, end_s=4, count=3)
    assert _indices(result) == [48, 72, 96]
    assert all(2.0 <= frame["t_s"] <= 4.0 for frame in result["frames"])


@pytest.mark.parametrize("start_s, end_s", [(4, 2), (3, 3), (12, None), (0, 0), ("x", None)])
def test_an_empty_or_out_of_clip_range_is_refused(folder, start_s, end_s):
    with pytest.raises(ContextFolderError) as info:
        video.sample_video(folder, "clip.mp4", start_s=start_s, end_s=end_s)
    assert info.value.code == "invalid_range"


def test_only_videos_are_sampled(folder):
    with pytest.raises(ContextFolderError) as info:
        video.sample_video(folder, "still.png")
    assert info.value.code == "not_video"
    with pytest.raises(ContextFolderError) as info:
        video.sample_video(folder, "missing.mp4")
    assert info.value.code == "not_found"


def test_a_build_without_the_decoder_says_so(folder):
    video.set_decoder_for_tests(None)
    with pytest.raises(ContextFolderError) as info:
        video.sample_video(folder, "clip.mp4")
    assert info.value.code == "video_decoder_unavailable"
    assert "update Mixar" in info.value.message


def test_an_undecodable_file_is_reported_without_the_path(folder):
    def broken(filepath, indices, max_dim):
        raise ValueError("Not a decodable movie file")

    video.set_decoder_for_tests(broken)
    with pytest.raises(ContextFolderError) as info:
        video.sample_video(folder, "clip.mp4")
    assert info.value.code == "unreadable_video" and str(folder) not in info.value.message

    def empty(filepath, indices, max_dim):
        return FRAME_COUNT, FPS, *SIZE, []

    video.set_decoder_for_tests(empty)
    with pytest.raises(ContextFolderError) as info:
        video.sample_video(folder, "clip.mp4")
    assert info.value.code == "unreadable_video"


def test_frames_are_jpegs_of_the_decoded_pixels_within_max_dim(folder):
    result = video.sample_video(folder, "clip.mp4", count=4, max_dim=128)
    for frame in result["frames"]:
        image = _decode(frame)
        assert image.format == "JPEG" and image.size == (128, 72)
        expected = _colour(frame["frame_index"])
        pixel = image.convert("RGB").getpixel((64, 36))
        assert all(abs(a - b) <= 6 for a, b in zip(pixel, expected)), (pixel, expected)
    # max_dim is clamped to the cap; never above it.
    big = video.sample_video(folder, "clip.mp4", count=1, max_dim=5000)
    assert max(_decode(big["frames"][0]).size) == SIZE[0]  # never upscaled


def test_rpc_dispatch_requires_the_grant(folder):
    scene = _scene()
    attached = attach.attach_folder(scene, str(folder))
    assert attached["success"], attached
    attach.folder_context_for_send(scene, "session-1")
    folder_id = attached["folder_id"]
    ok = rpc.dispatch(constants.RPC_VIEW_VIDEO, {"session_id": "session-1", "folder_id": folder_id,
                                                 "path": "clip.mp4", "count": 2})
    assert ok["success"] and _indices(ok) == [0, 239]
    other = rpc.dispatch(constants.RPC_VIEW_VIDEO, {"session_id": "session-2", "folder_id": folder_id,
                                                    "path": "clip.mp4"})
    assert other["error"]["code"] == "folder_not_attached"
    refused = rpc.dispatch(constants.RPC_VIEW_VIDEO, {"session_id": "session-1", "folder_id": folder_id,
                                                      "path": "still.png"})
    assert refused["error"]["code"] == "not_video" and str(folder) not in str(refused)


def test_the_method_and_capability_are_wired():
    assert constants.RPC_VIEW_VIDEO == "context_folder.view_video"
    assert constants.RPC_VIEW_VIDEO in constants.RPC_METHODS
    assert constants.VIDEO_CAPABILITY == "context_folder_video_v1"
    handshake = (CHAT / "core/socket_connection.py").read_text()
    assert "CONTEXT_FOLDER_VIDEO_CAPABILITY," in handshake
    assert "VIDEO_CAPABILITY as CONTEXT_FOLDER_VIDEO_CAPABILITY" in handshake
