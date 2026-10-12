# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Selected moodboard videos attach as context FILES (never pills) and are
never detached by deselection (``moodboard/core/chat_sync_videos.py``)."""

import sys
from types import SimpleNamespace


def _modules():
    """Import lazily: a module-level import here would bind ``chat_sync`` (and
    its dedupe helper's ``bpy``) BEFORE a later-collected moodboard test swaps
    the global bpy mock, which strands ``test_chat_attachment_dedupe.py``."""
    from mixar.modules.moodboard.core import chat_sync, chat_sync_videos

    return chat_sync, chat_sync_videos


def _item(name, path, *, selected=True, movie=True, frame_id=""):
    image = SimpleNamespace(name=name, source="MOVIE" if movie else "FILE", filepath=path)
    return SimpleNamespace(image=image, selected=selected, frame_id=frame_id)


def test_selected_videos_include_frame_members_and_skip_stills_and_idle_clips(tmp_path):
    chat_sync, chat_sync_videos = _modules()
    scene = SimpleNamespace(
        mixie_moodboard_images=[
            _item("clip", str(tmp_path / "clip.mp4")),
            _item("idle", str(tmp_path / "idle.mp4"), selected=False),
            _item("framed", str(tmp_path / "framed.mp4"), selected=False, frame_id="f1"),
            _item("still", str(tmp_path / "still.png"), movie=False),
        ],
        mixie_moodboard_frames=[SimpleNamespace(selected=True, frame_id="f1")],
    )
    assert chat_sync_videos.selected_video_names(scene) == ("clip", "framed")
    # Stills stay out of the video hook and videos stay out of the pill list.
    assert chat_sync._collect_selected_image_names(scene) == ["still"]
    assert chat_sync._compute_selection_signature(scene)[2] == ("clip", "framed")


def test_attach_selected_videos_is_idempotent_and_never_detaches(tmp_path, monkeypatch):
    _, chat_sync_videos = _modules()
    for name in ("clip.mp4", "framed.mp4"):
        (tmp_path / name).write_bytes(b"x")
    calls = []

    def attach_file(scene, path, *, origin):
        calls.append((path, origin))
        return {"success": True, "already": len(calls) > 2, "name": "x", "kind": "video", "file_id": path}

    monkeypatch.setitem(sys.modules, "mixar.modules.context_folder.core.files",
                        SimpleNamespace(attach_file=attach_file))
    scene = SimpleNamespace(
        mixie_context_files=[],
        mixie_moodboard_images=[_item("clip", str(tmp_path / "clip.mp4")),
                                _item("framed", str(tmp_path / "framed.mp4")),
                                _item("gone", str(tmp_path / "gone.mp4"))],
        mixie_moodboard_frames=[],
    )
    assert chat_sync_videos.attach_selected_videos(scene) == 2
    assert [origin for _, origin in calls] == ["moodboard", "moodboard"]  # a missing file is skipped
    assert chat_sync_videos.attach_selected_videos(scene) == 0  # already attached: nothing new
    # Deselecting is not a removal path: the hook only ever attaches.
    for item in scene.mixie_moodboard_images:
        item.selected = False
    assert chat_sync_videos.attach_selected_videos(scene) == 0 and len(calls) == 4
    assert chat_sync_videos.attach_selected_videos(SimpleNamespace()) == 0  # no context_files prop: no-op
