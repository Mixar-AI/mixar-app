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

import threading
import time

import bpy

from mixar.config.logging_config import get_logger
from .job import JobState
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

    def _on_queue_changed(queue: FeatureQueue) -> None:
        try:
            scene = bpy.context.scene
        except Exception:
            return
        if scene is None:
            return

        has_work = queue.has_active_work()
        was_active = bool(getattr(scene, property_name, False))

        if has_work and not was_active:
            try:
                setattr(scene, property_name, True)
            except (AttributeError, TypeError):
                pass
            if on_start is not None:
                try:
                    on_start(scene)
                except Exception:
                    pass
            return

        if not has_work and was_active:
            try:
                setattr(scene, property_name, False)
            except (AttributeError, TypeError):
                pass

            if on_finish is not None:
                try:
                    on_finish(scene)
                except Exception:
                    pass

            if batch_popup_title:
                snapshot = queue.snapshot()
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
                load_image_from_url,
            )

            downloaded = []
            for i, url in enumerate(urls):
                try:
                    if base_name:
                        # Agent-chosen name. Blender auto-dedups collisions
                        # (e.g. "dog" -> "dog.001"); index only when >1 image.
                        name = base_name if len(urls) == 1 else f"{base_name}_{i + 1}"
                    else:
                        timestamp = int(time.time())
                        name = f"{name_prefix}_{timestamp}_{i}"
                    img = load_image_from_url(url, name)
                    downloaded.append(img)
                except Exception as e:
                    logger.error("Failed to download image %d: %s", i, e)

            def _apply():
                if not downloaded:
                    on_error("Failed to download generated images")
                    return None
                from mixar.modules.common.utils.image_utils import (
                    add_image_to_moodboard,
                )

                for img in downloaded:
                    try:
                        add_image_to_moodboard(
                            img, prompt, job_handle=job_id,
                        )
                    except Exception as e:
                        logger.error(
                            "Failed to add image to moodboard: %s", e,
                        )

                names = ", ".join(img.name for img in downloaded)
                if undo_message:
                    bpy.ops.ed.undo_push(message=undo_message)
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
