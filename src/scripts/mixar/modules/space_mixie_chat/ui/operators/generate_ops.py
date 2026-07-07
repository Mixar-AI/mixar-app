# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Generate Mode Handlers for Mixie Chat.

Module-level functions for each generate sub-type (Lookdev, Lookdev 360,
Image-to-3D, Image Gen, Scene Recon). Called from MIXIE_CHAT_OT_send_message.execute()
when the chat mode is GENERATE.
"""

import bpy

from mixar.config.logging_config import get_logger

from ...core.message_helpers import add_agent_message, add_slot_loader
from ...core.generation_poller import register_generation_poll
from ...core.ui_utils import redraw_chat_areas

logger = get_logger(__name__)


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
    gen_type = scene.mixie_chat_generate_type
    prompt = scene.mixie_chat_input.strip()
    pending_attachments = scene.mixie_chat_pending_attachments

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

    # Route to appropriate handler
    if gen_type == 'LOOKDEV':
        return _handle_lookdev(operator, context, prompt)
    elif gen_type == 'LOOKDEV_360':
        return _handle_lookdev_360(operator, context, prompt)
    elif gen_type == 'IMAGE_TO_3D':
        return _handle_image_to_3d(operator, context, prompt, pending_attachments)
    elif gen_type == 'IMAGE_GEN':
        return _handle_image_gen(operator, context, prompt, pending_attachments)
    elif gen_type == 'SCENE_RECON':
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

    img = None
    used_attachment = False

    # Try attached image first
    if len(pending_attachments) > 0:
        att = pending_attachments[0]
        if att.image_source == 'FILE':
            img = bpy.data.images.load(att.image_path, check_existing=True)
            img.colorspace_settings.name = 'sRGB'
        else:
            img = bpy.data.images.get(att.image_path)
        used_attachment = True

    # Fall back to selected moodboard image
    if not img:
        try:
            from mixar.modules.moodboard.ui.sidebar_ui_helpers import (
                get_selected_moodboard_image,
            )
            img = get_selected_moodboard_image(context)
        except ImportError:
            pass

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

    bpy.ops.mixie.image_to_3d_generate(from_chat=True)

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

    bpy.ops.mixie.imagegen_generate(from_chat=True)

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
