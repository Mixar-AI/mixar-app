# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""``moodboard.view_video`` (backend → client): the agent watches a board video.

The agent cannot receive a video, so it asks for a Moodboard clip — typically
one it rendered with ``render_scene_video``, or the user's own reference — as
up to eight JPEG frames, through the sampler shared with context folders
(``common/utils/video_frames.py``).

Two steps, two threads. Resolving the NAME needs ``bpy`` (the chat session's
Scene, then its ``mixie_moodboard_images`` item and the movie's file), so it
runs once on the main thread through the injected ``run_on_main_thread``.
The decode then runs on a daemon worker (``MixarMoodboardVideoRPC``) so a
long clip never stalls the UI; the decoder never touches ``bpy``. Every path
calls ``respond`` exactly once, and no reply ever carries an absolute path.

Scene routing: a scene tab is a Scene with its own chat session, so the
request's ``session_id`` picks the Scene whose ``mixie_session_id`` matches.
The window scene is the fallback ONLY for an empty ``session_id``.
"""

from __future__ import annotations

import threading
import traceback
from typing import Callable

from ...common.utils.video_frames import VideoFrameError, sample_frames
from .agent_video import MOODBOARD_ITEMS_ATTR, find_moodboard_media
from .media_utils import describe_moodboard_media

WORKER_THREAD_NAME = "MixarMoodboardVideoRPC"


class MoodboardVideoError(Exception):
    """Expected refusal with a stable public code and a path-free message."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _error(code: str, message: str) -> dict:
    return {"success": False, "error": {"code": code, "message": message}}


def _internal_error(exc: BaseException) -> dict:
    """Only the fixed message reaches the wire (an ``OSError`` names its file);
    the traceback goes to the local console for diagnosis."""
    print("[MoodboardVideo] Unexpected failure:", "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    ))
    return _error("internal_error", "The local video operation failed")


def scene_for_session(session_id: str, scenes, window_scene):
    """The Scene this chat drives, or ``MoodboardVideoError('scene_not_found')``."""
    if session_id:
        for scene in scenes:
            if str(getattr(scene, "mixie_session_id", "") or "") == session_id:
                return scene
        raise MoodboardVideoError("scene_not_found", "No open scene belongs to this chat")
    if window_scene is None:
        raise MoodboardVideoError("scene_not_found", "No open scene belongs to this chat")
    return window_scene


def _refusal_code(scene, image_name: str) -> str:
    """Which of the three ``find_moodboard_media`` refusals applies: it raises
    one ``ValueError`` for all of them, so the state is re-read for the code."""
    for item in getattr(scene, MOODBOARD_ITEMS_ATTR, ()) or ():
        image = getattr(item, "image", None)
        if image is not None and str(getattr(image, "name", "") or "") == image_name:
            if describe_moodboard_media(item).get("media_type") != "VIDEO":
                return "not_video"
            return "source_missing"
    return "not_found"


def resolve_video_path(scene, image_name: str) -> str:
    """The readable movie file behind the board item named ``image_name``.

    Raises ``MoodboardVideoError`` (``not_found`` / ``not_video`` /
    ``source_missing``) with ``find_moodboard_media``'s agent-facing message.
    """
    try:
        (media,) = find_moodboard_media(
            scene, [image_name], describe=describe_moodboard_media, want_video=True,
        )
    except ValueError as exc:
        raise MoodboardVideoError(_refusal_code(scene, image_name), str(exc)) from exc
    path = str(media.get("resolved_filepath") or "")
    if not path:
        raise MoodboardVideoError(
            "source_missing",
            f"The video '{image_name}' was moved or deleted; its file is no longer readable.",
        )
    return path


def _resolve_on_main(image_name: str, session_id: str) -> str:
    """Main thread only: ``bpy`` is imported here so the module stays
    importable (and the pure helpers testable) without Blender."""
    import bpy

    scenes = list(getattr(bpy.data, "scenes", ()) or ())
    window_scene = getattr(getattr(bpy, "context", None), "scene", None)
    scene = scene_for_session(session_id, scenes, window_scene)
    return resolve_video_path(scene, image_name)


def _sample_on_worker(path: str, image_name: str, params: dict, respond: Callable) -> None:
    def _worker():
        try:
            sample = sample_frames(
                path,
                start_s=params.get("start_s"),
                end_s=params.get("end_s"),
                count=params.get("count") or 6,
                max_dim=params.get("max_dim") or 768,
            )
        except VideoFrameError as exc:
            respond(_error(exc.code, exc.message))
            return
        except Exception as exc:  # noqa: BLE001 — must always answer, path-free
            respond(_internal_error(exc))
            return
        respond({"success": True, "image_name": image_name, **sample})

    threading.Thread(target=_worker, daemon=True, name=WORKER_THREAD_NAME).start()


def handle_request(method: str, params, respond: Callable, *, run_on_main_thread: Callable) -> None:
    """Answer one ``moodboard.view_video`` request; ``respond(result)`` runs once.

    ``run_on_main_thread(fn) -> bool`` schedules the name resolution on
    Blender's main thread (``space_mixie_chat.core.main_thread_executor``);
    ``False`` means it could not be scheduled (shutdown) and is answered here.
    """
    del method  # one method today; kept for parity with the other RPC surfaces
    params = params if isinstance(params, dict) else {}
    image_name = str(params.get("image_name") or "").strip()
    if not image_name:
        respond(_error("invalid_params", "image_name is required: a name from list_moodboard_images"))
        return
    session_id = str(params.get("session_id") or "").strip()

    def _main():
        try:
            path = _resolve_on_main(image_name, session_id)
        except MoodboardVideoError as exc:
            respond(_error(exc.code, exc.message))
            return
        except Exception as exc:  # noqa: BLE001 — must always answer, path-free
            respond(_internal_error(exc))
            return
        _sample_on_worker(path, image_name, params, respond)

    if run_on_main_thread(_main) is False:
        respond(_error("internal_error", "The local video operation failed"))
