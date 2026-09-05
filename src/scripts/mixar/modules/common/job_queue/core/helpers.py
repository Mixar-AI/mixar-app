# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared helpers for concrete Job queue implementations.

Consolidates patterns duplicated across 16+ queue files:
- Scene flag listener factory
- Batch summary popup
- Image URL extraction from response dicts
- Queue-with-listener accessor

Image result transfer lives in ``image_results.py``.
"""

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


