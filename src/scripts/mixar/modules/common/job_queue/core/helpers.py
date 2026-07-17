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


def get_queue_with_listener(feature_key: str, listener) -> FeatureQueue:
    """Get or create a FeatureQueue, attaching ``listener`` once per key."""
    queue = get_queue(feature_key)
    if feature_key not in _attached_listeners:
        queue.add_listener(listener)
        _attached_listeners.add(feature_key)
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
            scenes_by_name = {s.name: s for s in _iter_scenes()}
            targets = [scenes_by_name[n] for n in active_scene_names if n in scenes_by_name]
            if not targets:
                fallback = getattr(bpy.context, "scene", None)
                if fallback is not None:
                    targets = [fallback]
            for scene in targets:
                _set_flag(scene, True)
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


def extract_image_urls(result: dict) -> list:
    """Extract image URLs from a generation result dict.

    Handles nested ``data.data.result`` envelopes and both list-of-dicts
    and list-of-strings image formats.
    """
    data = result
    if "data" in data and isinstance(data["data"], dict):
        data = data["data"]
    if "result" in data and isinstance(data["result"], dict):
        data = data["result"]

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
    on_done,
    on_error,
    undo_message: str = "",
    base_name: str = "",
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
    on_error : callable(error_str)
        Called on main thread if all downloads fail.
    undo_message : str, optional
        If set, pushes an undo step with this message after adding images.
    """

    def _bg_download():
        try:
            from mixar.modules.common.utils.image_utils import (
                download_image_to_tempfile,
            )

            batch_started_at = time.time()
            downloaded_files = []
            for i, url in enumerate(urls):
                try:
                    if base_name:
                        # Agent-chosen name. Blender auto-dedups collisions
                        # (e.g. "dog" -> "dog.001"); index only when >1 image.
                        name = base_name if len(urls) == 1 else f"{base_name}_{i + 1}"
                    else:
                        timestamp = int(time.time())
                        name = f"{name_prefix}_{timestamp}_{i}"
                    download_started_at = time.time()
                    temp_path, byte_count = download_image_to_tempfile(url)
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
                    load_image_from_file,
                )

                loaded_images = []
                for temp_path, name, byte_count in downloaded_files:
                    load_started_at = time.time()
                    try:
                        img = load_image_from_file(temp_path, name)
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
                        try:
                            os.unlink(temp_path)
                        except OSError:
                            pass

                if not loaded_images:
                    on_error("Failed to load generated images")
                    return None

                for img in loaded_images:
                    try:
                        add_image_to_moodboard(
                            img, prompt, job_handle=job_id,
                        )
                    except Exception as e:
                        logger.error(
                            "Failed to add image to moodboard: %s", e,
                        )

                names = ", ".join(img.name for img in loaded_images)
                if undo_message:
                    bpy.ops.ed.undo_push(message=undo_message)
                logger.debug(
                    "[Queue] image moodboard update completed job=%s count=%d total=%.3fs",
                    job_id,
                    len(loaded_images),
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
