# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Scene Reconstruction Downloader Mixin

Concurrent GLB download and sequential import management for SceneReconManager.
Downloads up to MAX_CONCURRENT_DOWNLOADS GLBs in parallel, imports in order.
"""

import threading

import bpy

from mixar.config.logging_config import get_logger
from ...common.api.services.scene_recon_service import get_scene_recon_service
from .scene_recon_constants import MAX_CONCURRENT_DOWNLOADS

logger = get_logger(__name__)


class SceneReconDownloaderMixin:
    """Download and import methods mixed into SceneReconManager.

    Accesses manager state via self (resolved at runtime by MRO).
    """

    def _try_download_next(self):
        """Start downloads for all pending objects up to the concurrency limit."""
        while self._active_downloads < MAX_CONCURRENT_DOWNLOADS and self._pending_objects:
            # Find the lowest-index pending object to start downloading
            next_id = min(self._pending_objects.keys())
            obj_data = self._pending_objects.pop(next_id)
            self._active_downloads += 1
            self._download_object(obj_data)

    def _download_object(self, obj_data: dict):
        """Download a completed object's GLB in a background thread."""
        obj_index = obj_data.get("index", -1)
        model_url = obj_data.get("model_url", "")
        label = obj_data.get("label", f"object_{obj_index}")

        logger.debug(
            "[SceneRecon] Downloading GLB for object %s ('%s')...", obj_index, label,
        )

        # Mark as downloaded to prevent re-queuing
        self._downloaded_objects.add(obj_index)

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
                service = get_scene_recon_service()
                glb_bytes = service.download_glb_from_url(model_url)

                def handle_download():
                    self._handle_glb_download(glb_bytes, pose_data, obj_index, label)
                    return None

                bpy.app.timers.register(handle_download, first_interval=0.0)

            except Exception as e:
                error_msg = str(e)

                def report_error():
                    logger.error(
                        "[SceneRecon] GLB download failed for object %s: %s",
                        obj_index, error_msg,
                    )
                    self._active_downloads -= 1
                    # Store None sentinel for failed download
                    self._downloaded_glbs[obj_index] = None
                    self._failed_objects.append((obj_index, label, error_msg))
                    if self._on_download_failed:
                        try:
                            self._on_download_failed(obj_index, label, error_msg)
                        except Exception as cb_e:
                            logger.error(
                                "[SceneRecon] Download failed callback error: %s", cb_e,
                            )
                    self._try_import_next()
                    self._try_download_next()
                    self._try_finish_job()
                    return None

                bpy.app.timers.register(report_error, first_interval=0.0)

        thread = threading.Thread(target=download_call, daemon=True)
        thread.start()

    def _handle_glb_download(self, glb_bytes: bytes, pose_data: dict, object_id: int, label: str):
        """Handle GLB download completion on main thread."""
        self._active_downloads -= 1

        if not glb_bytes:
            logger.error("[SceneRecon] Empty GLB data for object %s", object_id)
            self._downloaded_glbs[object_id] = None
            error_msg = "Empty GLB data"
            self._failed_objects.append((object_id, label, error_msg))
            if self._on_download_failed:
                try:
                    self._on_download_failed(object_id, label, error_msg)
                except Exception as cb_e:
                    logger.error("[SceneRecon] Download failed callback error: %s", cb_e)
        else:
            logger.debug(
                "[SceneRecon] Downloaded object %s: %s bytes", object_id, len(glb_bytes),
            )
            self._downloaded_glbs[object_id] = (glb_bytes, pose_data, label)

        # Try importing in order and starting more downloads
        self._try_import_next()
        self._try_download_next()
        self._try_finish_job()

    def _try_import_next(self):
        """Import downloaded objects. Order-independent when mesh_pose_matrix is present."""
        made_progress = True
        while made_progress:
            made_progress = False
            for obj_id in sorted(self._downloaded_glbs):
                entry = self._downloaded_glbs[obj_id]
                if entry is None:
                    # Failed download sentinel — remove and skip
                    del self._downloaded_glbs[obj_id]
                    if obj_id == self._next_import_id:
                        self._next_import_id += 1
                    made_progress = True
                    break
                glb_bytes, pose_data, label = entry
                if pose_data.get("mesh_pose_matrix") is not None:
                    # Scene-recon path: order-independent, import immediately
                    del self._downloaded_glbs[obj_id]
                    if self._on_object_ready:
                        try:
                            self._on_object_ready(glb_bytes, pose_data, obj_id, label)
                        except Exception as e:
                            logger.error(
                                "[SceneRecon] Import failed for %s: %s", obj_id, e,
                            )
                    made_progress = True
                    break
                else:
                    # Legacy path: must import in order (Z-offset depends on sequence)
                    if obj_id == self._next_import_id:
                        del self._downloaded_glbs[obj_id]
                        if self._on_object_ready:
                            try:
                                self._on_object_ready(glb_bytes, pose_data, obj_id, label)
                            except Exception as e:
                                logger.error(
                                    "[SceneRecon] Import failed for %s: %s", obj_id, e,
                                )
                        self._next_import_id += 1
                        made_progress = True
                        break
