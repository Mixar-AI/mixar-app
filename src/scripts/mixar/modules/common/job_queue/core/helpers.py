# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared helpers for concrete Job queue implementations.

Consolidates patterns duplicated across 16+ queue files:
- Scene flag listener factory
- Batch summary popup
- Image download + moodboard add
- Image URL extraction from response dicts
- Queue-with-listener accessor
"""

import os
import threading
import time

import bpy

from mixar.config.logging_config import get_logger
from .job import JobState, RUNNING_STATES
from .queue_manager import FeatureQueue, get_queue

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Queue accessor with auto-attached listener
# ---------------------------------------------------------------------------

_attached_listeners: set = set()


def _listener_key(listener):
    """Stable dedupe identity for a listener.

    Fresh-closure listeners (the scene-flag listener is rebuilt on every
    enqueue) stamp a stable ``_mixar_listener_key``; stable module functions and
    cached singletons fall back to their own object identity.
    """
    return getattr(listener, "_mixar_listener_key", listener)


def get_queue_with_listener(feature_key: str, listener) -> FeatureQueue:
    """Get or create a FeatureQueue, attaching ``listener`` exactly once.

    Dedup is per ``(feature_key, listener)`` — NOT per ``feature_key`` alone.
    Several DISTINCT listeners legitimately watch the same queue (e.g. the
    generation-library archiver AND the image-to-3D scene-flag listener both on
    ``image_to_3d_pro``); keying on the feature_key alone let whichever attached
    FIRST silently suppress the other. That regressed shipped UI: the startup
    archiver claimed the key, so enqueue's ``mixie_image_to_3d_is_generating``
    flag listener never attached and the loader/success state broke.
    """
    queue = get_queue(feature_key)
    key = (feature_key, _listener_key(listener))
    if key not in _attached_listeners:
        queue.add_listener(listener)
        _attached_listeners.add(key)
    return queue


# ---------------------------------------------------------------------------
# Scene flag listener factory
# ---------------------------------------------------------------------------


def create_scene_flag_listener(
    property_name: str,
    *,
    batch_popup_title: str = "",
    on_start=None,
    on_finish=None,
):
    """Create a queue listener that syncs a scene bool property.

    Sets ``scene.<property_name> = True`` when work starts, ``False``
    when it finishes.  If ``batch_popup_title`` is provided, fires a
    one-shot batch summary popup at the active→idle transition.

    Parameters
    ----------
    on_start : callable(scene) | None
        Called on the idle→active transition, *after* the flag is set.
    on_finish : callable(scene) | None
        Called on the active→idle transition, *after* the flag is cleared.
    """

    # Queue-level edge tracker. The flag lives per-scene but the queue (and this
    # listener) is shared, so a single active/idle bool drives the once-per-batch
    # on_start/on_finish hooks and the summary popup.
    edge = {"active": False}

    _ACTIVE_STATES = frozenset(
        RUNNING_STATES | {JobState.PENDING, JobState.PAUSED_AUTH}
    )

    def _iter_scenes():
        try:
            return list(bpy.data.scenes)
        except Exception:
            return []

    def _set_flag(scene, value: bool) -> None:
        try:
            setattr(scene, property_name, value)
        except (AttributeError, TypeError):
            pass

    def _on_queue_changed(queue: FeatureQueue) -> None:
        snapshot = queue.snapshot()

        # Scenes that submitted a job that is still active. Falls back to the
        # currently active scene only for jobs that predate scene tracking.
        active_scene_names = {
            j.scene_name for j in snapshot
            if j.scene_name and j.state in _ACTIVE_STATES
        }
        has_work = queue.has_active_work()

        if has_work:
            scenes = _iter_scenes()
            scenes_by_name = {s.name: s for s in scenes}
            targets = [scenes_by_name[n] for n in active_scene_names if n in scenes_by_name]
            if not active_scene_names:
                # Compatibility only for jobs created before scene tracking.
                fallback = getattr(bpy.context, "scene", None)
                if fallback is not None:
                    targets = [fallback]
            # Match by name, never identity: PyRNA wrappers are not
            # identity-stable, so the ``bpy.context.scene`` fallback is a
            # different Python object than the matching ``bpy.data.scenes``
            # item and an ``id()`` set would exclude it.
            target_names = {scene.name for scene in targets}
            # Recompute every scene, not just the currently-active targets. If
            # scene A finishes while scene B continues, A must be released now
            # instead of waiting for the entire feature queue to become idle.
            for scene in scenes:
                _set_flag(scene, scene.name in target_names)
            if not edge["active"]:
                edge["active"] = True
                if on_start is not None:
                    for scene in targets:
                        try:
                            on_start(scene)
                        except Exception:
                            pass
            return

        # Idle: clear the flag on EVERY scene that still carries it, so a scene
        # the user has since switched away from is never left stuck True.
        if edge["active"]:
            edge["active"] = False
            cleared = []
            for scene in _iter_scenes():
                if bool(getattr(scene, property_name, False)):
                    _set_flag(scene, False)
                    cleared.append(scene)

            if on_finish is not None:
                for scene in cleared:
                    try:
                        on_finish(scene)
                    except Exception:
                        pass

            if batch_popup_title:
                succeeded = sum(
                    1 for j in snapshot if j.state == JobState.SUCCESS
                )
                failed = sum(
                    1 for j in snapshot if j.state == JobState.FAILED
                )
                cancelled = sum(
                    1 for j in snapshot if j.state == JobState.CANCELLED
                )
                if (succeeded + failed + cancelled) > 0:
                    show_batch_summary_popup(
                        batch_popup_title, succeeded, failed, cancelled,
                    )

    # Stable dedupe identity: this factory returns a NEW closure on every
    # enqueue, but all closures for the same scene property are the same logical
    # listener and must attach only once (see get_queue_with_listener).
    _on_queue_changed._mixar_listener_key = f"scene_flag:{property_name}"
    return _on_queue_changed


# ---------------------------------------------------------------------------
# Batch summary popup
# ---------------------------------------------------------------------------


def show_batch_summary_popup(
    title: str, succeeded: int, failed: int, cancelled: int,
) -> None:
    """Schedule a one-shot popup summarising a completed batch."""

    def _draw(self_menu, context):
        layout = self_menu.layout
        layout.label(text=f"Succeeded: {succeeded}", icon='CHECKMARK')
        if failed:
            layout.label(text=f"Failed: {failed}", icon='ERROR')
        if cancelled:
            layout.label(text=f"Cancelled: {cancelled}", icon='CANCEL')

    def _popup():
        try:
            wm = bpy.context.window_manager
            wm.popup_menu(_draw, title=title, icon='INFO')
        except Exception:
            pass
        return None  # one-shot

    try:
        bpy.app.timers.register(_popup, first_interval=0.0)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Image URL extraction
# ---------------------------------------------------------------------------


def _unwrap_result_envelope(result: dict) -> dict:
    """Peel the optional ``data``/``result`` wrapping some backend responses
    carry, returning the dict that holds the generation payload fields."""
    data = result
    if "data" in data and isinstance(data["data"], dict):
        data = data["data"]
    if "result" in data and isinstance(data["result"], dict):
        data = data["result"]
    return data


def extract_image_name(result: dict) -> str:
    """Extract the backend-suggested/echoed ``image_name`` from a generation
    result dict ("" when absent). Same envelope tolerance as
    :func:`extract_image_urls` — the name sits next to ``images``."""
    return str(_unwrap_result_envelope(result).get("image_name") or "").strip()


def extract_image_urls(result: dict) -> list:
    """Extract image URLs from a generation result dict.

    Handles nested ``data.data.result`` envelopes and both list-of-dicts
    and list-of-strings image formats.
    """
    data = _unwrap_result_envelope(result)

    images = []
    for img_item in data.get("images", []):
        if isinstance(img_item, dict) and "url" in img_item:
            images.append(img_item["url"])
        elif isinstance(img_item, str):
            images.append(img_item)

    if not images:
        single_url = data.get("image_url")
        if single_url:
            images.append(single_url)

    return images


# ---------------------------------------------------------------------------
# Image download + moodboard add
# ---------------------------------------------------------------------------


def download_images_to_moodboard(
    *,
    urls: list,
    name_prefix: str,
    prompt: str,
    job_id: str,
    on_added=None,
    on_done,
    on_error,
    undo_message: str = "",
    base_name: str = "",
    scene_name: str = "",
    should_apply=None,
) -> None:
    """Download images from URLs in bg thread, add to moodboard on main thread.

    Parameters
    ----------
    urls : list[str]
        Image URLs to download.
    name_prefix : str
        Prefix for bpy.data.images names (e.g. ``"imagegen"``).
    prompt : str
        Prompt text stored with the moodboard entry.
    job_id : str
        Job ID for moodboard handle tracking.
    on_done : callable(names_str)
        Called on main thread with comma-separated image names.
    on_added : callable(names_str), optional
        Called after moodboard insertion but before the undo snapshot. Use for
        durable metadata/placement that redo must restore with the image.
        Failure rolls back the new cards and image datablocks.
    on_error : callable(error_str)
        Called on main thread if all downloads fail.
    undo_message : str, optional
        If set, pushes an undo step with this message after adding images.
    scene_name : str, optional
        Originating Blender scene. Queue jobs set this so changing the active
        scene while a download runs cannot redirect the generated images.
    should_apply : callable, optional
        Main-thread cancellation guard. When false, downloaded temp files are
        discarded without inserting images or firing completion callbacks.
    """

    def _bg_download():
        try:
            from mixar.modules.common.utils.image_utils import (
                download_image_to_tempfile,
                filename_from_url,
            )

            batch_started_at = time.time()
            downloaded_files = []
            for i, url in enumerate(urls):
                try:
                    s3_filename = filename_from_url(url)
                    if base_name:
                        # Agent-chosen or backend-suggested name. Blender auto-dedups collisions
                        # (e.g. "dog" -> "dog.001"); index only when >1 image.
                        name = base_name if len(urls) == 1 else f"{base_name}_{i + 1}"
                    elif s3_filename:
                        # No suggested name — mirror the server-side S3 file
                        # name (prompt-derived, unique per image) so outliner
                        # name, filepath and S3 key stay aligned.
                        name = os.path.splitext(s3_filename)[0]
                    else:
                        timestamp = int(time.time())
                        name = f"{name_prefix}_{timestamp}_{i}"
                    download_started_at = time.time()
                    # Keep the server-side (S3) file name on the temp file so
                    # the packed datablock's filepath shows the same name.
                    temp_path, byte_count = download_image_to_tempfile(
                        url, filename=s3_filename,
                    )
                    logger.debug(
                        "[Queue] image download completed job=%s index=%d bytes=%d duration=%.3fs",
                        job_id,
                        i,
                        byte_count,
                        time.time() - download_started_at,
                    )
                    downloaded_files.append((temp_path, name, byte_count))
                except Exception as e:
                    logger.error("Failed to download image %d: %s", i, e)

            def _apply():
                if not downloaded_files:
                    on_error("Failed to download generated images")
                    return None
                from mixar.modules.common.utils.image_utils import (
                    add_image_to_moodboard,
                    cleanup_temp_image,
                    load_image_from_file,
                )

                if should_apply is not None and not should_apply():
                    for temp_path, _name, _byte_count in downloaded_files:
                        cleanup_temp_image(temp_path)
                    return None

                loaded_images = []
                for temp_path, name, byte_count in downloaded_files:
                    load_started_at = time.time()
                    try:
                        img = load_image_from_file(
                            temp_path, name, keep_filename=True,
                        )
                        logger.debug(
                            "[Queue] image load completed job=%s image=%s bytes=%d duration=%.3fs total=%.3fs",
                            job_id,
                            img.name,
                            byte_count,
                            time.time() - load_started_at,
                            time.time() - batch_started_at,
                        )
                        loaded_images.append(img)
                    except Exception as e:
                        logger.error("Failed to load image into Blender: %s", e)
                    finally:
                        cleanup_temp_image(temp_path)

                if not loaded_images:
                    on_error("Failed to load generated images")
                    return None

                target_scene = None
                if scene_name:
                    try:
                        target_scene = bpy.data.scenes.get(scene_name)
                    except Exception:
                        target_scene = None
                    if target_scene is None:
                        for img in loaded_images:
                            try:
                                bpy.data.images.remove(img)
                            except Exception:
                                pass
                        on_error(f"Originating scene '{scene_name}' no longer exists")
                        return None
                else:
                    target_scene = getattr(bpy.context, "scene", None)
                if target_scene is None:
                    for img in loaded_images:
                        try:
                            bpy.data.images.remove(img)
                        except Exception:
                            pass
                    on_error("No Blender scene is available for generated images")
                    return None

                added_images = []
                for img in loaded_images:
                    try:
                        add_image_to_moodboard(
                            img,
                            prompt,
                            job_handle=job_id,
                            scene=target_scene,
                        )
                        added_images.append(img)
                    except Exception as e:
                        logger.error(
                            "Failed to add image to moodboard: %s", e,
                        )
                        try:
                            bpy.data.images.remove(img)
                        except Exception:
                            pass

                if not added_images:
                    on_error("Failed to add generated images to the moodboard")
                    return None

                names = ", ".join(img.name for img in added_images)
                if on_added is not None:
                    try:
                        on_added(names)
                    except Exception as e:
                        # Metadata hooks may be part of the result contract
                        # (for example, character-component provenance). Roll
                        # back the cards and their freshly loaded datablocks so
                        # a failed hook cannot leave a successful-looking,
                        # untraceable result on the moodboard.
                        try:
                            items = target_scene.mixie_moodboard_images
                            for index in range(len(items) - 1, -1, -1):
                                try:
                                    item = items[index]
                                    if (
                                        getattr(item, "mixar_job_handle", "") == job_id
                                        and getattr(item, "image", None) in added_images
                                    ):
                                        items.remove(index)
                                except Exception:
                                    pass
                            for img in added_images:
                                try:
                                    bpy.data.images.remove(img)
                                except Exception:
                                    pass
                        except Exception as rollback_error:
                            # The rollback must never mask on_error: a raise
                            # here would otherwise strand the job in
                            # RUNNING_DOWNLOAD and leak the loaded datablocks.
                            logger.error(
                                "Moodboard rollback failed for job %s: %s",
                                job_id, rollback_error,
                            )
                        on_error(f"Could not finalize generated images: {e}")
                        return None
                if undo_message:
                    bpy.ops.ed.undo_push(message=undo_message)
                logger.debug(
                    "[Queue] image moodboard update completed job=%s count=%d total=%.3fs",
                    job_id,
                    len(added_images),
                    time.time() - batch_started_at,
                )
                on_done(names)
                return None

            bpy.app.timers.register(_apply, first_interval=0.0)
        except Exception as e:
            err = f"Unexpected error during image download: {e}"
            logger.error(err)

            def _fail():
                on_error(err)
                return None

            bpy.app.timers.register(_fail, first_interval=0.0)

    threading.Thread(target=_bg_download, daemon=True).start()
