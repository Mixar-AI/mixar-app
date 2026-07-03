# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mesh Segment Operators.

Operators for UV mesh segmentation.
"""

import os
import tempfile

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


class MIXIE_OT_mesh_segment_submit(Operator):
    """Submit the selected mesh for UV segmentation"""

    bl_idname = "mixie.mesh_segment_submit"
    bl_label = "Submit Mesh Segment"
    bl_description = "Submit the selected mesh for UV segmentation"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        # Must have active mesh object selected
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            return False
        return True

    def _get_sidebar_tab(self, context):
        """Get the sidebar tab properties if available."""
        scene = context.scene
        if hasattr(scene, 'mixie_moodboard_sidebar'):
            sidebar = scene.mixie_moodboard_sidebar
            if sidebar and hasattr(sidebar, 'tab_mesh_segment'):
                return sidebar.tab_mesh_segment
        return None

    def execute(self, context):
        scene = context.scene

        # Get selected mesh objects from viewport
        mesh_objects = [obj for obj in context.selected_objects if obj.type == 'MESH']
        if not mesh_objects:
            self.report({'ERROR'}, "No mesh object selected in viewport")
            return {'CANCELLED'}

        # Use active object as primary
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            obj = mesh_objects[0]

        # Check for UV map
        if not obj.data.uv_layers:
            self.report({'ERROR'}, "Mesh has no UV map. Please unwrap the mesh first.")
            return {'CANCELLED'}

        # Get properties from sidebar tab
        sidebar_tab = self._get_sidebar_tab(context)

        # Read prompt from sidebar tab first, fallback to scene-level description
        prompt = ""
        expected_parts = ""

        if sidebar_tab:
            prompt = getattr(sidebar_tab, 'prompt', '') or ''
            expected_parts = getattr(sidebar_tab, 'expected_parts', '') or ''
            logger.debug("Using sidebar tab - prompt: '%s', expected_parts: '%s'", prompt, expected_parts)

        # Fallback to scene-level properties
        if not prompt.strip():
            prompt = getattr(scene, 'mixie_mesh_segment_description', '') or ''
        if not expected_parts.strip():
            expected_parts = getattr(scene, 'mixie_mesh_segment_expected_parts', '') or ''

        prompt = prompt.strip()
        expected_parts = expected_parts.strip()

        if not prompt:
            self.report({'ERROR'}, "Please enter a prompt")
            return {'CANCELLED'}

        if not expected_parts:
            self.report({'ERROR'}, "Please enter expected parts")
            return {'CANCELLED'}

        # Export mesh to temporary OBJ file
        try:
            temp_dir = tempfile.gettempdir()
            obj_path = os.path.join(temp_dir, f"{obj.name}_mesh_segment.obj")

            # Select only the target object
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            context.view_layer.objects.active = obj

            # Export to OBJ
            bpy.ops.wm.obj_export(
                filepath=obj_path,
                export_selected_objects=True,
                export_uv=True,
                export_normals=True,
                export_materials=False,
            )

            logger.debug("Exported mesh to: %s", obj_path)

        except Exception as e:
            self.report({'ERROR'}, f"Failed to export mesh: {e}")
            return {'CANCELLED'}

        # Model slug from the tab's catalog selection (catalog default →
        # legacy "mesh_segment_v1" fallback, byte-identical today).
        model = "mesh_segment_v1"
        try:
            from mixar.modules.common.generation_params import (
                resolve_model_slug,
            )
            model = resolve_model_slug(
                "mesh_segment",
                getattr(sidebar_tab, 'model', '') if sidebar_tab else '',
                "mesh_segment_v1",
            )
        except Exception:
            pass

        # Submit job via FeatureQueue
        try:
            from ....mesh_segment.core.mesh_segment_queue import enqueue_mesh_segment_job

            job = enqueue_mesh_segment_job(
                mesh_object_name=obj.name,
                mesh_file_path=obj_path,
                description=prompt,  # 'prompt' from UI, API expects 'description'
                expected_parts=expected_parts,
                model=model,
            )

            if job:
                from mixar.modules.common.job_queue.constants import FEATURE_MESH_SEGMENT
                from mixar.modules.common.job_queue.ui.lists.queue_uilist import mark_enqueued
                mark_enqueued(FEATURE_MESH_SEGMENT)
                self.report({'INFO'}, "Added to queue")
                return {'FINISHED'}
            else:
                error = context.scene.mixie_mesh_segment_error
                self.report({'ERROR'}, error or "Failed to submit job")
                return {'CANCELLED'}

        except Exception as e:
            self.report({'ERROR'}, f"Failed to submit job: {e}")
            return {'CANCELLED'}


class MIXIE_OT_mesh_segment_cancel(Operator):
    """Cancel the current mesh segment job"""

    bl_idname = "mixie.mesh_segment_cancel"
    bl_label = "Cancel Mesh Segment"
    bl_description = "Cancel the current mesh segment job"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return getattr(context.scene, 'mixie_mesh_segment_is_processing', False)

    def execute(self, context):
        try:
            from mixar.modules.common.job_queue.core.queue_manager import get_queue
            from mixar.modules.common.job_queue.constants import FEATURE_MESH_SEGMENT

            get_queue(FEATURE_MESH_SEGMENT).cancel_all()

            self.report({'INFO'}, "Mesh segment job cancelled")
            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Failed to cancel job: {e}")
            return {'CANCELLED'}


classes = (
    MIXIE_OT_mesh_segment_submit,
    MIXIE_OT_mesh_segment_cancel,
)


def register():
    """Register operator classes"""
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)


def unregister():
    """Unregister operator classes"""
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)
