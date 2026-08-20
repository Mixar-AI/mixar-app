# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Generate Mode Handlers for Mixie Chat.

Module-level functions for each generate sub-type. Called from
MIXIE_CHAT_OT_send_message.execute() when the chat mode is GENERATE.

The generate type (``scene.mixie_chat_generate_type``) is catalog-driven:
identifiers are generation-catalog service keys served by
``/generation-catalog/chat-options`` (see chat_generate_options_cache).
Routing:

- ``depth_to_image``       → lookdev scene render (mixie.lookdev_generate_from_scene)
- ``pbr_gen``              → 360 PBR textures (mixie.lookdev360_generate)
- ``model_3d``             → Image to 3D (mixie.image_to_3d_generate)
- ``image_to_3d``          → Image to 3D Pro — queued directly (job queue)
- ``hunyuan_rapid``        → Rapid 3D — queued directly (job queue)
- ``image_gen``            → Text to Image (mixie.imagegen_generate)
- ``scene_reconstruction`` → 3D scene (mixie.scene_recon_generate)
"""

import bpy

from mixar.config.logging_config import get_logger

from ...core.message_helpers import add_agent_message, add_slot_loader
from ...core.generation_poller import register_generation_poll
from ...core.ui_utils import redraw_chat_areas

logger = get_logger(__name__)

# Legacy enum identifiers (pre catalog-driven dropdown) → service keys.
# Saved keymaps or agent scripts may still hand us the old ids.
_GEN_TYPE_ALIASES = {
    "IMAGE_GEN": "image_gen",
    "IMAGE_TO_3D": "model_3d",
    "LOOKDEV": "depth_to_image",
    "LOOKDEV_360": "pbr_gen",
    "SCENE_RECON": "scene_reconstruction",
}


def normalize_generate_service(value: str) -> str:
    """Map a generate-type value (legacy id or service key) to a service key."""
    return _GEN_TYPE_ALIASES.get(value or "", value or "")


def _chosen_model(scene, service_key):
    """The model slug picked via the in-chat "which model?" ask, if it
    names one of *service_key*'s current models — else "" (use default)."""
    slug = (getattr(scene, "mixie_chat_generate_model", "") or "").strip()
    if not slug:
        return ""
    try:
        from mixar.bootstrap.chat_generate_options_cache import get_option
        models = (get_option(service_key) or {}).get("models") or []
        if any(m.get("slug") == slug for m in models):
            return slug
    except Exception:
        pass
    try:
        from mixar.bootstrap.generation_catalog_cache import get_model
        if get_model(service_key, slug):
            return slug
    except Exception:
        pass
    return ""


def _deselect_moodboard_origin(scene) -> None:
    """Deselect moodboard images for any is_moodboard attachments in
    pending so the moodboard sync doesn't re-add them on the next poll
    after we clear pending_attachments. Lazy import so the chat module
    doesn't carry a hard dep on moodboard at load time."""
    try:
        from mixar.modules.moodboard.core.chat_sync import (
            deselect_all_moodboard_origin_attachments,
        )
        deselect_all_moodboard_origin_attachments(scene)
    except Exception as e:  # noqa: BLE001 — never block the send path
        logger.debug(
            "moodboard deselect on generate send skipped: %s",
            e, exc_info=True,
        )


def execute_generate_mode(operator, context):
    """Handle message sending in Generate mode - routes to sub-type handler.

    Args:
        operator: The calling Blender operator (for self.report())
        context: Blender context

    Returns:
        Blender operator return set ({'FINISHED'} or {'CANCELLED'})
    """
    scene = context.scene
    gen_type = normalize_generate_service(scene.mixie_chat_generate_type)
    prompt = scene.mixie_chat_input.strip()
    pending_attachments = scene.mixie_chat_pending_attachments

    try:
        from mixar.bootstrap.chat_generate_options_cache import get_service_keys
        available_services = get_service_keys()
    except Exception:
        available_services = []
    if not gen_type or gen_type not in available_services:
        operator.report(
            {'WARNING'},
            "Generation is currently unavailable. Refresh the catalog and try again.",
        )
        return {'CANCELLED'}

    # Same flag the agent send path sets — without it a generate-only
    # session lets the "Hi I'm Mixie" empty-state greeting reappear.
    scene.mixie_chat_user_has_engaged = True

    # Add user message to history (if there's a prompt)
    if prompt:
        user_msg = scene.mixie_chat_messages.add()
        user_msg.sender = 'USER'
        user_msg.text = prompt

        # Copy attachments to message history
        for att in pending_attachments:
            msg_att = user_msg.attachments.add()
            msg_att.image_path = att.image_path
            msg_att.image_source = att.image_source
            msg_att.display_name = att.display_name

    # Route to appropriate handler (keys are catalog service keys)
    if gen_type == 'depth_to_image':
        return _handle_lookdev(operator, context, prompt)
    elif gen_type == 'pbr_gen':
        return _handle_lookdev_360(operator, context, prompt)
    elif gen_type == 'model_3d':
        return _handle_image_to_3d(operator, context, prompt, pending_attachments)
    elif gen_type in ('image_to_3d', 'hunyuan_rapid'):
        return _handle_model_gen_queue(
            operator, context, gen_type, prompt, pending_attachments)
    elif gen_type == 'image_gen':
        return _handle_image_gen(operator, context, prompt, pending_attachments)
    elif gen_type == 'scene_reconstruction':
        return _handle_scene_recon(operator, context, prompt, pending_attachments)

    operator.report({'WARNING'}, f"Unknown generate type: {gen_type}")
    return {'CANCELLED'}


