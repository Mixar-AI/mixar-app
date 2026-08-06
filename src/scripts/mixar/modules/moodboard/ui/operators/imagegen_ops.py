# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Image Gen Operators

Operators for AI image generation using the dynamic v2 API.
"""

import bpy
from bpy.types import Operator

from mixar.modules.common.utils.image_utils import compress_for_service
from mixar.config.logging_config import get_logger
from mixar.modules.moodboard.core.media_utils import is_still_item

logger = get_logger(__name__)

_imagegen_listener = None


def _get_imagegen_listener():
    """Lazily create the imagegen queue listener (cached singleton).

    Replicates the old imagegen_queue.py listener behaviour:
    - on_start: clear ``mixie_imagegen_error``
    - on_finish: redraw MIXIE areas
    """
    global _imagegen_listener
    if _imagegen_listener is not None:
        return _imagegen_listener

    from mixar.modules.common.job_queue.core.helpers import (
        create_scene_flag_listener,
    )

    def _on_start(scene):
        try:
            scene.mixie_imagegen_error = ""
        except (AttributeError, TypeError):
            pass

    def _on_finish(scene):
        try:
            for area in bpy.context.screen.areas:
                if area.type == 'MIXIE':
                    area.tag_redraw()
        except Exception:
            pass

    _imagegen_listener = create_scene_flag_listener(
        "mixie_imagegen_is_generating",
        on_start=_on_start,
        on_finish=_on_finish,
    )
    return _imagegen_listener


def _get_max_refs(model_name: str) -> int:
    """Get maximum reference images for a model (catalog, then hardcoded)."""
    try:
        from mixar.bootstrap.generation_catalog_cache import get_model

        model = get_model("image_gen", model_name)
        if model and model.get("max_reference_images") is not None:
            return int(model["max_reference_images"])
    except Exception:
        pass
    # Hardcoded last-resort fallback (offline / pre-auth)
    return 14 if model_name == "pro" else 3


def _get_default_image_model():
    """Default image_gen model slug from the catalog, or None."""
    try:
        from mixar.bootstrap.generation_catalog_cache import (
            get_default_model_slug,
        )
        return get_default_model_slug("image_gen")
    except Exception:
        return None


class MIXIE_OT_imagegen_generate(Operator):
    """Generate images using AI and add them to the moodboard"""

    bl_idname = "mixie.imagegen_generate"
    bl_label = "Generate Image"
    bl_description = "Generate AI images and add them to the moodboard"
    bl_options = {"REGISTER"}

    from_chat: bpy.props.BoolProperty(
        name="From Chat",
        description="Called from chat context - use defaults",
        default=False,
    )

    # Direct invocation properties (used by agent scripts).
    # When `prompt` is non-empty, these override chat/sidebar defaults.
    prompt: bpy.props.StringProperty(default="")
    model: bpy.props.StringProperty(default="")
    style: bpy.props.StringProperty(default="")
    aspect_ratio: bpy.props.StringProperty(default="")
    resolution: bpy.props.StringProperty(default="")
    number_of_images: bpy.props.IntProperty(default=0, min=0, max=4)
    negative_prompt: bpy.props.StringProperty(default="")
    reference_image_names: bpy.props.StringProperty(default="")
    # Agent-chosen base name for the generated moodboard image(s). Empty =
    # auto name (imagegen_<timestamp>_N). Blender dedups collisions.
    name: bpy.props.StringProperty(default="")

    def execute(self, context):
        # Direct invocation with explicit params (agent scripts)
        if self.prompt:
            return self._execute_direct(context)

        scene = context.scene

        # Check if called from sidebar context - prefer sidebar properties
        use_sidebar_props = False
        sidebar_tab = None
        prompt = ""

        # When called from chat, skip sidebar prompt entirely — use the
        # global property that the chat handler set so the user's chat
        # prompt is never overridden by stale sidebar text.
        if self.from_chat:
            prompt = getattr(scene, 'mixie_imagegen_prompt', '')
        else:
            if hasattr(scene, 'mixie_moodboard_sidebar'):
                sidebar = scene.mixie_moodboard_sidebar
                if sidebar and hasattr(sidebar, 'tab_imagegen'):
                    sidebar_tab = sidebar.tab_imagegen
                    if sidebar_tab:
                        # Sidebar tab found - use sidebar context for reference images
                        # regardless of whether prompt comes from sidebar or fallback
                        use_sidebar_props = True

                        # Try to read prompt from sidebar
                        sidebar_prompt = ""

                        # Method 1: Direct attribute access
                        try:
                            sidebar_prompt = sidebar_tab.prompt
                        except Exception as e:
                            logger.debug("Prompt read error (direct): %s", e)

                        # Method 2: RNA path resolution if method 1 failed
                        if not sidebar_prompt or not sidebar_prompt.strip():
                            try:
                                sidebar_prompt = scene.path_resolve(
                                    "mixie_moodboard_sidebar.tab_imagegen.prompt"
                                )
                            except Exception as e:
                                logger.debug("Prompt read error (path_resolve): %s", e)

                        # Method 3: getattr chain as fallback
                        if not sidebar_prompt or not sidebar_prompt.strip():
                            try:
                                sb = getattr(scene, 'mixie_moodboard_sidebar', None)
                                if sb:
                                    tab = getattr(sb, 'tab_imagegen', None)
                                    if tab:
                                        sidebar_prompt = getattr(tab, 'prompt', '')
                            except Exception as e:
                                logger.debug("Prompt read error (getattr): %s", e)

                        if sidebar_prompt and sidebar_prompt.strip():
                            prompt = sidebar_prompt

            # Fallback to global property if sidebar prompt is empty
            if not prompt or not prompt.strip():
                global_prompt = getattr(scene, 'mixie_imagegen_prompt', '')
                if global_prompt and global_prompt.strip():
                    prompt = global_prompt

        if not prompt or not prompt.strip():
            self.report({"WARNING"}, "Please enter a prompt (press Enter to confirm your text)")
            return {"CANCELLED"}

        # Determine model and other params based on context
        if self.from_chat:
            # Chat may pass an explicit model (picked via the in-chat
            # "which model?" ask); empty means the catalog default.
            model = self.model.strip() or _get_default_image_model()
            if not model:
                self.report(
                    {"WARNING"}, "No models available - please wait for models to load"
                )
                return {"CANCELLED"}

            # Check for chat-attached reference images
            reference_image_bytes = []
            for ref_item in scene.mixie_imagegen_ref_images:
                if ref_item.image:
                    try:
                        ref_bytes = compress_for_service(ref_item.image, "imagegen")
                        reference_image_bytes.append(ref_bytes)
                    except Exception as e:
                        logger.error("Error converting chat reference image '%s': %s",
                                     ref_item.image.name, e)
        else:
            # Get model from appropriate source (sidebar or global properties)
            if use_sidebar_props:
                model = sidebar_tab.model if hasattr(sidebar_tab, 'model') else ""
            else:
                model = scene.mixie_imagegen_model

            if model in ("LOADING", "ERROR", "NONE", ""):
                # Scene property has invalid value — use the catalog default
                model = _get_default_image_model()

            if not model or model in ("LOADING", "ERROR", "NONE", ""):
                self.report(
                    {"WARNING"}, "Please wait for models to load or check connection"
                )
                return {"CANCELLED"}

            # Get max reference images for this model
            max_refs = _get_max_refs(model)

            # Collect reference images
            reference_image_bytes = []

            # Determine which reference images to use based on context
            if use_sidebar_props:
                # Sidebar context: check toggle state
                use_moodboard_selection = getattr(sidebar_tab, 'use_reference_images', False)

                if use_moodboard_selection:
                    # Toggle ON: use currently selected moodboard images (dynamic)
                    for item in scene.mixie_moodboard_images:
                        if item.selected and is_still_item(item):
                            try:
                                img_bytes = compress_for_service(item.image, "imagegen")
                                reference_image_bytes.append(img_bytes)
                                if len(reference_image_bytes) >= max_refs:
                                    break
                            except Exception as e:
                                logger.error("Error converting moodboard image '%s': %s",
                                             item.image.name, e)
                else:
                    # Toggle OFF: use uploaded images from reference_images collection
                    if hasattr(sidebar_tab, 'reference_images'):
                        for ref_item in sidebar_tab.reference_images:
                            # Prefer direct image pointer, fall back to index
                            img = getattr(ref_item, 'image', None)
                            if not img and ref_item.moodboard_index >= 0:
                                mb_images = scene.mixie_moodboard_images
                                if ref_item.moodboard_index < len(mb_images):
                                    img = mb_images[ref_item.moodboard_index].image
                            if img:
                                try:
                                    img_bytes = compress_for_service(img, "imagegen")
                                    reference_image_bytes.append(img_bytes)
                                    if len(reference_image_bytes) >= max_refs:
                                        break
                                except Exception as e:
                                    logger.error("Error converting reference image '%s': %s",
                                                 img.name, e)
            else:
                # Popup context: use reference image collection + selected moodboard images
                # Add reference images from collection
                for ref_item in scene.mixie_imagegen_ref_images:
                    if ref_item.image:
                        try:
                            ref_bytes = compress_for_service(ref_item.image, "imagegen")
                            reference_image_bytes.append(ref_bytes)
                            if len(reference_image_bytes) >= max_refs:
                                break
                        except Exception as e:
                            logger.error("Error getting reference image: %s", e)

                # Add selected moodboard images (up to remaining slots)
                try:
                    for item in scene.mixie_moodboard_images:
                        if item.selected and is_still_item(item):
                            img_bytes = compress_for_service(item.image, "imagegen")
                            reference_image_bytes.append(img_bytes)
                            if len(reference_image_bytes) >= max_refs:
                                break
                except Exception as e:
                    logger.error("Error getting reference images: %s", e)

        # Collect style/aspect/resolution params
        if self.from_chat:
            style = "none"
            aspect_ratio = "1:1"
            resolution = "1K"
            negative_prompt = None
        elif use_sidebar_props:
            style = getattr(sidebar_tab, 'style', 'REALISTIC')
            aspect_ratio = getattr(sidebar_tab, 'aspect_ratio', '1_1')
            resolution = getattr(sidebar_tab, 'resolution', '1024')
            negative_prompt = None
        else:
            style = scene.mixie_imagegen_style
            aspect_ratio = scene.mixie_imagegen_aspect_ratio
            resolution = getattr(scene, "mixie_imagegen_resolution", "1K")
            negative_prompt = scene.mixie_imagegen_negative_prompt or None

        stored_prompt = prompt.strip()
        stored_num_images = getattr(scene, "mixie_imagegen_num_images", 1)

        # Sidebar context: prefer the catalog-driven parameter engine for
        # all params (style, aspect_ratio, resolution?, number_of_images,
        # and any future params). Falls back to the legacy hardcoded
        # properties when the catalog isn't loaded.
        catalog_params = None
        if not self.from_chat and use_sidebar_props:
            try:
                from mixar.modules.common.generation_params import (
                    collect_params, has_params,
                )
                if model and has_params("image_gen", model):
                    catalog_params = collect_params("image_gen", model)
            except Exception as e:
                logger.debug("Catalog param collection failed: %s", e)
                catalog_params = None

        if catalog_params is not None:
            params = {"style": style, **catalog_params}
            # Wire contract requires number_of_images even if a model's
            # schema omits it.
            params.setdefault("number_of_images", stored_num_images)
        else:
            params = {
                "style": style,
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
                "number_of_images": stored_num_images,
            }

        # Submit via FeatureQueue
        try:
            import base64 as _b64
            from mixar.modules.common.job_queue import enqueue_generation
            from mixar.modules.common.job_queue.constants import FEATURE_IMAGEGEN

            ref_b64 = []
            if reference_image_bytes:
                ref_b64 = [_b64.b64encode(img).decode() for img in reference_image_bytes]

            payload = {
                "prompt": stored_prompt,
                "params": params,
            }
            if negative_prompt:
                payload["params"]["negative_prompt"] = negative_prompt
            if ref_b64:
                payload["reference_images_b64"] = ref_b64

            job = enqueue_generation(
                kind="image",
                feature_key=FEATURE_IMAGEGEN,
                job_type="image_gen",
                model=model,
                payload=payload,
                label=f"ImageGen: {stored_prompt[:40]}",
                display_label=stored_prompt[:40],
                fail_message="Image generation failed",
                name_prefix="imagegen",
                prompt_text=stored_prompt,
                undo_message="Generate Image",
                listener=_get_imagegen_listener(),
            )
            if not job:
                self.report({"WARNING"}, "A duplicate image generation is already queued")
                return {"CANCELLED"}
        except Exception as e:
            self.report({"ERROR"}, f"Failed to start generation: {e}")
            return {"CANCELLED"}

        from mixar.modules.common.job_queue.ui.lists.queue_uilist import mark_enqueued
        mark_enqueued(FEATURE_IMAGEGEN)
        self.report({"INFO"}, "Added to queue")
        return {"FINISHED"}

    def _execute_direct(self, context):
        """Handle direct invocation with explicit params (agent scripts)."""
        import base64 as _b64
        import uuid as _uuid
        from mixar.modules.common.job_queue import enqueue_generation
        from mixar.modules.common.job_queue.constants import FEATURE_IMAGEGEN
        from mixar.modules.common.utils.image_utils import compress_image_for_upload
        from mixar.modules.common.utils.agent_feedback import (
            clear_agent_gen_reason, set_agent_gen_reason,
        )

        clear_agent_gen_reason(context)
        prompt = self.prompt.strip()
        model = self.model

        if not model:
            model = _get_default_image_model()
        if not model:
            set_agent_gen_reason(context, "No model specified and no default available")
            self.report({"ERROR"}, "No model specified and no default available")
            return {"CANCELLED"}

        # Collect reference images by name
        max_refs = _get_max_refs(model)
        ref_b64 = []
        if self.reference_image_names:
            for name in (n.strip() for n in self.reference_image_names.split(",") if n.strip()):
                img = bpy.data.images.get(name)
                if img and img.has_data:
                    try:
                        ref_b64.append(
                            _b64.b64encode(compress_image_for_upload(img)).decode()
                        )
                        if len(ref_b64) >= max_refs:
                            break
                    except Exception as e:
                        logger.error("Failed to convert ref image '%s': %s", name, e)

        payload = {
            "prompt": prompt,
            "params": {
                "style": self.style or "none",
                "aspect_ratio": self.aspect_ratio or "1:1",
                "resolution": self.resolution or "1K",
                "number_of_images": self.number_of_images or 1,
            },
        }
        if self.negative_prompt and self.negative_prompt.strip():
            payload["params"]["negative_prompt"] = self.negative_prompt.strip()
        if ref_b64:
            payload["reference_images_b64"] = ref_b64
        if self.name.strip():
            # Agent-chosen name: the backend uses it for the S3 filenames,
            # skips Gemini's own name suggestion, and echoes it in the result.
            payload["image_name"] = self.name.strip()

        # Prefer the actual API prompt for the row title so the queue reads
        # like the interactive path; fall back to name / "image" if empty.
        # The 4-hex uuid suffix keeps the queue's label-based dedup happy
        # when a batch contains multiple images of the same prompt.
        _label_base = prompt[:40] or self.name.strip() or "image"
        job = enqueue_generation(
            kind="image",
            feature_key=FEATURE_IMAGEGEN,
            job_type="image_gen",
            model=model,
            payload=payload,
            label=f"ImageGen: {_label_base} [{_uuid.uuid4().hex[:4]}]",
            display_label=_label_base,
            fail_message="Image generation failed",
            name_prefix="imagegen",
            prompt_text=prompt,
            undo_message="Generate Image",
            base_name=self.name.strip(),
            listener=_get_imagegen_listener(),
        )
        if not job:
            set_agent_gen_reason(context, "A duplicate image generation is already queued")
            self.report({"WARNING"}, "A duplicate image generation is already queued")
            return {"CANCELLED"}

        from mixar.modules.common.job_queue.ui.lists.queue_uilist import mark_enqueued
        mark_enqueued(FEATURE_IMAGEGEN)
        self.report({"INFO"}, "Added to queue")
        return {"FINISHED"}


classes = (
    MIXIE_OT_imagegen_generate,
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
