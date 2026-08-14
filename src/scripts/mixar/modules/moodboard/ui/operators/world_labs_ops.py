# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""World Labs (Marble) operators.

Manage the input image and trigger world generation through the unified
generation queue (job_type ``world_labs``).
"""

import base64 as _b64
import os

import bpy
from bpy.types import Operator

from ....common.utils.file_select_utils import file_select_guard, mark_file_select_executed
from ...core.image_lifecycle import remove_image_safely


def _get_world_labs_tab(context):
    scene = context.scene
    sidebar = getattr(scene, "mixie_moodboard_sidebar", None)
    return getattr(sidebar, "tab_world_labs", None) if sidebar else None


def _catalog_settings(
    selected_model: str = "", selected_mode: str = "", selected_lod: str = "",
):
    """Resolve World Labs model parameters exclusively from the live catalog."""
    from mixar.bootstrap.generation_catalog_cache import (
        get_default_model_slug,
        get_model,
    )
    from mixar.modules.common.generation_params import collect_params

    placeholders = {"", "LOADING", "NONE", "ERROR"}
    requested = selected_model or ""
    if requested not in placeholders and get_model("world_labs", requested) is None:
        raise ValueError(f"World Labs model '{requested}' is not enabled")
    model = (
        requested if requested not in placeholders
        else (get_default_model_slug("world_labs") or "")
    )
    model_row = get_model("world_labs", model) if model else None
    if not model_row:
        raise ValueError("No enabled World Labs model is available")

    values = collect_params("world_labs", model)
    schema = model_row.get("parameters") or {}

    def _value(name, explicit):
        spec = schema.get(name) or {}
        value = explicit or values.get(name) or spec.get("default")
        allowed = spec.get("enum")
        if value is None or (allowed is not None and value not in allowed):
            raise ValueError(f"World Labs catalog parameter '{name}' is unavailable")
        return str(value)

    return model, _value("mode", selected_mode), _value("lod", selected_lod)


class MIXIE_OT_world_labs_pick_image(Operator):
    """Pick an input image for World Labs world generation"""

    bl_idname = "mixie.world_labs_pick_image"
    bl_label = "Pick Image"
    bl_description = "Select an input image for world generation"
    bl_options = {"REGISTER", "UNDO"}

    filepath: bpy.props.StringProperty(
        name="File Path", description="Path to the input image file",
        subtype="FILE_PATH",
    )
    filter_glob: bpy.props.StringProperty(
        default="*.png;*.jpg;*.jpeg;*.bmp;*.tga;*.tiff;*.webp", options={"HIDDEN"}
    )

    def invoke(self, context, event):
        if not file_select_guard(self, context):
            return {"FINISHED"}
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        if not self.filepath:
            self.report({"WARNING"}, "No file selected")
            return {"CANCELLED"}
        try:
            filepath = os.path.abspath(os.path.realpath(self.filepath))
        except (OSError, ValueError) as e:
            self.report({"ERROR"}, f"Invalid file path: {e}")
            return {"CANCELLED"}
        if not os.path.isfile(filepath):
            self.report({"ERROR"}, f"File not found: {filepath}")
            return {"CANCELLED"}

        try:
            img = bpy.data.images.load(filepath, check_existing=True)
            img.pack()
        except Exception as e:  # noqa: BLE001
            self.report({"ERROR"}, f"Failed to load image: {e}")
            return {"CANCELLED"}

        tab = _get_world_labs_tab(context)
        if tab is None:
            self.report({"ERROR"}, "Sidebar properties not found")
            return {"CANCELLED"}
        tab.reference_image = img
        tab.use_selected_image = False  # show the uploaded-image card
        self.report({"INFO"}, f"Selected '{img.name}' as input image")
        mark_file_select_executed(self)
        return {"FINISHED"}


class MIXIE_OT_world_labs_remove_image(Operator):
    """Remove the input image from the World Labs tab"""

    bl_idname = "mixie.world_labs_remove_image"
    bl_label = "Remove Image"
    bl_description = "Remove the input image"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        tab = _get_world_labs_tab(context)
        if tab is None:
            self.report({"ERROR"}, "Sidebar properties not found")
            return {"CANCELLED"}
        old_img = getattr(tab, "reference_image", None)
        tab.reference_image = None
        remove_image_safely(old_img)
        self.report({"INFO"}, "Input image removed")
        return {"FINISHED"}


class MIXIE_OT_world_labs_generate(Operator):
    """Generate a 3D world with World Labs (Marble)"""

    bl_idname = "mixie.world_labs_generate"
    bl_label = "Generate World"
    bl_description = "Generate a 3D world from a text prompt or image"
    bl_options = {"REGISTER"}

    # Agent-direct invocation params (set by enqueue_generation). `from_agent`
    # marks the agent path (set via the spec const_args) so we route to
    # _execute_direct and surface a clean agent_feedback reason even when no
    # prompt/image_name was supplied, instead of falling to the sidebar tab.
    from_agent: bpy.props.BoolProperty(default=False, options={"SKIP_SAVE"})
    mode: bpy.props.StringProperty(default="")
    prompt: bpy.props.StringProperty(default="")
    image_name: bpy.props.StringProperty(default="")
    model: bpy.props.StringProperty(default="")
    lod: bpy.props.StringProperty(default="")

    def execute(self, context):
        from mixar.modules.common.utils.image_utils import compress_for_service
        from mixar.modules.common.job_queue.constants import FEATURE_WORLD_LABS
        from mixar.modules.common.job_queue.ui.lists.queue_uilist import mark_enqueued
        from mixar.modules.moodboard.core.world_labs_queue import enqueue_world_labs_job

        # Agent-direct path: explicit params from enqueue_generation. Route here
        # whenever the agent invoked us (from_agent) so empty params yield a clean
        # agent_feedback reason rather than the "no sidebar tab" path.
        if self.from_agent or self.prompt or self.image_name:
            return self._execute_direct(context)

        tab = _get_world_labs_tab(context)
        if tab is None:
            self.report({"ERROR"}, "World Labs tab not available")
            return {"CANCELLED"}

        prompt = (getattr(tab, "prompt", "") or "").strip()
        try:
            model, catalog_mode, lod = _catalog_settings(
                selected_model=getattr(tab, "model", ""),
            )
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        from mixar.modules.moodboard.core.world_labs_mode import (
            resolve_world_labs_mode,
        )

        image = None
        if catalog_mode == "image":
            image = self._resolve_image(context, tab, quiet=bool(prompt))
            # Catalog default is image. A prompt-only submit must not keep
            # that default — the backend would charge and then 422.
            if image is None and not prompt:
                return {"CANCELLED"}
        mode = resolve_world_labs_mode(
            catalog_mode, has_image=image is not None, has_prompt=bool(prompt),
        )

        image_b64 = ""
        label = prompt[:40] if prompt else "World"

        if mode == "image":
            if image is None:
                return {"CANCELLED"}
            try:
                image_bytes = compress_for_service(image, "world_labs")
            except Exception as e:  # noqa: BLE001
                self.report({"ERROR"}, f"Failed to process image: {e}")
                return {"CANCELLED"}
            image_b64 = _b64.b64encode(image_bytes).decode()
            label = image.name
        elif not prompt:
            self.report({"WARNING"}, "Please enter a text prompt")
            return {"CANCELLED"}

        try:
            job = enqueue_world_labs_job(
                mode=mode,
                prompt=prompt,
                model=model,
                lod=lod,
                image_bytes_b64=image_b64,
                label=label,
            )
        except Exception as e:  # noqa: BLE001
            self.report({"ERROR"}, f"Failed to start generation: {e}")
            return {"CANCELLED"}

        if not job:
            self.report({"WARNING"}, "A duplicate generation is already queued")
            return {"CANCELLED"}

        mark_enqueued(FEATURE_WORLD_LABS)
        self.report({"INFO"}, "Added to queue")
        return {"FINISHED"}

    def _execute_direct(self, context):
        """Agent invocation with explicit params (mode/prompt/image_name/model/lod)."""
        from mixar.modules.common.utils.image_utils import compress_for_service
        from mixar.modules.common.job_queue.constants import FEATURE_WORLD_LABS
        from mixar.modules.common.job_queue.ui.lists.queue_uilist import mark_enqueued
        from mixar.modules.moodboard.core.world_labs_queue import enqueue_world_labs_job
        from mixar.modules.common.utils.agent_feedback import (
            clear_agent_gen_reason, set_agent_gen_reason,
        )

        clear_agent_gen_reason(context)
        prompt = (self.prompt or "").strip()
        from mixar.modules.moodboard.core.world_labs_mode import (
            resolve_world_labs_mode,
        )

        requested_mode = self.mode or ("image" if self.image_name else "text")
        try:
            model, catalog_mode, lod = _catalog_settings(
                selected_model=self.model,
                selected_mode=requested_mode,
                selected_lod=self.lod,
            )
        except ValueError as e:
            set_agent_gen_reason(context, str(e))
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        mode = resolve_world_labs_mode(
            catalog_mode,
            has_image=bool(self.image_name),
            has_prompt=bool(prompt),
        )

        image_b64 = ""
        label = prompt[:40] if prompt else "World"
        if mode == "image":
            img = bpy.data.images.get(self.image_name)
            if img is None or not img.has_data:
                set_agent_gen_reason(
                    context, f"Image '{self.image_name}' not found on the moodboard"
                )
                self.report({"ERROR"}, "Image not found")
                return {"CANCELLED"}
            try:
                image_bytes = compress_for_service(img, "world_labs")
            except Exception as e:  # noqa: BLE001
                set_agent_gen_reason(context, f"Failed to process image: {e}")
                self.report({"ERROR"}, f"Failed to process image: {e}")
                return {"CANCELLED"}
            image_b64 = _b64.b64encode(image_bytes).decode()
            label = img.name
        elif not prompt:
            set_agent_gen_reason(
                context,
                "world_labs needs a prompt (text mode) or image_name (image mode)",
            )
            self.report({"WARNING"}, "Provide a prompt or image_name")
            return {"CANCELLED"}

        job = enqueue_world_labs_job(
            mode=mode, prompt=prompt, model=model, lod=lod,
            image_bytes_b64=image_b64, label=label,
        )
        if not job:
            set_agent_gen_reason(context, "A duplicate world generation is already queued")
            self.report({"WARNING"}, "A duplicate world is already queued")
            return {"CANCELLED"}
        mark_enqueued(FEATURE_WORLD_LABS)
        self.report({"INFO"}, "Added to queue")
        return {"FINISHED"}

    def _resolve_image(self, context, tab, quiet=False):
        """Return the chosen image (selected moodboard image or uploaded)."""
        if getattr(tab, "use_selected_image", True):
            scene = context.scene
            selected = [
                item.image for item in getattr(scene, "mixie_moodboard_images", [])
                if item.selected and item.image
            ]
            if not selected:
                if not quiet:
                    self.report({"WARNING"}, "Please select an image in the moodboard")
                return None
            return selected[0]
        image = getattr(tab, "reference_image", None)
        if not image:
            if not quiet:
                self.report({"WARNING"}, "Please add an input image")
            return None
        return image


classes = (
    MIXIE_OT_world_labs_pick_image,
    MIXIE_OT_world_labs_remove_image,
    MIXIE_OT_world_labs_generate,
)


def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)


def unregister():
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)