def _handle_lookdev(operator, context, prompt):
    """Handle Lookdev generation - renders scene depth and generates images."""
    scene = context.scene

    if not prompt:
        add_agent_message(scene, "Please enter a prompt describing the scene you want to generate.")
        return {'CANCELLED'}

    scene.mixie_lookdev_prompt = prompt
    bubble_id = add_slot_loader(scene, "Generating lookdev image from scene")

    bpy.ops.mixie.lookdev_generate_from_scene(from_chat=True)

    register_generation_poll(
        scene, bubble_id,
        is_generating_attr="mixie_lookdev_is_generating",
        error_attr="mixie_lookdev_error",
        success_message="Check moodboard for the output.",
    )

    scene.mixie_chat_input = ""
    redraw_chat_areas()
    return {'FINISHED'}


def _handle_lookdev_360(operator, context, prompt):
    """Handle Lookdev 360 generation - generates textures for selected meshes."""
    scene = context.scene

    mesh_objects = [obj for obj in context.selected_objects if obj.type == 'MESH']
    if not mesh_objects:
        add_agent_message(scene, "Please select mesh objects in the 3D viewport before generating.")
        return {'CANCELLED'}

    if not prompt:
        add_agent_message(scene, "Please enter a prompt describing the texture style.")
        return {'CANCELLED'}

    scene.mixie_lookdev360_prompt = prompt
    bubble_id = add_slot_loader(scene, "Generating 360 textures for selected meshes")

    bpy.ops.mixie.lookdev360_generate(from_chat=True)

    register_generation_poll(
        scene, bubble_id,
        is_generating_attr="mixie_lookdev360_is_generating",
        error_attr="mixie_lookdev360_error",
        success_message="Textures generated and applied to selected meshes.",
    )

    scene.mixie_chat_input = ""
    redraw_chat_areas()
    return {'FINISHED'}


def _handle_image_to_3d(operator, context, prompt, pending_attachments):
    """Handle Image to 3D generation - generates 3D model from attached or selected image."""
    scene = context.scene

    img, used_attachment = _resolve_chat_input_image(context, pending_attachments)

    if not img:
        add_agent_message(
            scene,
            "Please attach a reference image or select one in the moodboard."
        )
        return {'CANCELLED'}

    scene.mixie_image_to_3d_image = img
    scene.mixie_image_to_3d_prompt = prompt or ""
    scene.mixie_image_to_3d_use_selected = False

    bubble_id = add_slot_loader(scene, "Generating 3D model from image")

    # model="" lets the operator fall back to the catalog default.
    bpy.ops.mixie.image_to_3d_generate(
        from_chat=True, model=_chosen_model(scene, "model_3d"))

    register_generation_poll(
        scene, bubble_id,
        is_generating_attr="mixie_image_to_3d_is_generating",
        error_attr="mixie_image_to_3d_error",
        success_message="3D model generated and imported into the viewport.",
    )

    scene.mixie_chat_input = ""
    if used_attachment:
        _deselect_moodboard_origin(scene)
        pending_attachments.clear()
    redraw_chat_areas()
    return {'FINISHED'}


