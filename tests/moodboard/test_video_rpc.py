# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""``moodboard.view_video`` (``moodboard/core/video_rpc.py``): the agent
watches a board video as sampled frames. Two scene tabs with different chat
sessions, a fake ``bpy``, a synchronous main-thread stub and a fake decoder
pin the routing, every error code, the worker thread, the single reply and
the absence of absolute paths; the socket wiring is pinned at source level."""

import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "src" / "scripts"
CHAT = SCRIPTS / "mixar" / "modules" / "space_mixie_chat"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.common.utils import video_frames
from mixar.modules.moodboard import constants
from mixar.modules.moodboard.core import video_rpc

FRAME_COUNT, FPS, SIZE = 240, 24.0, (320, 180)


def _fake_decoder(calls):
    """Records the thread it ran on; the tuple contract of ``imbuf.mixar_movie_frames``."""

    def decode(filepath, indices, max_dim):
        calls.append((threading.current_thread().name, Path(filepath).name, list(indices), max_dim))
        width, height = SIZE
        scale = min(1.0, max_dim / max(width, height))
        w, h = max(1, round(width * scale)), max(1, round(height * scale))
        wanted = sorted({min(FRAME_COUNT - 1, max(0, int(i))) for i in indices})
        return FRAME_COUNT, FPS, width, height, [(i, w, h, bytes((i % 256, 0, 40, 255)) * (w * h))
                                                for i in wanted]

    return decode


def _image(name, source, filepath):
    return SimpleNamespace(name=name, source=source, filepath=filepath, size=(0, 0))


def _scene(session_id, images):
    return SimpleNamespace(
        name=f"Scene-{session_id}", mixie_session_id=session_id,
        mixie_moodboard_images=[SimpleNamespace(image=image) for image in images],
    )


@pytest.fixture
def board(tmp_path, monkeypatch):
    (tmp_path / "clip.mp4").write_bytes(b"not really mp4 bytes")
    (tmp_path / "other.mp4").write_bytes(b"not really mp4 bytes")
    (tmp_path / "still.png").write_bytes(b"\x89PNG")
    scene_a = _scene("sess-a", [
        _image("Render.mp4", "MOVIE", str(tmp_path / "clip.mp4")),
        _image("Concept.png", "FILE", str(tmp_path / "still.png")),
        _image("Lost.mp4", "MOVIE", str(tmp_path / "gone.mp4")),
    ])
    scene_b = _scene("sess-b", [_image("Other.mp4", "MOVIE", str(tmp_path / "other.mp4"))])
    fake_bpy = SimpleNamespace(data=SimpleNamespace(scenes=[scene_a, scene_b]),
                               context=SimpleNamespace(scene=scene_a))
    monkeypatch.setitem(sys.modules, "bpy", fake_bpy)
    calls = []
    video_frames.set_decoder_for_tests(_fake_decoder(calls))
    yield SimpleNamespace(root=tmp_path, calls=calls, scenes=(scene_a, scene_b), bpy=fake_bpy)
    video_frames.reset_decoder_for_tests()


def _request(params, *, main_calls=None):
    """Drive ``handle_request`` with a synchronous main-thread stub; wait for the
    worker; return the ONE reply (asserting there was exactly one)."""
    replies = []
    main_calls = main_calls if main_calls is not None else []

    def run_now(fn):
        main_calls.append(fn)
        fn()
        return True

    video_rpc.handle_request(constants.VIDEO_RPC, params, replies.append, run_on_main_thread=run_now)
    for thread in threading.enumerate():
        if thread.name == video_rpc.WORKER_THREAD_NAME:
            thread.join(10)
    assert len(replies) == 1, replies
    return replies[0]


def _assert_path_free(reply, root):
    assert str(root) not in json.dumps(reply)


def test_a_board_video_comes_back_as_frames_from_the_worker(board):
    main_calls = []
    reply = _request({"image_name": "Render.mp4", "session_id": "sess-a", "count": 2},
                     main_calls=main_calls)
    assert reply["success"] is True and reply["image_name"] == "Render.mp4"
    assert (reply["frame_count"], reply["fps"], reply["duration_s"]) == (240, 24.0, 10.0)
    assert (reply["width"], reply["height"]) == SIZE
    assert [frame["frame_index"] for frame in reply["frames"]] == [0, 239]
    assert all(frame["mime"] == "image/jpeg" and frame["image_base64"] for frame in reply["frames"])
    assert len(main_calls) == 1  # the name resolved once, on the main thread
    # The decode ran on the named daemon worker, never inside the main-thread hop.
    assert [call[0] for call in board.calls] == [video_rpc.WORKER_THREAD_NAME] * 2
    assert board.calls[-1][1:] == ("clip.mp4", [0, 239], 768)
    _assert_path_free(reply, board.root)


def test_the_range_and_size_params_reach_the_sampler(board):
    reply = _request({"image_name": "Render.mp4", "session_id": "sess-a", "start_s": 2, "end_s": 4,
                      "count": 3, "max_dim": 128})
    assert [frame["frame_index"] for frame in reply["frames"]] == [48, 72, 96]
    assert board.calls[-1][2:] == ([48, 72, 96], 128)


def test_the_session_id_routes_to_its_own_scene_tab(board):
    other = _request({"image_name": "Other.mp4", "session_id": "sess-b", "count": 1})
    assert other["success"] and other["image_name"] == "Other.mp4"
    assert board.calls[-1][1] == "other.mp4"
    # Scene A's video is not on scene B's board.
    crossed = _request({"image_name": "Render.mp4", "session_id": "sess-b"})
    assert crossed["error"]["code"] == "not_found"
    _assert_path_free(crossed, board.root)


def test_an_unknown_session_is_refused_and_an_empty_one_uses_the_window_scene(board):
    reply = _request({"image_name": "Render.mp4", "session_id": "sess-zzz"})
    assert reply == {"success": False, "error": {
        "code": "scene_not_found", "message": "No open scene belongs to this chat"}}
    assert board.calls == []
    fallback = _request({"image_name": "Render.mp4", "count": 1})
    assert fallback["success"] and board.calls[-1][1] == "clip.mp4"


@pytest.mark.parametrize("image_name, code, fragment", [
    ("Concept.png", "not_video", "not a video"),
    ("Nope.mp4", "not_found", "list_moodboard_images"),
    ("Lost.mp4", "source_missing", "moved or deleted"),
])
def test_the_board_lookup_refusals_carry_the_agent_facing_reason(board, image_name, code, fragment):
    reply = _request({"image_name": image_name, "session_id": "sess-a"})
    assert reply["success"] is False and reply["error"]["code"] == code
    assert fragment in reply["error"]["message"] and image_name in reply["error"]["message"]
    assert board.calls == []
    _assert_path_free(reply, board.root)


@pytest.mark.parametrize("params", [{}, {"image_name": ""}, {"image_name": "   "}, {"session_id": "sess-a"},
                                    "not a dict", None])
def test_a_missing_image_name_is_refused_before_any_thread_hop(board, params):
    main_calls = []
    reply = _request(params, main_calls=main_calls)
    assert reply["error"]["code"] == "invalid_params" and "image_name" in reply["error"]["message"]
    assert main_calls == [] and board.calls == []


def test_sampler_errors_keep_their_codes(board):
    bad_range = _request({"image_name": "Render.mp4", "session_id": "sess-a", "start_s": 5, "end_s": 1})
    assert bad_range["error"]["code"] == "invalid_range"

    video_frames.set_decoder_for_tests(None)
    none = _request({"image_name": "Render.mp4", "session_id": "sess-a"})
    assert none["error"]["code"] == "video_decoder_unavailable" and "update Mixar" in none["error"]["message"]

    def broken(filepath, indices, max_dim):
        raise OSError(5, "io", filepath)

    video_frames.set_decoder_for_tests(broken)
    unreadable = _request({"image_name": "Render.mp4", "session_id": "sess-a"})
    assert unreadable["error"]["code"] == "unreadable_video"
    _assert_path_free(unreadable, board.root)


def test_unexpected_failures_are_internal_errors_without_detail(board, monkeypatch, capsys):
    def explode(path, **kwargs):
        raise TypeError(f"boom {path}")

    monkeypatch.setattr(video_rpc, "sample_frames", explode)
    reply = _request({"image_name": "Render.mp4", "session_id": "sess-a"})
    assert reply == {"success": False, "error": {
        "code": "internal_error", "message": "The local video operation failed"}}
    _assert_path_free(reply, board.root)
    assert "boom" in capsys.readouterr().out  # the traceback stays local

    # A main-thread failure (bpy data gone) answers the same way, once.
    monkeypatch.setattr(video_rpc, "resolve_video_path", lambda scene, name: 1 / 0)
    again = _request({"image_name": "Render.mp4", "session_id": "sess-a"})
    assert again["error"]["code"] == "internal_error"


def test_a_main_thread_hop_that_cannot_be_scheduled_still_answers_once():
    replies = []
    video_rpc.handle_request(constants.VIDEO_RPC, {"image_name": "Render.mp4"}, replies.append,
                             run_on_main_thread=lambda fn: False)
    assert replies == [{"success": False, "error": {
        "code": "internal_error", "message": "The local video operation failed"}}]


def test_the_pure_helpers_cover_the_routing_rules():
    a, b = _scene("sess-a", []), _scene("sess-b", [])
    assert video_rpc.scene_for_session("sess-b", [a, b], a) is b
    assert video_rpc.scene_for_session("", [a, b], b) is b
    with pytest.raises(video_rpc.MoodboardVideoError) as info:
        video_rpc.scene_for_session("sess-c", [a, b], a)
    assert info.value.code == "scene_not_found"
    with pytest.raises(video_rpc.MoodboardVideoError) as info:
        video_rpc.scene_for_session("", [a, b], None)
    assert info.value.code == "scene_not_found"


def test_the_method_and_capability_are_wired():
    assert constants.VIDEO_RPC == "moodboard.view_video"
    assert constants.VIDEO_CAPABILITY == "moodboard_video_v1"
    chat_constants = (CHAT / "constants.py").read_text()
    assert 'MOODBOARD_VIEW_VIDEO = "moodboard.view_video"' in chat_constants
    dispatch = (CHAT / "core/socket_dispatch.py").read_text()
    assert "elif method == JSONRPCMethod.MOODBOARD_VIEW_VIDEO:" in dispatch
    assert "self._handle_moodboard_video_request(params, request_id)" in dispatch
    assert "from mixar.modules.moodboard.core.video_rpc import handle_request" in dispatch
    assert "run_on_main_thread=run_on_main_thread" in dispatch
    assert '"code": "capability_unavailable"' in dispatch
    handshake = (CHAT / "core/socket_connection.py").read_text()
    assert "VIDEO_CAPABILITY as MOODBOARD_VIDEO_CAPABILITY" in handshake
    assert "MOODBOARD_VIDEO_CAPABILITY," in handshake
