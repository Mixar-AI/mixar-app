# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Hunyuan 3D -- Operators

Operators:
- MIXIE_OT_hunyuan_load_image:      File browser to load images
- MIXIE_OT_hunyuan_remove_image:    Clear the main image reference
- MIXIE_OT_hunyuan_add_multi_view:  Add a multi-view image slot (Pro)
- MIXIE_OT_hunyuan_remove_multi_view: Remove a multi-view slot by index
- MIXIE_OT_hunyuan_generate:        Main generate operator (per-mode)
- MIXIE_OT_hunyuan_cancel:          Cancel running job (stops poll timer)
"""

import os

import bpy
from bpy.props import IntProperty, StringProperty
from bpy.types import Operator

from ...core.hunyuan_helpers import _redraw_3d_views
from mixar.modules.common.utils.mixie_space_utils import (
    get_first_selected_moodboard_image,
)
from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


# ============================================================================
# OPERATORS -- File Browser
# ============================================================================


class MIXIE_OT_hunyuan_load_image(Operator):
    """Load an image file for Hunyuan"""

    bl_idname = "mixie.hunyuan_load_image"
    bl_label = "Load Image"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(
        default="*.png;*.jpg;*.jpeg;*.webp", options={'HIDDEN'},
    )
    target: StringProperty(default="main")  # "main" or "multi_view"
    multi_view_index: IntProperty(default=-1)

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if not self.filepath or not os.path.isfile(self.filepath):
            self.report({'ERROR'}, "No valid file selected")
            return {'CANCELLED'}

        img = bpy.data.images.load(self.filepath, check_existing=True)
        img.pack()

        props = context.scene.hunyuan
        mode = props.active_mode

        if (
            self.target == "multi_view"
            and mode == 'PRO'
            and self.multi_view_index >= 0
        ):
            if self.multi_view_index < len(props.pro.multi_views):
                props.pro.multi_views[self.multi_view_index].image = img
        elif mode == 'PRO':
            entry = props.pro.uploaded_images.add()
            entry.image = img
            props.pro.use_selected_image = False
        elif mode == 'RAPID':
            props.rapid.image = img
            props.rapid.use_selected_image = False

        _redraw_3d_views()
        return {'FINISHED'}


class MIXIE_OT_hunyuan_remove_image(Operator):
    """Clear the main image reference for Hunyuan"""

    bl_idname = "mixie.hunyuan_remove_image"
    bl_label = "Remove Image"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.hunyuan
        mode = props.active_mode

        if mode == 'PRO':
            props.pro.image = None
            props.pro.uploaded_images.clear()
        elif mode == 'RAPID':
            props.rapid.image = None

        _redraw_3d_views()
        return {'FINISHED'}


class MIXIE_OT_hunyuan_remove_uploaded_image(Operator):
    """Remove an uploaded image from Pro mode by index"""

    bl_idname = "mixie.hunyuan_remove_uploaded_image"
    bl_label = "Remove Uploaded Image"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty()

    def execute(self, context):
        uploaded = context.scene.hunyuan.pro.uploaded_images
        if 0 <= self.index < len(uploaded):
            uploaded.remove(self.index)
        _redraw_3d_views()
        return {'FINISHED'}


# ============================================================================
# OPERATORS -- Multi-View Management (Pro mode)
# ============================================================================


class MIXIE_OT_hunyuan_add_multi_view(Operator):
    """Add a multi-view image slot"""

    bl_idname = "mixie.hunyuan_add_multi_view"
    bl_label = "Add View"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        context.scene.hunyuan.pro.multi_views.add()
        _redraw_3d_views()
        return {'FINISHED'}


class MIXIE_OT_hunyuan_remove_multi_view(Operator):
    """Remove a multi-view image slot"""

    bl_idname = "mixie.hunyuan_remove_multi_view"
    bl_label = "Remove View"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty()

    def execute(self, context):
        mv = context.scene.hunyuan.pro.multi_views
        if 0 <= self.index < len(mv):
            mv.remove(self.index)
        _redraw_3d_views()
        return {'FINISHED'}


# ============================================================================
# OPERATORS -- Generate
# ============================================================================


class MIXIE_OT_hunyuan_generate(Operator):
    """Generate 3D using Hunyuan"""

    bl_idname = "mixie.hunyuan_generate"
    bl_label = "Generate"
    bl_options = {'REGISTER'}

    mode_override: StringProperty(default="")

    @classmethod
    def poll(cls, context):
        return hasattr(context.scene, 'hunyuan')

    def execute(self, context):
        from mixar.modules.common.utils.image_utils import compress_image_for_upload

        props = context.scene.hunyuan
        mode = self.mode_override or props.active_mode

        # Early check: mesh-based modes require a selected mesh
        if mode in ('TOPOLOGY', 'PART', 'UV'):
            has_mesh = any(o.type == 'MESH' for o in context.selected_objects)
            if not has_mesh:
                self.report({'WARNING'}, "No mesh selected")
                return {'CANCELLED'}

        # PRO mode — generation queue
        if mode == 'PRO':
            try:
                self._submit_pro(
                    context, props.pro, compress_image_for_upload,
                )
            except Exception as e:
                self.report({'ERROR'}, str(e))
                return {'CANCELLED'}
            from mixar.modules.common.job_queue.constants import FEATURE_IMAGE_TO_3D_PRO
            from mixar.modules.common.job_queue.ui.lists.queue_uilist import mark_enqueued
            mark_enqueued(FEATURE_IMAGE_TO_3D_PRO)
            self.report({'INFO'}, "Added to queue")
            return {'FINISHED'}

        # TOPOLOGY — generation queue with per-object fan-out
        if mode == 'TOPOLOGY':
            try:
                self._submit_topology_queue(context, props.topology)
            except Exception as e:
                self.report({'ERROR'}, str(e))
                return {'CANCELLED'}
            from mixar.modules.common.job_queue.constants import FEATURE_RETOPOLOGY
            from mixar.modules.common.job_queue.ui.lists.queue_uilist import mark_enqueued
            mark_enqueued(FEATURE_RETOPOLOGY)
            self.report({'INFO'}, "Added to queue")
            return {'FINISHED'}

        # RAPID — generation queue
        if mode == 'RAPID':
            try:
                self._submit_rapid_queue(context, props.rapid, compress_image_for_upload)
            except Exception as e:
                self.report({'ERROR'}, str(e))
                return {'CANCELLED'}
            from mixar.modules.common.job_queue.constants import FEATURE_HUNYUAN_RAPID
            from mixar.modules.common.job_queue.ui.lists.queue_uilist import mark_enqueued
            mark_enqueued(FEATURE_HUNYUAN_RAPID)
            self.report({'INFO'}, "Added to queue")
            return {'FINISHED'}

        # PART — generation queue
        if mode == 'PART':
            try:
                from ...core.part_queue import enqueue_part_job
                enqueue_part_job(context=context, operator=self)
            except Exception as e:
                self.report({'ERROR'}, str(e))
                return {'CANCELLED'}
            from mixar.modules.common.job_queue.constants import FEATURE_HUNYUAN_PART
            from mixar.modules.common.job_queue.ui.lists.queue_uilist import mark_enqueued
            mark_enqueued(FEATURE_HUNYUAN_PART)
            self.report({'INFO'}, "Added to queue")
            return {'FINISHED'}

        # UV — generation queue
        if mode == 'UV':
            try:
                from ...core.uv_queue import enqueue_uv_job
                enqueue_uv_job(context=context, operator=self)
            except Exception as e:
                self.report({'ERROR'}, str(e))
                return {'CANCELLED'}
            from mixar.modules.common.job_queue.constants import FEATURE_HUNYUAN_UV
            from mixar.modules.common.job_queue.ui.lists.queue_uilist import mark_enqueued
            mark_enqueued(FEATURE_HUNYUAN_UV)
            self.report({'INFO'}, "Added to queue")
            return {'FINISHED'}

        self.report({'WARNING'}, f"Unknown mode: {mode}")
        return {'CANCELLED'}

    # ------------------------------------------------------------------ #
    # Per-mode submit helpers
    # ------------------------------------------------------------------ #

    def _submit_pro(
        self, context, pro, compress_image_for_upload,
    ):
        """Fan out a Pro generation request into the generation queue.

        - When ``use_selected_image`` is on, every selected moodboard
          image becomes its own queued job (multi-view ignored).
        - Otherwise a single job is enqueued, optionally with multi-view
          images and the uploaded reference image.
        """
        from mixar.modules.moodboard.core.image_to_3d_queue import (
            enqueue_pro_job, snapshot_shared_params,
        )

        shared = snapshot_shared_params(pro)
        use_moodboard = getattr(pro, 'use_selected_image', False)

        if use_moodboard:
            scene = context.scene
            selected = []
            if hasattr(scene, 'mixie_moodboard_images'):
                selected = [
                    item for item in scene.mixie_moodboard_images
                    if item.selected and item.image
                ]
            if not selected:
                raise ValueError("No image selected in moodboard")
            for item in selected:
                enqueue_pro_job(
                    image=item.image,
                    shared=shared,
                    label=item.image.name,
                )
            return

        # Uploaded images — batch one job per image (same as moodboard path).
        uploaded = [e for e in pro.uploaded_images if e.image]
        has_prompt = bool(shared.get("prompt"))
        has_mv = len(pro.multi_views) > 0 and any(
            mv.image for mv in pro.multi_views
        )

        mv_list = None
        if has_mv:
            mv_list = [
                (compress_image_for_upload(mv.image), "mv.png", mv.view_type)
                for mv in pro.multi_views if mv.image
            ] or None

        if len(uploaded) > 1:
            # Multiple uploaded images → one job per image (batch)
            for entry in uploaded:
                enqueue_pro_job(
                    image=entry.image,
                    shared=shared,
                    label=entry.image.name,
                )
            return

        # Single image / multi-view / prompt-only submission.
        single_img = uploaded[0].image if uploaded else None
        if not (has_prompt or single_img or has_mv):
            raise ValueError(
                "Provide at least one of: prompt, image, or multi-view images",
            )

        label = single_img.name if single_img else (shared.get("prompt") or "prompt")
        enqueue_pro_job(
            image=single_img,
            shared=shared,
            label=label,
            multi_views=mv_list,
        )

    def _submit_rapid_queue(self, context, rapid, compress_image_for_upload):
        """Validate and enqueue a Rapid generation job via FeatureQueue."""
        from ...core.rapid_queue import enqueue_rapid_job

        has_prompt = bool(rapid.prompt.strip())
        has_image = rapid.image is not None

        use_moodboard = getattr(rapid, 'use_selected_image', False)
        mb_img = None
        if use_moodboard:
            mb_img = get_first_selected_moodboard_image(context.scene)
            if not mb_img:
                raise ValueError("No image selected in moodboard")
            has_image = True
            has_prompt = False

        image_bytes = b""
        if has_image:
            if use_moodboard and mb_img:
                image_bytes = compress_image_for_upload(mb_img)
            elif rapid.image:
                image_bytes = compress_image_for_upload(rapid.image)

        enqueue_rapid_job(
            prompt=rapid.prompt.strip() if has_prompt else "",
            image_bytes=image_bytes,
            image_filename="image.png",
            result_format=rapid.result_format,
            enable_pbr=rapid.enable_pbr,
            enable_geometry=rapid.enable_geometry,
        )

    def _submit_topology_queue(self, context, topo):
        """Fan out a Topology retopology request into the generation queue.

        Each selected mesh becomes its own job (per-object fan-out, Q1).
        Files exceeding the size limit are skipped with a warning.
        """
        from mixar.modules.hunyuan.core.retopology_queue import (
            enqueue_retopology_jobs, snapshot_shared_params,
        )

        selected_meshes = [
            o for o in context.selected_objects if o.type == 'MESH'
        ]
        if not selected_meshes:
            raise ValueError("No mesh selected")

        shared = snapshot_shared_params(topo)
        enqueued = enqueue_retopology_jobs(
            context=context,
            objects=selected_meshes,
            shared=shared,
            operator=self,
        )
        if not enqueued:
            raise ValueError(
                "No objects could be enqueued (all skipped or failed export)",
            )


# ============================================================================
# OPERATORS -- Cancel
# ============================================================================


class MIXIE_OT_hunyuan_cancel(Operator):
    """Cancel the running Hunyuan job"""

    bl_idname = "mixie.hunyuan_cancel"
    bl_label = "Cancel"
    bl_options = {'REGISTER'}

    mode_override: StringProperty(default="")

    # Map queue-driven modes to their feature keys
    _QUEUE_FEATURE_KEYS = {
        'PRO': 'image_to_3d_pro',
        'TOPOLOGY': 'retopology',
        'RAPID': 'hunyuan_rapid',
        'PART': 'hunyuan_part',
        'UV': 'hunyuan_uv',
    }

    @classmethod
    def poll(cls, context):
        if not hasattr(context.scene, 'hunyuan'):
            return False
        # Check if any queue has active work
        from mixar.modules.common.job_queue import get_queue
        for feature_key in cls._QUEUE_FEATURE_KEYS.values():
            try:
                queue = get_queue(feature_key)
                if queue.has_active_work():
                    return True
            except Exception:
                pass
        return False

    def execute(self, context):
        props = context.scene.hunyuan
        mode = self.mode_override or props.active_mode

        # Cancel via FeatureQueue for all modes
        feature_key = self._QUEUE_FEATURE_KEYS.get(mode)
        if feature_key:
            from mixar.modules.common.job_queue import get_queue
            queue = get_queue(feature_key)
            queue.cancel_all()

        _redraw_3d_views()
        return {'FINISHED'}


class MIXIE_OT_hunyuan_dismiss_error(Operator):
    """Dismiss the error and return to idle"""

    bl_idname = "mixie.hunyuan_dismiss_error"
    bl_label = "Dismiss"
    bl_options = {'REGISTER'}

    mode_override: StringProperty(default="")

    @classmethod
    def poll(cls, context):
        if not hasattr(context.scene, 'hunyuan'):
            return False
        props = context.scene.hunyuan
        try:
            mode_props = getattr(props, props.active_mode.lower())
            return mode_props.job.status == 'FAILED'
        except AttributeError:
            return False

    def execute(self, context):
        props = context.scene.hunyuan
        mode = self.mode_override or props.active_mode
        try:
            mode_props = getattr(props, mode.lower())
        except AttributeError:
            logger.warning("hunyuan_dismiss_error: unknown mode '%s'", mode)
            return {'CANCELLED'}
        job = mode_props.job

        job.status = 'IDLE'
        job.error_message = ""
        job.progress = 0.0

        _redraw_3d_views()
        return {'FINISHED'}


# ============================================================================
# CLASS LIST (registered by bootstrap)
# ============================================================================

classes = (
    MIXIE_OT_hunyuan_load_image,
    MIXIE_OT_hunyuan_remove_image,
    MIXIE_OT_hunyuan_remove_uploaded_image,
    MIXIE_OT_hunyuan_add_multi_view,
    MIXIE_OT_hunyuan_remove_multi_view,
    MIXIE_OT_hunyuan_generate,
    MIXIE_OT_hunyuan_cancel,
    MIXIE_OT_hunyuan_dismiss_error,
)
