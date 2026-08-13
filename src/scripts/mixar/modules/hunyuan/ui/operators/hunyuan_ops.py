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
from bpy.props import BoolProperty, IntProperty, StringProperty
from bpy.types import Operator

from mixar.modules.common.job_queue.core.model_io import redraw_3d_views
from ...constants import HUNYUAN_RAPID_JOB_TYPE, HUNYUAN_RAPID_MODEL
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

        redraw_3d_views()
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

        redraw_3d_views()
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
        redraw_3d_views()
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
        redraw_3d_views()
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
        redraw_3d_views()
        return {'FINISHED'}


# ============================================================================
# OPERATORS -- Generate
# ============================================================================


def _has_active_view_set(context) -> bool:
    """True when the Model Gen tab holds a multi-view set ready to submit."""
    from mixar.modules.moodboard.core.turnaround_views import get_active_group

    try:
        return bool(get_active_group(context.scene))
    except Exception:
        return False


class MIXIE_OT_hunyuan_generate(Operator):
    """Generate 3D using Hunyuan"""

    bl_idname = "mixie.hunyuan_generate"
    bl_label = "Generate"
    bl_options = {'REGISTER'}

    mode_override: StringProperty(default="")

    # Direct-invocation properties (agent/chat) for PRO mode: when `prompt` or
    # `image_name` is set, the PRO path runs from these explicit params instead
    # of the sidebar/moodboard UI state.
    prompt: StringProperty(default="")
    image_name: StringProperty(default="")
    # Agent-chosen name for the imported mesh (Pro / Rapid direct paths);
    # empty falls back to the input image name, then a prompt slug.
    name: StringProperty(default="")
    # Redundant now that an active view set is signal enough (see execute) —
    # kept so an explicit agent call still reads clearly and still FAILS LOUDLY
    # when no set exists, instead of quietly generating from one image.
    multi_view: BoolProperty(default=False)
    model_version: StringProperty(default="3.0")
    enable_pbr: BoolProperty(default=False)
    face_count: IntProperty(default=0)
    polygon_type: StringProperty(default="")
    # Rapid direct-invocation params
    enable_geometry: BoolProperty(default=False)
    result_format: StringProperty(default="glb")
    # Retopology (TOPOLOGY) direct-invocation params
    object_name: StringProperty(default="")
    model: StringProperty(default="tripo")
    face_level: IntProperty(default=0)
    post_process: BoolProperty(default=True)
    # Mesh export params for direct PART/UV invocation
    export_format: StringProperty(default="GLB")
    from_chat: BoolProperty(default=False)

    @classmethod
    def poll(cls, context):
        return hasattr(context.scene, 'hunyuan')

    def execute(self, context):
        from mixar.modules.common.utils.image_utils import compress_image_for_upload
        from mixar.modules.common.utils.agent_feedback import set_agent_gen_reason

        props = context.scene.hunyuan
        mode = self.mode_override or props.active_mode

        # Early check: mesh-based modes require a selected mesh — unless the
        # agent passed an explicit object_name (direct invocation).
        if mode in ('TOPOLOGY', 'PART', 'UV'):
            if not self.object_name.strip():
                has_mesh = any(o.type == 'MESH' for o in context.selected_objects)
                if not has_mesh:
                    self.report({'WARNING'}, "No mesh selected")
                    return {'CANCELLED'}

        # PRO mode — job queue
        if mode == 'PRO':
            try:
                # Direct (agent) invocation: explicit params bypass UI state.
                # multi_view counts as a direct param — otherwise setting it
                # without an image_name would fall through to the UI path and
                # be silently ignored.
                if (self.from_chat or self.prompt.strip()
                        or self.image_name.strip() or self.multi_view):
                    self._submit_pro_direct(context)
                else:
                    self._submit_pro(
                        context, props.pro, compress_image_for_upload,
                    )
            except Exception as e:
                set_agent_gen_reason(context, str(e))
                self.report({'ERROR'}, str(e))
                return {'CANCELLED'}
            from mixar.modules.common.job_queue.constants import FEATURE_IMAGE_TO_3D_PRO
            from mixar.modules.common.job_queue.ui.lists.queue_uilist import mark_enqueued
            mark_enqueued(FEATURE_IMAGE_TO_3D_PRO)
            self.report({'INFO'}, "Added to queue")
            return {'FINISHED'}

        # TOPOLOGY — job queue with per-object fan-out
        if mode == 'TOPOLOGY':
            try:
                # Direct (agent) invocation: retopologize a named object.
                if self.object_name.strip():
                    self._submit_topology_direct(context)
                else:
                    self._submit_topology_queue(context, props.topology)
            except Exception as e:
                set_agent_gen_reason(context, str(e))
                self.report({'ERROR'}, str(e))
                return {'CANCELLED'}
            from mixar.modules.common.job_queue.constants import FEATURE_RETOPOLOGY
            from mixar.modules.common.job_queue.ui.lists.queue_uilist import mark_enqueued
            mark_enqueued(FEATURE_RETOPOLOGY)
            self.report({'INFO'}, "Added to queue")
            return {'FINISHED'}

        # RAPID — job queue
        if mode == 'RAPID':
            try:
                if self.from_chat or self.prompt.strip() or self.image_name.strip():
                    self._submit_rapid_direct(context, compress_image_for_upload)
                else:
                    self._submit_rapid_queue(context, props.rapid, compress_image_for_upload)
            except Exception as e:
                set_agent_gen_reason(context, str(e))
                self.report({'ERROR'}, str(e))
                return {'CANCELLED'}
            from mixar.modules.common.job_queue.constants import FEATURE_HUNYUAN_RAPID
            from mixar.modules.common.job_queue.ui.lists.queue_uilist import mark_enqueued
            mark_enqueued(FEATURE_HUNYUAN_RAPID)
            self.report({'INFO'}, "Added to queue")
            return {'FINISHED'}

        # PART — job queue
        if mode == 'PART':
            try:
                from ...core.part_enqueue import enqueue_part_job
                if self.object_name.strip():
                    self._submit_part_direct(context, enqueue_part_job)
                else:
                    enqueue_part_job(context=context, operator=self)
            except Exception as e:
                set_agent_gen_reason(context, str(e))
                self.report({'ERROR'}, str(e))
                return {'CANCELLED'}
            from mixar.modules.common.job_queue.constants import FEATURE_HUNYUAN_PART
            from mixar.modules.common.job_queue.ui.lists.queue_uilist import mark_enqueued
            mark_enqueued(FEATURE_HUNYUAN_PART)
            self.report({'INFO'}, "Added to queue")
            return {'FINISHED'}

        # UV — job queue
        if mode == 'UV':
            try:
                from ...core.uv_enqueue import enqueue_uv_job
                if self.object_name.strip():
                    self._submit_uv_direct(context, enqueue_uv_job)
                else:
                    enqueue_uv_job(context=context, operator=self)
            except Exception as e:
                set_agent_gen_reason(context, str(e))
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

    def _submit_pro_direct(self, context):
        """Submit a single Pro (image-to-3D) job from explicit operator params.

        Used by the agent/chat path: reads prompt/image_name/model_version/
        enable_pbr/face_count/polygon_type directly instead of props.pro.
        """
        from mixar.modules.moodboard.core.generation_enqueue import enqueue_pro_job

        image = None
        if self.image_name.strip():
            image = bpy.data.images.get(self.image_name.strip())
            if image is None:
                raise ValueError(f"Image '{self.image_name}' not found")

        prompt = self.prompt.strip() or None

        # Turnaround group: submit every detected view of this sheet as ONE
        # multi-view job, forwarding the S3 keys the detect-views endpoint
        # returned instead of re-uploading pixels.
        #
        # multi_view is NOT required to be set. It used to be opt-in, which
        # made the whole feature depend on the caller remembering: an agent
        # that generated from a sheet whose views had been detected in an
        # EARLIER turn had no trigger to pass the flag, and the job went out
        # as a lone base64 image with every crop silently dropped. An active
        # set on the tab is now signal enough — the user assembled it for
        # exactly this job. Clearing the set is how you opt out.
        turnaround = None
        if self.multi_view or _has_active_view_set(context):
            turnaround = self._resolve_turnaround(context, image)

        if image is None and not prompt:
            raise ValueError("Provide at least a prompt or an image_name")

        polygon_type = self.polygon_type.strip() or None
        shared = {
            "generate_type": "LowPoly" if polygon_type else "Normal",
            "model_version": self.model_version.strip() or "3.0",
            "enable_pbr": bool(self.enable_pbr),
            "face_count": self.face_count if self.face_count > 0 else None,
            "polygon_type": polygon_type,
            "prompt": prompt,
        }
        # Prefer the agent-supplied prompt over the image identifier so the
        # queue row reads like the user's intent — see image_to_3d_ops for
        # the same reasoning.
        label = (prompt[:40] if prompt else None) or (image.name if image else "3D")
        enqueue_pro_job(
            image=image, shared=shared, label=label, turnaround=turnaround,
            mesh_name=self.name)

    def _resolve_turnaround(self, context, image):
        """Multi-view payload built from *image* plus the tab's view set.

        *image* is the vendor's single frontal image; the companion angles
        come from the Model Gen tab's active multi-view set (the set holds
        companions only, so there is nothing on *image* to look it up from).

        Raises ValueError (caught by execute -> reported + CANCELLED) when the
        request cannot be honoured. Never falls back to a single-image job:
        the caller explicitly asked for the set, so silently generating from
        one view would spend a multi-minute job on the wrong input.
        """
        from mixar.modules.moodboard.core.turnaround_payload import (
            build_multi_view_payload,
        )
        from mixar.modules.moodboard.core.turnaround_views import (
            get_active_group,
        )

        if image is None:
            raise ValueError("multi_view=True requires an image_name")

        group_id = get_active_group(context.scene)
        if not group_id:
            raise ValueError(
                "No multi-view set is active — run "
                "mixie.moodboard_detect_views on the sheet first, or add "
                "views with mixie.moodboard_add_selected_views"
            )

        # Same duplicate handling the sidebar path uses. No model slug is
        # needed: which angles a model accepts is catalog capability, not
        # something the client derives from a version string.
        fragment, warnings = build_multi_view_payload(
            context.scene, group_id, image)
        for warning in warnings:
            self.report({'WARNING'}, warning)
        return fragment

    def _submit_rapid_direct(self, context, compress_image_for_upload):
        """Submit a Rapid job from explicit agent/chat params."""
        import base64 as _b64
        from mixar.modules.common.job_queue import enqueue_generation
        from mixar.modules.common.job_queue.constants import FEATURE_HUNYUAN_RAPID

        image = None
        if self.image_name.strip():
            image = bpy.data.images.get(self.image_name.strip())
            if image is None:
                raise ValueError(f"Image '{self.image_name}' not found")
            if not image.has_data:
                raise ValueError(f"Image '{self.image_name}' has no pixel data")

        prompt = self.prompt.strip()
        has_prompt = bool(prompt)
        has_image = image is not None
        if not has_prompt and not has_image:
            raise ValueError("Provide either a prompt or an image_name")
        if has_prompt and has_image:
            raise ValueError("Prompt and image are mutually exclusive")

        result_format = (self.result_format or "glb").strip().lower()
        if result_format not in {"glb", "usdz"}:
            raise ValueError("result_format must be 'glb' or 'usdz'")

        params = {
            "enable_pbr": bool(self.enable_pbr),
            "enable_geometry": bool(self.enable_geometry),
            "result_format": result_format,
        }
        if has_prompt:
            params["prompt"] = prompt

        payload = {"params": params}
        if has_image:
            image_bytes = compress_image_for_upload(image)
            payload["image_bytes_b64"] = _b64.b64encode(image_bytes).decode()
            payload["image_filename"] = "image.png"

        label = prompt[:40] if has_prompt else image.name
        from mixar.modules.moodboard.core.generation_enqueue import (
            derive_model_name, make_model_rename_on_imported,
        )
        mesh_name = derive_model_name(
            image, prompt if has_prompt else "", explicit=self.name)
        enqueue_generation(
            kind="glb",
            feature_key=FEATURE_HUNYUAN_RAPID,
            job_type=HUNYUAN_RAPID_JOB_TYPE,
            model=HUNYUAN_RAPID_MODEL,
            payload=payload,
            label=label,
            on_imported=make_model_rename_on_imported(mesh_name),
            scene_flag="mixie_hunyuan_rapid_is_generating",
        )

    def _submit_topology_direct(self, context):
        """Retopologize a single named mesh object from explicit params (agent).

        Used by the agent/chat path: looks up object_name in the scene and runs
        the queue retopology on it, bypassing the selection-based UI flow.
        """
        from mixar.modules.hunyuan.core.retopology_enqueue import (
            enqueue_retopology_jobs,
        )

        obj = bpy.data.objects.get(self.object_name.strip())
        if obj is None or obj.type != 'MESH':
            raise ValueError(f"Mesh object '{self.object_name}' not found")

        model = (self.model or "tripo").strip().lower()
        if model not in {"tripo", "hunyuan"}:
            raise ValueError("model must be 'tripo' or 'hunyuan'")

        shared = {
            "model": model,
            "polygon_type": self.polygon_type.strip() or None,
            "face_level": self.face_level if self.face_level > 0 else None,
            "post_process": bool(self.post_process),
        }
        enqueued = enqueue_retopology_jobs(
            context=context, objects=[obj], shared=shared, operator=self,
        )
        if not enqueued:
            raise ValueError(
                "Retopology could not be enqueued (export failed or file too large)",
            )

    def _submit_part_direct(self, context, enqueue_part_job):
        """Submit Hunyuan Part for a named mesh object from explicit params."""
        self._submit_selected_object_job(
            context=context,
            object_name=self.object_name,
            export_format=self.export_format,
            mode_props=context.scene.hunyuan.part,
            enqueue_func=enqueue_part_job,
            failure_message="Hunyuan Part could not be enqueued",
        )

    def _submit_uv_direct(self, context, enqueue_uv_job):
        """Submit Hunyuan UV for a named mesh object from explicit params."""
        self._submit_selected_object_job(
            context=context,
            object_name=self.object_name,
            export_format=self.export_format,
            mode_props=context.scene.hunyuan.uv,
            enqueue_func=enqueue_uv_job,
            failure_message="Hunyuan UV could not be enqueued",
        )

    def _submit_selected_object_job(
        self,
        *,
        context,
        object_name,
        export_format,
        mode_props,
        enqueue_func,
        failure_message,
    ):
        obj = bpy.data.objects.get(object_name.strip())
        if obj is None or obj.type != 'MESH':
            raise ValueError(f"Mesh object '{object_name}' not found")

        fmt = (export_format or "GLB").strip().upper()
        if fmt not in {"GLB", "OBJ", "FBX"}:
            raise ValueError("export_format must be GLB, OBJ, or FBX")

        prev_selected = list(context.selected_objects)
        prev_active = context.view_layer.objects.active
        prev_format = getattr(mode_props, "export_format", "GLB")
        try:
            for selected in prev_selected:
                selected.select_set(False)
            obj.select_set(True)
            context.view_layer.objects.active = obj
            mode_props.export_format = fmt
            job = enqueue_func(context=context, operator=self)
            if not job:
                raise ValueError(failure_message)
        finally:
            mode_props.export_format = prev_format
            obj.select_set(False)
            for selected in prev_selected:
                try:
                    selected.select_set(True)
                except ReferenceError:
                    pass
            try:
                context.view_layer.objects.active = prev_active
            except (ReferenceError, TypeError):
                pass

    def _submit_pro(
        self, context, pro, compress_image_for_upload,
    ):
        """Fan out a Pro generation request into the job queue.

        - When ``use_selected_image`` is on, every selected moodboard
          image becomes its own queued job (multi-view ignored).
        - Otherwise a single job is enqueued, optionally with multi-view
          images and the uploaded reference image.
        """
        from mixar.modules.moodboard.core.generation_enqueue import (
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
        import base64 as _b64
        from mixar.modules.common.job_queue import enqueue_generation
        from mixar.modules.common.job_queue.constants import FEATURE_HUNYUAN_RAPID

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

        if not has_prompt and not has_image:
            raise ValueError("Provide either a prompt or an image")
        if has_prompt and has_image:
            raise ValueError("Prompt and image are mutually exclusive")

        image_bytes = b""
        if has_image:
            if use_moodboard and mb_img:
                image_bytes = compress_image_for_upload(mb_img)
            elif rapid.image:
                image_bytes = compress_image_for_upload(rapid.image)

        params = {
            "enable_pbr": bool(rapid.enable_pbr),
            "enable_geometry": bool(rapid.enable_geometry),
            "result_format": (rapid.result_format or "glb").lower(),
        }
        prompt_str = rapid.prompt.strip() if has_prompt else ""
        if prompt_str:
            params["prompt"] = prompt_str

        payload = {"params": params}
        if image_bytes:
            payload["image_bytes_b64"] = _b64.b64encode(image_bytes).decode()
            payload["image_filename"] = "image.png"

        label = prompt_str[:40] if has_prompt else "image.png"

        from mixar.modules.moodboard.core.generation_enqueue import (
            derive_model_name, make_model_rename_on_imported,
        )
        rapid_image = mb_img or (rapid.image if has_image else None)
        mesh_name = derive_model_name(rapid_image, prompt_str)
        enqueue_generation(
            kind="glb",
            feature_key=FEATURE_HUNYUAN_RAPID,
            job_type=HUNYUAN_RAPID_JOB_TYPE,
            model=HUNYUAN_RAPID_MODEL,
            payload=payload,
            label=label,
            on_imported=make_model_rename_on_imported(mesh_name),
            scene_flag="mixie_hunyuan_rapid_is_generating",
        )

    def _submit_topology_queue(self, context, topo):
        """Fan out a Topology retopology request into the job queue.

        Each selected mesh becomes its own job (per-object fan-out, Q1).
        Files exceeding the size limit are skipped with a warning.
        """
        from mixar.modules.hunyuan.core.retopology_enqueue import (
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

        redraw_3d_views()
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

        redraw_3d_views()
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
