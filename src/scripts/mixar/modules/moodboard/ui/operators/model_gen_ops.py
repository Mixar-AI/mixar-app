# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Model Gen Operators

Generate operator for the consolidated, catalog-driven Model Gen tab.
Routes by the tab's selected mode (catalog service of capability
``model_gen``) and submits through the unified job queue with each mode's
EXISTING wire payload shape (see generation_params/core/assemblers.py):

- ``model_3d``      → job_type "model_3d", FEATURE_MODEL_3D
- ``image_to_3d``   → job_type "image_to_3d" (Hunyuan Pro),
                      FEATURE_IMAGE_TO_3D_PRO, reuses the Pro import hook
- ``hunyuan_rapid`` → job_type "hunyuan_rapid", FEATURE_HUNYUAN_RAPID
"""

import base64 as _b64

from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.moodboard.core.media_utils import is_still_item

logger = get_logger(__name__)

# Placeholder enum ids that are never real catalog keys/slugs.
_PLACEHOLDERS = ("LOADING", "ERROR", "NONE", "")


def _routing(service_key):
    """Per-service enqueue kwargs (feature key, flags, import hooks).

    Mirrors what each mode's legacy operator passes to
    ``enqueue_generation`` today. Unknown (future) services fall back to
    the catalog service's own feature_key and the model_3d-style listener.
    """
    from mixar.modules.common.job_queue.constants import (
        FEATURE_HUNYUAN_RAPID,
        FEATURE_IMAGE_TO_3D_PRO,
        FEATURE_MODEL_3D,
    )

    if service_key == "model_3d":
        return dict(
            feature_key=FEATURE_MODEL_3D,
            fail_message="3D model generation failed",
            scene_flag="mixie_image_to_3d_is_generating",
            batch_popup_title="Image to 3D batch complete",
        )
    if service_key == "image_to_3d":
        # on_imported is set by the operator (mesh naming + normalization),
        # so it is intentionally omitted here.
        return dict(
            feature_key=FEATURE_IMAGE_TO_3D_PRO,
            fail_message="Image to 3D failed",
            scene_flag="mixie_image_to_3d_is_generating",
            batch_popup_title="Image to 3D batch complete",
        )
    if service_key == "hunyuan_rapid":
        return dict(
            feature_key=FEATURE_HUNYUAN_RAPID,
            scene_flag="mixie_hunyuan_rapid_is_generating",
        )

    # Unknown service — generic routing keyed by the catalog service.
    feature_key = service_key
    try:
        from mixar.bootstrap.generation_catalog_cache import get_service
        svc = get_service(service_key)
        if svc and svc.get("feature_key"):
            feature_key = svc["feature_key"]
    except Exception:
        pass
    return dict(
        feature_key=feature_key,
        scene_flag="mixie_image_to_3d_is_generating",
    )


class MIXIE_OT_model_gen_generate(Operator):
    """Generate a 3D model using the selected Model Gen mode"""

    bl_idname = "mixie.model_gen_generate"
    bl_label = "Generate 3D Model"
    bl_description = "Generate a 3D model using the selected mode and model"
    bl_options = {"REGISTER"}

    def _get_input_image(self, context, tab):
        """Input image from the shared image-source UI (or None)."""
        scene = context.scene
        if getattr(tab, 'use_selected_image', False):
            if hasattr(scene, 'mixie_moodboard_images'):
                for item in scene.mixie_moodboard_images:
                    if item.selected and is_still_item(item):
                        return item.image
            return None
        return getattr(tab, 'reference_image', None)

    def _turnaround_payload(self, context, image, service_key, model):
        """Multi-view payload fragment for the set *image* is the main of.

        The ONLY multi-view source for this tab: the Multiple Views section
        holds both backend-detected turnaround crops and views the user added
        by hand, so there is nothing else to merge in.
        ``scene.hunyuan.pro.multi_views`` is deliberately not consulted — it
        belongs to the standalone Hunyuan panel, and reading it here used to
        silently discard whatever the user put in it.

        The set is resolved FROM *image* (the vendor's single frontal image,
        never a group member), not from the tab, so an Input Image that does
        not own a set takes the plain single-image path even while a set is
        active on the tab. Reading it off the tab is the production defect:
        a set detected for one subject was inherited by an unrelated image
        picked later and generated as a morph of the two.

        Shares ``build_active_group_payload`` with the agent/legacy operator
        so the binding, the capability check and the terminal error wording
        all come from one place. Deliberately NOT pre-gated on
        ``model_supports_multi_view``: an incapable model on a bound main has
        to cancel loudly, and an early-out would silently drop the set — the
        exact "degrade to one image" this guard exists to prevent.

        Returns ``None`` when *image* owns no multi-view set (the normal
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
                context.scene, image, service_key, model)
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return False
        if result is None:
            return None
        fragment, warnings = result
        for warning in warnings:
            self.report({"WARNING"}, warning)
        return fragment

    def execute(self, context):
        from mixar.modules.common.generation_params import (
            assemble_payload, collect_params, model_supports_multi_view,
            resolve_service_key,
        )
        from mixar.modules.common.utils.image_utils import (
            compress_for_service, compress_image_for_upload,
        )

        scene = context.scene
        sidebar = getattr(scene, 'mixie_moodboard_sidebar', None)
        tab = getattr(sidebar, 'tab_image_to_3d', None) if sidebar else None
        if tab is None:
            self.report({"WARNING"}, "Model Gen tab not available")
            return {"CANCELLED"}

        # --- Resolve mode (service) and model slug from the catalog ---
        service_key = resolve_service_key("model_gen", getattr(tab, "mode", ""))
        if not service_key:
            self.report({"WARNING"}, "Please wait for the catalog to load")
            return {"CANCELLED"}

        model = getattr(tab, 'model', '')
        if model in _PLACEHOLDERS:
            try:
                from mixar.bootstrap.generation_catalog_cache import (
                    get_default_model_slug,
                )
                model = get_default_model_slug(service_key) or ""
            except Exception:
                model = ""
        if not model or model in _PLACEHOLDERS:
            self.report({"WARNING"}, "Please wait for models to load")
            return {"CANCELLED"}

        # --- Inputs (image shared by all modes; multi-view for models that
        # advertise supports_multi_view, keyed per-model not per-service) ---
        image = self._get_input_image(context, tab)
        prompt = (getattr(tab, 'prompt', '') or '').strip() or None
        supports_mv = model_supports_multi_view(service_key, model)

        # --- Multiple Views: submit the whole set as ONE multi-view job ---
        # Detected crops were already staged in S3 by detect-views, so their
        # keys are forwarded verbatim; hand-added views carry inline pixels.
        # Applies only when THIS image is the set's own frontal image; the
        # capability check lives inside, not in the supports_mv pre-gate.
        turnaround_payload = self._turnaround_payload(
            context, image, service_key, model)
        if turnaround_payload is False:
            return {"CANCELLED"}

        # Per-mode input validation (mirrors each legacy operator).
        if turnaround_payload:
            pass  # the input image plus its companion views are the input
        elif service_key == "image_to_3d" or supports_mv:
            if not (image or prompt):
                self.report(
                    {"WARNING"},
                    "Provide at least one of: prompt, image, or multiple views",
                )
                return {"CANCELLED"}
        elif service_key == "hunyuan_rapid":
            if not (image or prompt):
                self.report({"WARNING"}, "Provide either a prompt or an image")
                return {"CANCELLED"}
        else:
            if not image:
                self.report({"WARNING"}, "Please add an input image")
                return {"CANCELLED"}

        # --- Base payload (image / multi-view) ---
        payload = {}
        if turnaround_payload:
            payload.update(turnaround_payload)
        elif image is not None:
            try:
                if service_key == "model_3d":
                    image_bytes = compress_for_service(image, "image_to_3d")
                else:
                    image_bytes = compress_image_for_upload(image)
            except Exception as e:
                self.report({"ERROR"}, f"Failed to process image: {e}")
                return {"CANCELLED"}
            if image_bytes:
                payload["image_bytes_b64"] = _b64.b64encode(image_bytes).decode()
                payload["image_filename"] = "image.png"

        # --- Catalog params -> wire payload (per-service assembler) ---
        params = {}
        try:
            params = collect_params(service_key, model)
        except Exception as e:
            logger.debug("collect_params failed for %s/%s: %s",
                         service_key, model, e)
        if prompt:
            if service_key == "image_to_3d":
                params["prompt"] = prompt
            elif service_key == "hunyuan_rapid":
                # Rapid: prompt and image are mutually exclusive on the wire.
                if image is None:
                    params["prompt"] = prompt
            else:
                payload["prompt"] = prompt
        payload = assemble_payload(service_key, params, payload, model)

        # --- Enqueue ---
        route = _routing(service_key)
        feature_key = route.pop("feature_key")
        label = image.name if image else ((prompt or model)[:40])

        # Name the imported mesh from the input image (or a prompt slug for
        # text-to-3D) and normalize its placement. Overrides any service
        # default hook (e.g. image_to_3d's legacy "_high" rename) so every
        # Model Gen provider names + grounds its result consistently.
        from mixar.modules.moodboard.core.generation_enqueue import (
            derive_model_name, make_model_rename_on_imported, model_front_zrot,
        )
        mesh_name = derive_model_name(image, prompt or "")
        route["on_imported"] = make_model_rename_on_imported(
            mesh_name, model_front_zrot(model))

        try:
            from mixar.modules.common.job_queue import enqueue_generation

            job = enqueue_generation(
                kind="glb",
                feature_key=feature_key,
                job_type=service_key,
                model=model,
                payload=payload,
                label=label,
                **route,
            )
            if not job:
                self.report({"WARNING"}, "A duplicate generation is already queued")
                return {"CANCELLED"}
        except Exception as e:
            self.report({"ERROR"}, f"Failed to start generation: {e}")
            return {"CANCELLED"}

        from mixar.modules.common.job_queue.ui.lists.queue_uilist import (
            mark_enqueued,
        )
        mark_enqueued(feature_key)
        self.report({"INFO"}, "Added to queue")
        return {"FINISHED"}


classes = (
    MIXIE_OT_model_gen_generate,
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
