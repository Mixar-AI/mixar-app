# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Select job results in the viewport or moodboard when a queue item is clicked."""

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.job_queue.constants import FEATURE_IMAGEGEN
from mixar.modules.common.job_queue.core.job import JobState

logger = get_logger(__name__)

_ATTR_TO_FEATURE: dict[str, str] = {}  # Populated by queue_properties._attach_listeners

# Guard: suppress selection callback during programmatic mirror syncs
_suppress_selection = False


def on_active_index_changed(pg, _context) -> None:
    """Update callback for ``MixieFeatureQueuePG.active_index``.

    Resolves the feature key from the PG instance, looks up the
    canonical Job, and selects the result in the viewport or moodboard.
    """
    if _suppress_selection:
        return

    feature_key = _resolve_feature_key(pg)
    if not feature_key:
        return

    idx = pg.active_index
    if idx < 0 or idx >= len(pg.items):
        return

    item = pg.items[idx]
    if item.state != JobState.SUCCESS.value:
        return

    # Look up canonical Job for the full imported_object_names
    from mixar.modules.common.job_queue.core.queue_manager import get_queue

    queue = get_queue(feature_key)
    job = None
    for j in queue.snapshot():
        if j.id == item.job_id:
            job = j
            break
    if job is None:
        logger.debug("[QueueSelection] No canonical job found for %s", item.job_id)
        return
    if not job.imported_object_names:
        logger.debug("[QueueSelection] Job %s has no imported_object_names", job.id)
        return

    if feature_key == FEATURE_IMAGEGEN:
        _select_moodboard_images(job)
    else:
        _select_viewport_objects(job.imported_object_names)


def _resolve_feature_key(pg) -> str:
    """Find which feature_key owns this MixieFeatureQueuePG instance.

    Uses RNA path comparison — Blender creates new Python wrappers on each
    PointerProperty access, so ``is`` identity checks always fail.
    """
    try:
        pg_path = pg.path_from_id()
    except Exception:
        return ""
    try:
        scene = bpy.context.scene
    except Exception:
        return ""
    if not hasattr(scene, "mixie_queues"):
        return ""
    queues = scene.mixie_queues
    for attr, feat in _ATTR_TO_FEATURE.items():
        sub = getattr(queues, attr, None)
        if sub is None:
            continue
        try:
            if sub.path_from_id() == pg_path:
                return feat
        except Exception:
            continue
    return ""


def _select_viewport_objects(names_csv: str) -> None:
    """Deselect all, then select + activate the named objects."""
    names = [n.strip() for n in names_csv.split(",") if n.strip()]
    if not names:
        return

    try:
        # Deselect all currently selected objects
        for obj in bpy.context.view_layer.objects.selected:
            obj.select_set(False)
        # Select the named objects
        last = None
        for name in names:
            obj = bpy.data.objects.get(name)
            if obj and obj.name in bpy.context.view_layer.objects:
                obj.select_set(True)
                last = obj
        if last:
            bpy.context.view_layer.objects.active = last
        # Redraw 3D viewports to show the selection change
        for area in bpy.context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
    except Exception as e:
        logger.debug("[QueueSelection] Failed to select viewport objects: %s", e)


def _select_moodboard_images(job) -> None:
    """Select moodboard images that match this job's ID."""
    try:
        scene = bpy.context.scene
        if not hasattr(scene, "mixie_moodboard_images"):
            return
        # Match by job_handle (set to job.id at enqueue time)
        for item in scene.mixie_moodboard_images:
            item.selected = (
                item.mixar_job_handle == job.id
            )
        # Redraw moodboard
        for area in bpy.context.screen.areas:
            if area.type == 'MIXIE':
                area.tag_redraw()
    except Exception as e:
        logger.debug("[QueueSelection] Failed to select moodboard images: %s", e)
