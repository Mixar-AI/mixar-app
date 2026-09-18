# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Scene Reconstruction Submission Helpers

Shared utilities for submitting scene reconstruction jobs, used by
both the direct-image operator and the prompt-to-image callback.
"""

import datetime

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def on_prompt_error(scene, sidebar_tab, message):
    """Handle error during prompt-based scene generation (safe to call from background threads)."""
    logger.error("%s", message)

    def _show():
        try:
            from .generate_progress import reset_progress
            reset_progress('scene_recon')
            scene.mixie_scene_recon_is_generating = False
            if sidebar_tab:
                sidebar_tab.error_text = message
                sidebar_tab.stage_name = ""
                sidebar_tab.stage_detail = ""

            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == "MIXIE":
                        area.tag_redraw()

            def draw_error(self_inner, context):
                self_inner.layout.label(text=message)

            bpy.context.window_manager.popup_menu(
                draw_error, title="Scene Reconstruction Error", icon="ERROR"
            )
        except Exception:
            pass
        return None

    bpy.app.timers.register(_show, first_interval=0)


def submit_recon_job(scene, sidebar_tab, image_bytes,
                     generate_mesh, min_mask_pixels,
                     mesh_postprocess=True, texture_baking=False,
                     vertex_color=True,
                     save_to_library=False, asset_library_path=""):
    """
    Submit a scene reconstruction job.

    Sets up the scene collection, callbacks, and submits to the manager.
    Used by both the direct-image operator and the prompt-to-image callback.

    Returns:
        True if the job was submitted, False otherwise.
    """
    try:
        from mixar.modules.moodboard.core.scene_recon_queue import enqueue_scene_recon_job
        from mixar.modules.moodboard.core import scene_importer
    except ImportError as e:
        on_prompt_error(scene, sidebar_tab, f"Scene recon queue not available: {e}")
        return False

    job_suffix = datetime.datetime.now().strftime("%H%M%S")
    scene_importer.init_scene(
        clear_existing=False,
        camera_direction="-y",
        collection_name=f"SceneRecon_{job_suffix}",
    )

    # Bbox placeholder tracking for generate_mesh=false flow
    placeholder_map = {}  # object_id -> (blender_obj, label)

    def on_object_ready(glb_bytes, pose_data, object_id, label):
        logger.debug("Importing object %s ('%s') into scene", object_id, label)
        try:
            imported_obj = scene_importer.add_object(glb_bytes, pose_data, object_id, name=label)
            if imported_obj and save_to_library and asset_library_path:
                try:
                    from mixar.modules.moodboard.core.scene_asset_exporter import (
                        export_object_to_asset_library,
                    )
                    export_object_to_asset_library(imported_obj, label, asset_library_path)
                except Exception as e:
                    logger.error("Asset export error for '%s': %s", label, e)
        except Exception as e:
            logger.error("Failed to import object %s: %s", object_id, e)

    def on_bbox_ready(center, dimensions, rotation, scale, object_id, label,
                      bbox_pose_matrix=None):
        """Create wireframe bbox placeholder for no-mesh objects."""
        obj = scene_importer.add_bbox_placeholder(
            center, dimensions, rotation, scale, object_id, label,
            bbox_pose_matrix=bbox_pose_matrix,
        )
        if obj:
            placeholder_map[object_id] = (obj, label)

    def on_complete(total, succeeded, failed_count):
        if failed_count == 0:
            msg = f"Scene reconstruction complete! ({total} objects imported)"
        else:
            msg = (f"Scene complete: {succeeded}/{total} objects "
                   f"imported ({failed_count} failed)")
        logger.info("%s", msg)

        # Trigger asset library fill for bbox placeholders
        if placeholder_map:
            try:
                from mixar.modules.moodboard.core.scene_asset_filler import (
                    fill_placeholders_from_library,
                )

                def on_asset_filled(obj_id, asset_name):
                    logger.debug("Replaced placeholder %s with asset '%s'",
                                obj_id, asset_name)

                def on_fill_complete(filled, fill_total):
                    logger.info("Asset fill: %d/%d placeholders replaced",
                               filled, fill_total)

                fill_placeholders_from_library(
                    placeholder_map,
                    on_filled=on_asset_filled,
                    on_complete=on_fill_complete,
                )
            except ImportError:
                logger.debug("Asset filler not available, keeping bbox placeholders")

    def on_error(error_msg):
        logger.error("%s", error_msg)

        def _show():
            try:
                def draw_error(self_inner, context):
                    self_inner.layout.label(text=error_msg)

                bpy.context.window_manager.popup_menu(
                    draw_error, title="Scene Reconstruction Error", icon="ERROR"
                )
            except Exception:
                pass
            return None

        bpy.app.timers.register(_show, first_interval=0)

    def on_download_failed(index, label, error):
        logger.error("Object %s ('%s') download failed: %s", index, label, error)

    job = enqueue_scene_recon_job(
        image_bytes=image_bytes,
        generate_mesh=generate_mesh,
        min_mask_pixels=min_mask_pixels,
        mesh_postprocess=mesh_postprocess,
        texture_baking=texture_baking,
        vertex_color=vertex_color,
        on_object_ready=on_object_ready,
        on_download_failed=on_download_failed,
        on_bbox_ready=on_bbox_ready,
        on_complete=on_complete,
        on_error=on_error,
    )

    if not job:
        on_prompt_error(scene, sidebar_tab, "Failed to submit reconstruction job")
        return False

    return True
