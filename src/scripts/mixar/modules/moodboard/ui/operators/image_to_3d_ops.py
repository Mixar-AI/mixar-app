# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Image to 3D Operators

Operators for 3D model generation from images using the unified job queue.
"""

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.common.utils.image_utils import compress_for_service
from mixar.modules.moodboard.core.media_utils import is_still_item

logger = get_logger(__name__)


def _get_default_model_3d():
    """Default model_3d model slug from the catalog, or None."""
    try:
        from mixar.bootstrap.generation_catalog_cache import (
            get_default_model_slug,
        )
        return get_default_model_slug("model_3d")
    except Exception:
        return None


class MIXIE_OT_image_to_3d_generate(Operator):
    """Generate a 3D model from an image"""

    bl_idname = "mixie.image_to_3d_generate"
    bl_label = "Generate 3D Model"
    bl_description = "Generate a 3D model from the selected image"
    bl_options = {"REGISTER"}

    from_chat: bpy.props.BoolProperty(
        name="From Chat",
        description="Called from chat context - use defaults",
        default=False,
    )

    # Direct invocation properties (used by agent scripts).
    # When `image_name` is non-empty, these override UI defaults.
    image_name: bpy.props.StringProperty(default="")
    model: bpy.props.StringProperty(default="")
    prompt: bpy.props.StringProperty(default="")
    # Agent-chosen name for the imported mesh; empty falls back to the input
    # image name, then a prompt slug (see generation_enqueue.derive_model_name).
    name: bpy.props.StringProperty(default="")

    # Trellis-specific
    texture_size: bpy.props.IntProperty(default=0, min=0, max=4096)
    mesh_simplify: bpy.props.FloatProperty(default=-1.0, min=-1.0, max=1.0)
    generate_normal: bpy.props.BoolProperty(default=True)
    save_gaussian_ply: bpy.props.BoolProperty(default=False)

    # Rodin-specific
    quality: bpy.props.StringProperty(default="")
    geometry_file_format: bpy.props.StringProperty(default="")
    material: bpy.props.StringProperty(default="")

    # Tripo-specific (tripo-p1)
    texture: bpy.props.BoolProperty(default=True)
    face_limit: bpy.props.IntProperty(default=0, min=0, max=20000)
    model_seed: bpy.props.IntProperty(default=0)

    def execute(self, context):
        # Direct invocation with explicit params (agent scripts)
        if self.image_name:
            return self._execute_direct(context)
        scene = context.scene

        # Check if called from sidebar context - prefer sidebar properties
        sidebar_tab = None
        if hasattr(scene, 'mixie_moodboard_sidebar'):
            sidebar = scene.mixie_moodboard_sidebar
            if hasattr(sidebar, 'tab_image_to_3d'):
                sidebar_tab = sidebar.tab_image_to_3d

        # Determine model to use
        if self.from_chat:
            # Chat may pass an explicit model (picked via the in-chat
            # "which model?" ask); empty means the catalog default.
            model_name = self.model.strip() or _get_default_model_3d()
            if not model_name:
                self.report({"WARNING"}, "No models available - please wait for models to load")
                return {"CANCELLED"}
        else:
            if sidebar_tab:
                model_name = getattr(sidebar_tab, 'model', '')
            elif hasattr(scene, 'mixie_image_to_3d_model'):
                model_name = scene.mixie_image_to_3d_model
            else:
                model_name = ''

            if model_name in ("LOADING", "ERROR", "NONE", ""):
                # Property has invalid value — use the catalog default
                model_name = _get_default_model_3d()

            if not model_name or model_name in ("LOADING", "ERROR", "NONE", ""):
                self.report({"WARNING"}, "Please wait for models to load or check connection")
                return {"CANCELLED"}

        # Get the input image based on context
        image = None

        if self.from_chat:
            if hasattr(scene, 'mixie_image_to_3d_image'):
                image = scene.mixie_image_to_3d_image
                if not image:
                    self.report({"WARNING"}, "Please attach an image in chat")
                    return {"CANCELLED"}
            else:
                self.report({"WARNING"}, "No input image available")
                return {"CANCELLED"}
        elif sidebar_tab:
            use_selected = getattr(sidebar_tab, 'use_selected_image', False)
            if use_selected:
                selected = [
                    item for item in scene.mixie_moodboard_images
                    if item.selected and is_still_item(item)
                ]
                if selected:
                    image = selected[0].image
                else:
                    self.report({"WARNING"}, "Please select an image in the moodboard")
                    return {"CANCELLED"}
            else:
                image = getattr(sidebar_tab, 'reference_image', None)
                if not image:
                    self.report({"WARNING"}, "Please add an input image")
                    return {"CANCELLED"}
        else:
            if hasattr(scene, 'mixie_image_to_3d_use_selected') and scene.mixie_image_to_3d_use_selected:
                selected = [
                    item for item in scene.mixie_moodboard_images
                    if item.selected and is_still_item(item)
                ]
                if selected:
                    image = selected[0].image
                else:
                    self.report({"WARNING"}, "No image selected in moodboard")
                    return {"CANCELLED"}
            elif hasattr(scene, 'mixie_image_to_3d_image'):
                image = scene.mixie_image_to_3d_image
                if not image:
                    self.report({"WARNING"}, "No input image selected")
                    return {"CANCELLED"}
            else:
                self.report({"WARNING"}, "No input image available")
                return {"CANCELLED"}

        # Turnaround sheets: the detect-views endpoint already split this
        # image into per-view crops and staged them in S3, so submit ONE
        # multi-view job forwarding those keys verbatim rather than
        # re-uploading pixels. Anything else takes the single-image path
        # below, unchanged.
        turnaround_payload = self._turnaround_payload(scene, image, model_name)
        if turnaround_payload is False:
            return {"CANCELLED"}

        # Convert image to bytes
        image_bytes = None
        if not turnaround_payload:
            try:
                image_bytes = compress_for_service(image, "image_to_3d")
            except Exception as e:
                self.report({"ERROR"}, f"Failed to process image: {e}")
                return {"CANCELLED"}

        # Get prompt (optional)
        if sidebar_tab:
            prompt = getattr(sidebar_tab, 'prompt', '').strip() or None
        elif hasattr(scene, 'mixie_image_to_3d_prompt'):
            prompt = scene.mixie_image_to_3d_prompt.strip() or None
        else:
            prompt = None

        # Enqueue via job queue
        try:
            import base64 as _b64
            from mixar.modules.common.job_queue import enqueue_generation
            from mixar.modules.common.job_queue.constants import FEATURE_MODEL_3D

            from mixar.modules.moodboard.core.generation_enqueue import (
                derive_model_name, make_model_rename_on_imported,
                model_front_zrot,
            )

            job_label = image.name if image else model_name
            payload = {}
            if turnaround_payload:
                payload.update(turnaround_payload)
            elif image_bytes:
                payload["image_bytes_b64"] = _b64.b64encode(image_bytes).decode()
                payload["image_filename"] = "image.png"
            if prompt:
                payload["prompt"] = prompt

            mesh_name = derive_model_name(image, prompt or "")
            job = enqueue_generation(
                kind="glb",
                feature_key=FEATURE_MODEL_3D,
                job_type="model_3d",
                model=model_name,
                payload=payload,
                label=job_label or "model_3d",
                fail_message="3D model generation failed",
                on_imported=make_model_rename_on_imported(
                    mesh_name, model_front_zrot(model_name)),
                scene_flag="mixie_image_to_3d_is_generating",
                batch_popup_title="Image to 3D batch complete",
            )
            if not job:
                self.report({"WARNING"}, "A duplicate generation is already queued")
                return {"CANCELLED"}
        except Exception as e:
            self.report({"ERROR"}, f"Failed to start generation: {e}")
            return {"CANCELLED"}

        from mixar.modules.common.job_queue.ui.lists.queue_uilist import mark_enqueued
        mark_enqueued(FEATURE_MODEL_3D)
        self.report({"INFO"}, "Added to queue")
        return {"FINISHED"}

    def _turnaround_payload(self, scene, image, model_name):
        """Multi-view payload fragment for the set *image* is the main of.

        The set is resolved from *image* — the vendor's single frontal image,
        never a member of its own set — so both callers (sidebar Generate and
        the direct agent invocation) get the same answer for the same image,
        and an unrelated image never inherits a set left active on the tab.
        Returns ``None`` when *image* owns no multi-view set (the existing
        single-image path applies unchanged), ``False`` when the set is
        unusable and the operator should cancel, else the fragment.
        """
        from mixar.modules.moodboard.core.turnaround_views import (
            build_active_group_payload,
        )

        if image is None:
            return None
        try:
            result = build_active_group_payload(
                scene, image, "model_3d", model_name)
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return False
        if result is None:
            return None
        fragment, warnings = result
        for warning in warnings:
            self.report({"WARNING"}, warning)
        return fragment

    def _execute_direct(self, context):
        """Handle direct invocation with explicit params (agent scripts)."""
        import base64 as _b64
        from mixar.modules.common.job_queue import enqueue_generation
        from mixar.modules.common.job_queue.constants import FEATURE_MODEL_3D
        from mixar.modules.common.utils.image_utils import compress_image_for_upload
        from mixar.modules.common.utils.agent_feedback import (
            clear_agent_gen_reason, set_agent_gen_reason,
        )

        clear_agent_gen_reason(context)
        img = bpy.data.images.get(self.image_name.strip())
        if not img:
            set_agent_gen_reason(context, f"Image '{self.image_name}' not found in bpy.data.images")
            self.report({"ERROR"}, f"Image '{self.image_name}' not found in bpy.data.images")
            return {"CANCELLED"}
        if not img.has_data:
            set_agent_gen_reason(context, f"Image '{self.image_name}' has no pixel data")
            self.report({"ERROR"}, f"Image '{self.image_name}' has no pixel data")
            return {"CANCELLED"}

        # Agent invocations are always authenticated, so the catalog is the
        # single source of valid models — no hardcoded fallback list.
        try:
            from mixar.bootstrap.generation_catalog_cache import (
                get_default_model_slug, get_models, is_loaded,
            )
            catalog_ready = is_loaded()
        except Exception:
            catalog_ready = False
        if not catalog_ready:
            set_agent_gen_reason(context, "Generation catalog not loaded yet — retry shortly")
            self.report({"ERROR"}, "Generation catalog not loaded yet — retry shortly")
            return {"CANCELLED"}

        valid_models = tuple(m["slug"] for m in get_models("model_3d"))
        model_name = (
            self.model.strip().lower() if self.model
            else (get_default_model_slug("model_3d") or "")
        )
        if not model_name or model_name not in valid_models:
            choices = ", ".join(f"'{m}'" for m in valid_models)
            set_agent_gen_reason(context, f"Invalid model '{model_name}'; must be one of: {choices}")
            self.report({"ERROR"}, f"Invalid model '{model_name}'. Must be one of: {choices}")
            return {"CANCELLED"}

        # The agent operator is the path used by backend
        # enqueue_generation("model_3d", ...). It must use the same active
        # turnaround set as the sidebar path; previously it always compressed
        # only ``img``, silently dropping every companion.
        turnaround_payload = self._turnaround_payload(
            context.scene, img, model_name)
        if turnaround_payload is False:
            set_agent_gen_reason(
                context,
                "The active multi-view set could not be submitted",
            )
            return {"CANCELLED"}

        image_bytes = None
        if not turnaround_payload:
            try:
                image_bytes = compress_image_for_upload(img)
            except Exception as e:
                set_agent_gen_reason(context, f"Failed to convert image: {e}")
                self.report({"ERROR"}, f"Failed to convert image: {e}")
                return {"CANCELLED"}

        # Pass through only the operator properties the agent explicitly
        # set; the backend validates them against the model's catalog
        # schema and fills defaults for the rest. No per-model branching —
        # unknown params for the chosen model are ignored server-side.
        _PARAM_PROPS = (
            "texture_size", "mesh_simplify", "generate_normal",
            "save_gaussian_ply", "quality", "geometry_file_format",
            "material", "texture", "face_limit", "model_seed",
        )
        parameters = {
            name: getattr(self, name)
            for name in _PARAM_PROPS
            if self.properties.is_property_set(name)
        }

        payload = dict(turnaround_payload or {})
        if image_bytes:
            payload.update({
                "image_bytes_b64": _b64.b64encode(image_bytes).decode(),
                "image_filename": "image.png",
            })
        # NOTE: the backend model_3d path reads payload["params"] — the old
        # "parameters" key was silently ignored.
        payload["params"] = parameters
        prompt = self.prompt.strip() if self.prompt else None
        if prompt:
            payload["prompt"] = prompt

        # Prefer the agent-supplied prompt over the image identifier so the
        # queue row reads like the user's intent (image name is typically an
        # auto-generated slug like ``imagegen_1783156890_0`` when the agent
        # chained ImageGen → Image-to-3D).
        job_label = prompt[:40] if prompt else (self.image_name.strip() or "model_3d")

        # Mesh name: agent-chosen (self.name) wins, else the input image name,
        # else a prompt slug. Applied to the import (Trellis empty + mesh, or
        # a single Hunyuan/Tripo mesh) with origin/world-origin normalization.
        from mixar.modules.moodboard.core.generation_enqueue import (
            derive_model_name, make_model_rename_on_imported, model_front_zrot,
        )
        mesh_name = derive_model_name(img, prompt or "", explicit=self.name)

        job = enqueue_generation(
            kind="glb",
            feature_key=FEATURE_MODEL_3D,
            job_type="model_3d",
            model=model_name,
            payload=payload,
            label=job_label,
            fail_message="3D model generation failed",
            on_imported=make_model_rename_on_imported(
                mesh_name, model_front_zrot(model_name)),
            scene_flag="mixie_image_to_3d_is_generating",
            batch_popup_title="Image to 3D batch complete",
        )
        if not job:
            set_agent_gen_reason(context, "A duplicate 3D generation is already queued")
            self.report({"WARNING"}, "A duplicate generation is already queued")
            return {"CANCELLED"}

        from mixar.modules.common.job_queue.ui.lists.queue_uilist import mark_enqueued
        mark_enqueued(FEATURE_MODEL_3D)
        self.report({"INFO"}, "Added to queue")
        return {"FINISHED"}


classes = (
    MIXIE_OT_image_to_3d_generate,
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