def _resolve_chat_input_image(context, pending_attachments):
    """First pending attachment as a bpy Image, else the selected
    moodboard image. Returns (image, used_attachment)."""
    img = None
    used_attachment = False

    if len(pending_attachments) > 0:
        att = pending_attachments[0]
        if att.image_source == 'FILE':
            img = bpy.data.images.load(att.image_path, check_existing=True)
            img.colorspace_settings.name = 'sRGB'
        else:
            img = bpy.data.images.get(att.image_path)
        used_attachment = True

    if not img:
        try:
            from mixar.modules.moodboard.ui.sidebar_ui_helpers import (
                get_selected_moodboard_image,
            )
            img = get_selected_moodboard_image(context)
        except ImportError:
            pass

    return img, used_attachment


def _handle_model_gen_queue(operator, context, service_key, prompt,
                            pending_attachments):
    """Handle Image to 3D Pro / Rapid 3D — enqueue through the job queue.

    Mirrors the moodboard's MIXIE_OT_model_gen_generate routing for the
    ``image_to_3d`` (Hunyuan Pro) and ``hunyuan_rapid`` services, with the
    chat composer's inputs (pending attachment / selected moodboard image
    + prompt) instead of the Model Gen tab state.
    """
    import base64 as _b64

    scene = context.scene

    img, used_attachment = _resolve_chat_input_image(context, pending_attachments)

    if not img and not prompt:
        add_agent_message(
            scene,
            "Attach a reference image or enter a prompt describing the model."
        )
        return {'CANCELLED'}

    # Model: the in-chat choice when one was made, else the service's
    # catalog default (chat options first, then the full catalog).
    model = _chosen_model(scene, service_key) or None
    if not model:
        try:
            from mixar.bootstrap.chat_generate_options_cache import (
                get_default_model_slug,
            )
            model = get_default_model_slug(service_key)
        except Exception:
            pass
    if not model:
        try:
            from mixar.bootstrap.generation_catalog_cache import (
                get_default_model_slug as _catalog_default,
            )
            model = _catalog_default(service_key)
        except Exception:
            pass
    if not model:
        add_agent_message(
            scene, "Generation catalog not loaded yet — please retry shortly."
        )
        return {'CANCELLED'}

    # --- Payload (image + prompt placement mirrors model_gen_ops) ---
    payload = {}
    if img is not None:
        try:
            from mixar.modules.common.utils.image_utils import (
                compress_image_for_upload,
            )
            image_bytes = compress_image_for_upload(img)
        except Exception as e:
            add_agent_message(scene, f"Failed to process the image: {e}")
            return {'CANCELLED'}
        if image_bytes:
            payload["image_bytes_b64"] = _b64.b64encode(image_bytes).decode()
            payload["image_filename"] = "image.png"

    params = {}
    try:
        from mixar.modules.common.generation_params import collect_params
        params = collect_params(service_key, model)
    except Exception as e:
        logger.debug("collect_params failed for %s/%s: %s", service_key, model, e)
    if prompt:
        if service_key == "image_to_3d":
            params["prompt"] = prompt
        elif img is None:
            # Rapid: prompt and image are mutually exclusive on the wire.
            params["prompt"] = prompt
    try:
        from mixar.modules.common.generation_params import assemble_payload
        payload = assemble_payload(service_key, params, payload, model)
    except Exception as e:
        logger.debug("assemble_payload failed for %s: %s", service_key, e)

    # --- Per-service enqueue routing (mirrors model_gen_ops._routing) ---
    from mixar.modules.common.job_queue.constants import (
        FEATURE_HUNYUAN_RAPID,
        FEATURE_IMAGE_TO_3D_PRO,
    )
    if service_key == "image_to_3d":
        feature_key = FEATURE_IMAGE_TO_3D_PRO
        scene_flag = "mixie_image_to_3d_is_generating"
        error_attr = "mixie_image_to_3d_error"
        loader_text = "Generating 3D model (Pro)"
    else:
        feature_key = FEATURE_HUNYUAN_RAPID
        scene_flag = "mixie_hunyuan_rapid_is_generating"
        error_attr = "mixie_hunyuan_rapid_error"
        loader_text = "Generating 3D model (Rapid)"

    # Name the imported mesh from the input image (or a prompt slug for
    # text-to-3D) and normalize its placement — same as model_gen_ops.
    route_extra = {}
    try:
        from mixar.modules.moodboard.core.generation_enqueue import (
            derive_model_name, make_model_rename_on_imported, model_front_zrot,
        )
        mesh_name = derive_model_name(img, prompt or "")
        route_extra["on_imported"] = make_model_rename_on_imported(
            mesh_name, model_front_zrot(model))
    except Exception as e:
        logger.debug("Failed to attach 3D naming hook: %s", e)

    bubble_id = add_slot_loader(scene, loader_text)

    label = img.name if img else ((prompt or model)[:40])
    try:
        from mixar.modules.common.job_queue import enqueue_generation

        job = enqueue_generation(
            kind="glb",
            feature_key=feature_key,
            job_type=service_key,
            model=model,
            payload=payload,
            label=label,
            fail_message="3D model generation failed",
            scene_flag=scene_flag,
            **route_extra,
        )
        if not job:
            add_agent_message(scene, "A duplicate generation is already queued.")
            return {'CANCELLED'}
    except Exception as e:
        logger.error("Chat %s enqueue failed: %s", service_key, e, exc_info=True)
        add_agent_message(scene, f"Failed to start generation: {e}")
        return {'CANCELLED'}

    register_generation_poll(
        scene, bubble_id,
        is_generating_attr=scene_flag,
        error_attr=error_attr,
        success_message="3D model generated and imported into the viewport.",
    )

    scene.mixie_chat_input = ""
    if used_attachment:
        _deselect_moodboard_origin(scene)
        pending_attachments.clear()
    redraw_chat_areas()
    return {'FINISHED'}


