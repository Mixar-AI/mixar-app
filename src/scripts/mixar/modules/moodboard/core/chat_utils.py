# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Chat Utilities for Moodboard

Functions for retrieving chat message data for use with moodboard operations.
"""

import bpy
from typing import TypedDict


class ImageInfo(TypedDict):
    """Type definition for image information dictionary."""
    image: bpy.types.Image | None
    image_path: str
    image_source: str
    display_name: str
    width: int
    height: int
    channels: int
    has_data: bool
    is_packed: bool
    is_dirty: bool
    file_format: str
    colorspace: str
    filepath: str


class LastUserMessageResult(TypedDict):
    """Type definition for get_last_user_message return value."""
    found: bool
    text: str
    images: list[ImageInfo]
    message_index: int


def get_last_user_message(context: bpy.types.Context = None) -> LastUserMessageResult:
    """
    Get the last message sent by the user in Mixie Chat.

    Retrieves the text content and all attached image details from the most
    recent user message. Image details include all information needed to pass
    to moodboard generation operators.

    Args:
        context: Blender context (uses bpy.context if None)

    Returns:
        Dictionary containing:
        - found: bool - Whether a user message was found
        - text: str - The message text content
        - images: list - Array of image info dictionaries with:
            - image: bpy.types.Image or None - The actual image reference
            - image_path: str - Path or blend data name
            - image_source: str - 'FILE' or 'BLEND_DATA'
            - display_name: str - Display name for UI
            - width: int - Image width in pixels
            - height: int - Image height in pixels
            - channels: int - Number of color channels
            - has_data: bool - Whether image has pixel data loaded
            - is_packed: bool - Whether image is packed into blend file
            - is_dirty: bool - Whether image has unsaved changes
            - file_format: str - File format (PNG, JPEG, etc.)
            - colorspace: str - Colorspace name
            - filepath: str - Full file path (empty for generated images)
        - message_index: int - Index of the message in chat history (-1 if not found)
    """
    if context is None:
        context = bpy.context

    result: LastUserMessageResult = {
        "found": False,
        "text": "",
        "images": [],
        "message_index": -1
    }

    scene = context.scene

    # Check if chat messages property exists
    if not hasattr(scene, "mixie_chat_messages"):
        return result

    messages = scene.mixie_chat_messages

    if not messages:
        return result

    # Find the last user message (iterate backwards)
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg.sender == 'USER':
            result["found"] = True
            result["text"] = msg.text
            result["message_index"] = i

            # Process attachments
            for attachment in msg.attachments:
                image_info = _get_image_info(attachment)
                result["images"].append(image_info)

            break

    return result


def _get_image_info(attachment) -> ImageInfo:
    """
    Extract detailed image information from a chat attachment.

    Args:
        attachment: MixieChatAttachment property group

    Returns:
        ImageInfo dictionary with all image details
    """
    image_info: ImageInfo = {
        "image": None,
        "image_path": attachment.image_path,
        "image_source": attachment.image_source,
        "display_name": attachment.display_name,
        "width": 0,
        "height": 0,
        "channels": 0,
        "has_data": False,
        "is_packed": False,
        "is_dirty": False,
        "file_format": "",
        "colorspace": "",
        "filepath": ""
    }

    # Try to get the actual image reference
    img = None

    if attachment.image_source == 'BLEND_DATA':
        # Image is stored in blend data, look up by name
        img = bpy.data.images.get(attachment.image_path)
    elif attachment.image_source == 'FILE':
        # Image is from file system, try to find by filepath
        for candidate in bpy.data.images:
            if candidate.filepath == attachment.image_path:
                img = candidate
                break
            # Also check absolute path
            if bpy.path.abspath(candidate.filepath) == attachment.image_path:
                img = candidate
                break

    if img:
        image_info["image"] = img
        image_info["width"] = img.size[0]
        image_info["height"] = img.size[1]
        image_info["channels"] = img.channels
        image_info["has_data"] = img.has_data
        image_info["is_packed"] = img.packed_file is not None
        image_info["is_dirty"] = img.is_dirty
        image_info["file_format"] = img.file_format
        image_info["filepath"] = img.filepath

        # Get colorspace name safely
        if img.colorspace_settings:
            image_info["colorspace"] = img.colorspace_settings.name

    return image_info


def get_user_message_images_for_generation(
    context: bpy.types.Context = None
) -> list[bpy.types.Image]:
    """
    Get a list of valid bpy.types.Image objects from the last user message.

    Convenience function that filters to only images that have data loaded
    and returns the actual image references for direct use in operators.

    Args:
        context: Blender context (uses bpy.context if None)

    Returns:
        List of bpy.types.Image objects that are ready for use
    """
    result = get_last_user_message(context)

    images = []
    for img_info in result["images"]:
        if img_info["image"] and img_info["has_data"]:
            images.append(img_info["image"])

    return images
