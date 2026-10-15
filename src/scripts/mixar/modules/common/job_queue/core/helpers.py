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
    on_start=None,
    on_finish=None,
):
    """Create a queue listener that syncs a scene bool property.

    Sets ``scene.<property_name> = True`` when work starts, ``False``
    when it finishes.  Batch completion feedback is the queue-activity
    toast's job (``core/enqueue_toast.py``), not this listener's.

    Parameters
    ----------
    on_start : callable(scene) | None
        Called on the idle→active transition, *after* the flag is set.
    on_finish : callable(scene) | None
        Called for EVERY scene whose flag clears, *after* the failure (if any)
        is recorded and the flag cleared: when that scene's jobs finish while
        another scene's continue, or when the queue goes idle.
    """

    # Queue-level edge tracker. The flag lives per-scene but the queue (and this
    # listener) is shared, so a single active/idle bool drives the once-per-batch
    # on_start/on_finish hooks.
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

    # ``mixie_<x>_is_generating`` pairs with ``mixie_<x>_error``: the chat's
    # generation poll (space_mixie_chat/core/generation_poller.py) reads it
    # when the flag drops, and posted SUCCESS for a failed job while nothing
    # wrote it. Written BEFORE the flag clears, so the poll sees both at once.
    error_property = (
        property_name[: -len("_is_generating")] + "_error"
        if property_name.endswith("_is_generating")
        else ""
    )

    # Per-scene batch membership, keyed by scene NAME (never an RNA
    # reference): the ids of every job that was active for the scene while its
    # flag was up. A release reports only failures from this set, so a failure
    # released early is never re-reported against the scene's next batch.
    # Membership is not bounded by ``finished_at``: the mirror sync stamps it,
    # so it can still be 0 when this listener fires.
    batch: dict = {}

    def _record_batch_failure(scene, snapshot, job_ids) -> None:
        if not error_property or not hasattr(scene, error_property):
            return
        from .failure_info import failure_message, failure_reason

        for job in reversed(snapshot):
            if job_ids is None:
                # No recorded batch (the listener attached mid-batch): the
                # legacy scene-name scan.
                if job.scene_name and job.scene_name != scene.name:
                    continue
            elif job.id not in job_ids:
                continue
            if job.state != JobState.FAILED:
                continue
            if getattr(job, "_scene_error_reported", False):
                continue
            job._scene_error_reported = True
            reason = failure_reason(job)
            text = failure_message(job) + (f" ({reason})" if reason else "")
            try:
                setattr(scene, error_property, text)
            except (AttributeError, TypeError):
                pass
            return

    def _release(scene, snapshot) -> None:
        """Clear one scene's flag, reporting its batch's latest failure first."""
        job_ids = batch.pop(scene.name, None)
        _record_batch_failure(scene, snapshot, job_ids)
        if job_ids:
            for job in snapshot:
                if job.id in job_ids:
                    job._scene_error_reported = True
        _set_flag(scene, False)
        if on_finish is not None:
            try:
                on_finish(scene)
            except Exception:
                pass

    def _begin(scene) -> None:
        """False→True: a new batch starts with a clean error field."""
        if error_property:
            try:
                if hasattr(scene, error_property):
                    setattr(scene, error_property, "")
            except (AttributeError, TypeError):
                pass
        _set_flag(scene, True)

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
            legacy = not active_scene_names
            if legacy:
                # Compatibility only for jobs created before scene tracking.
                fallback = getattr(bpy.context, "scene", None)
                if fallback is not None:
                    targets = [fallback]
            # Match by name, never identity: PyRNA wrappers are not
            # identity-stable, so the ``bpy.context.scene`` fallback is a
            # different Python object than the matching ``bpy.data.scenes``
            # item and an ``id()`` set would exclude it.
            target_names = {scene.name for scene in targets}
            for name in target_names:
                ids = batch.setdefault(name, set())
                ids.update(
                    j.id for j in snapshot
                    if j.state in _ACTIVE_STATES
                    and (j.scene_name == name or (legacy and not j.scene_name))
                )
            # Recompute every scene, not just the currently-active targets. If
            # scene A finishes while scene B continues, A is released now
            # (failure recorded, on_finish run) instead of waiting for the
            # entire feature queue to become idle.
            for scene in scenes:
                was_set = bool(getattr(scene, property_name, False))
                if scene.name in target_names:
                    if not was_set:
                        _begin(scene)
                elif was_set:
                    _release(scene, snapshot)
            if legacy:
                # The fallback wrapper is not the bpy.data item; set it too.
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
            for scene in _iter_scenes():
                if bool(getattr(scene, property_name, False)):
                    _release(scene, snapshot)
            batch.clear()

    # Stable dedupe identity: this factory returns a NEW closure on every
    # enqueue, but all closures for the same scene property are the same logical
    # listener and must attach only once (see get_queue_with_listener).
    _on_queue_changed._mixar_listener_key = f"scene_flag:{property_name}"
    return _on_queue_changed


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