def _handle_image_gen(operator, context, prompt, pending_attachments):
    """Handle Image Gen - generates AI image from prompt, optionally with reference images."""
    scene = context.scene

    if not prompt:
        add_agent_message(scene, "Please enter a prompt describing the image you want to generate.")
        return {'CANCELLED'}

    # Load attached images into the ref images collection for the operator to pick up
    scene.mixie_imagegen_ref_images.clear()
    used_attachment = False
    if len(pending_attachments) > 0:
        for att in pending_attachments:
            if att.image_source == 'FILE':
                img = bpy.data.images.load(att.image_path, check_existing=True)
                img.colorspace_settings.name = 'sRGB'
            else:
                img = bpy.data.images.get(att.image_path)
            if img:
                ref_item = scene.mixie_imagegen_ref_images.add()
                ref_item.image = img
        used_attachment = True

    scene.mixie_imagegen_prompt = prompt
    bubble_id = add_slot_loader(scene, "Generating image")

    # model="" lets the operator fall back to the catalog default.
    bpy.ops.mixie.imagegen_generate(
        from_chat=True, model=_chosen_model(scene, "image_gen"))

    register_generation_poll(
        scene, bubble_id,
        is_generating_attr="mixie_imagegen_is_generating",
        error_attr="mixie_imagegen_error",
        success_message="Check moodboard for the generated image.",
    )

    scene.mixie_chat_input = ""
    if used_attachment:
        _deselect_moodboard_origin(scene)
        pending_attachments.clear()
    redraw_chat_areas()
    return {'FINISHED'}


def _handle_scene_recon(operator, context, prompt, pending_attachments):
    """Handle Scene Reconstruction - generates 3D scene from prompt and/or image."""
    scene = context.scene
    has_image = len(pending_attachments) > 0

    if not prompt and not has_image:
        add_agent_message(
            scene,
            "Please enter a prompt describing the scene, or attach an image to reconstruct."
        )
        return {'CANCELLED'}

    # Load attached image if present
    chat_image_name = ""
    if has_image:
        att = pending_attachments[0]
        if att.image_source == 'FILE':
            img = bpy.data.images.load(att.image_path, check_existing=True)
            img.colorspace_settings.name = 'sRGB'
        else:
            img = bpy.data.images.get(att.image_path)

        if not img:
            add_agent_message(scene, "Failed to load the attached image.")
            return {'CANCELLED'}

        chat_image_name = img.name

    if has_image:
        bubble_id = add_slot_loader(scene, "Generating 3D scene from image")
    else:
        bubble_id = add_slot_loader(scene, "Generating 3D scene from description")

    bpy.ops.mixie.scene_recon_generate(
        from_chat=True,
        chat_prompt=prompt or "",
        chat_image_name=chat_image_name,
    )

    register_generation_poll(
        scene, bubble_id,
        is_generating_attr="mixie_scene_recon_is_generating",
        error_attr="mixie_scene_recon_error",
        success_message="3D scene generated and imported into the viewport.",
    )

    scene.mixie_chat_input = ""
    if has_image:
        _deselect_moodboard_origin(scene)
        pending_attachments.clear()
    redraw_chat_areas()
    return {'FINISHED'}
