# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene Reconstruction download / import helpers for SceneReconJob.

Extracted from SceneReconDownloaderMixin into standalone functions to
keep ``scene_recon_queue.py`` under 500 lines.
"""

import threading
from typing import Optional, Tuple

import bpy

from mixar.config.logging_config import get_logger
from .scene_recon_constants import MAX_CONCURRENT_DOWNLOADS

logger = get_logger(__name__)


def try_download_next(job) -> None:
    """Start downloads for all pending objects up to the concurrency limit."""
    while job._active_downloads < MAX_CONCURRENT_DOWNLOADS and job._pending_objects:
        next_id = min(job._pending_objects.keys())
        obj_data = job._pending_objects.pop(next_id)
        job._active_downloads += 1
        _download_object(job, obj_data)


def _download_object(job, obj_data: dict) -> None:
    """Download a completed object's GLB in a background thread."""
    obj_index = obj_data.get("index", -1)
    model_url = obj_data.get("model_url", "")
    label = obj_data.get("label", f"object_{obj_index}")

    # Mark as downloaded to prevent re-queuing
    job._downloaded_set.add(obj_index)

    # Build pose data from object metadata
    pose_data = {
        "quaternion": obj_data.get("rotation", [1.0, 0.0, 0.0, 0.0]),
        "translation": obj_data.get("center", [0.0, 0.0, 0.0]),
        "scale": obj_data.get("scale", 1.0),
        "dimensions": obj_data.get("dimensions", [1.0, 1.0, 1.0]),
        "mesh_pose_matrix": obj_data.get("mesh_pose_matrix"),
        "bbox_pose_matrix": obj_data.get("bbox_pose_matrix"),
    }

    def download_call():
        try:
            from mixar.modules.common.api.services.scene_recon_service import (
                get_scene_recon_service,
            )

            service = get_scene_recon_service()
            glb_bytes = service.download_glb_from_url(model_url)

            def handle_download():
                _handle_glb_download(job, glb_bytes, pose_data, obj_index, label)
                return None

            bpy.app.timers.register(handle_download, first_interval=0.0)

        except Exception as e:
            error_msg = str(e)

            def report_error():
                logger.error(
                    "[SceneRecon] GLB download failed for object %s: %s",
                    obj_index, error_msg,
                )
                job._active_downloads -= 1
                job._downloaded_glbs[obj_index] = None
                job._failed_objects.append((obj_index, label, error_msg))
                if job._on_download_failed:
                    try:
                        job._on_download_failed(obj_index, label, error_msg)
                    except Exception as cb_e:
                        logger.error("[SceneRecon] Download failed callback: %s", cb_e)
                try_import_next(job)
                try_download_next(job)
                return None

            bpy.app.timers.register(report_error, first_interval=0.0)

    threading.Thread(target=download_call, daemon=True).start()


def _handle_glb_download(
    job, glb_bytes: bytes, pose_data: dict, object_id: int, label: str,
) -> None:
    """Handle GLB download completion on main thread."""
    job._active_downloads -= 1

    if not glb_bytes:
        logger.error("[SceneRecon] Empty GLB data for object %s", object_id)
        job._downloaded_glbs[object_id] = None
        error_msg = "Empty GLB data"
        job._failed_objects.append((object_id, label, error_msg))
        if job._on_download_failed:
            try:
                job._on_download_failed(object_id, label, error_msg)
            except Exception as cb_e:
                logger.error("[SceneRecon] Download failed callback: %s", cb_e)
    else:
        job._downloaded_glbs[object_id] = (glb_bytes, pose_data, label)

    try_import_next(job)
    try_download_next(job)


def try_import_next(job) -> None:
    """Import downloaded objects. Order-independent when mesh_pose_matrix is present."""
    made_progress = True
    while made_progress:
        made_progress = False
        for obj_id in sorted(job._downloaded_glbs):
            entry = job._downloaded_glbs[obj_id]
            if entry is None:
                del job._downloaded_glbs[obj_id]
                if obj_id == job._next_import_id:
                    job._next_import_id += 1
                made_progress = True
                break
            glb_bytes, pose_data, label = entry
            if pose_data.get("mesh_pose_matrix") is not None:
                del job._downloaded_glbs[obj_id]
                if job._on_object_ready:
                    try:
                        before = set(o.name for o in bpy.data.objects)
                        job._on_object_ready(glb_bytes, pose_data, obj_id, label)
                        _capture_new_objects(job, before)
                    except Exception as e:
                        logger.error("[SceneRecon] Import failed for %s: %s", obj_id, e)
                made_progress = True
                break
            else:
                if obj_id == job._next_import_id:
                    del job._downloaded_glbs[obj_id]
                    if job._on_object_ready:
                        try:
                            before = set(o.name for o in bpy.data.objects)
                            job._on_object_ready(glb_bytes, pose_data, obj_id, label)
                            _capture_new_objects(job, before)
                        except Exception as e:
                            logger.error(
                                "[SceneRecon] Import failed for %s: %s", obj_id, e,
                            )
                    job._next_import_id += 1
                    made_progress = True
                    break


def _capture_new_objects(job, before: set) -> None:
    """Record names of objects created by the import callback."""
    after = set(o.name for o in bpy.data.objects)
    new_names = sorted(after - before)
    if new_names:
        job._imported_names.extend(new_names)
