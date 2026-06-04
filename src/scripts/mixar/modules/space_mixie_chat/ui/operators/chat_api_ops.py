# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixie Chat API Operators

Programmatic API for manipulating chat messages.
Provides operators for adding, editing, removing messages.
"""

import bpy
from bpy.types import Operator
from bpy.props import EnumProperty, StringProperty, IntProperty

from ...core import cleanup_loaded_file_images, collect_message_file_image_paths
from ...core.ui_utils import redraw_chat_areas


class MIXIE_CHAT_OT_add_message(Operator):
    """Add a message to the chat programmatically"""
    bl_idname = "mixie_chat.add_message"
    bl_label = "Add Message"
    bl_description = "Add a new message to the chat"
    bl_options = {'REGISTER'}

    sender: EnumProperty(
        name="Sender",
        items=[
            ('USER', "User", "Message from user"),
            ('AGENT', "Agent", "Message from AI agent")
        ],
        default='AGENT'
    )
    text: StringProperty(
        name="Text",
        description="Message content",
        default=""
    )
    message_type: EnumProperty(
        name="Type",
        items=[
            ('AGENT', "Agent", "Agent response message"),
            ('LOADING', "Loading", "Loading indicator with spinner"),
            ('TODO', "Todo", "To-do list with checkable items"),
            ('PROMPT', "Prompt", "User input prompt with options")
        ],
        default='AGENT'
    )
    metadata: StringProperty(
        name="Metadata",
        description="JSON metadata for special message types",
        default="{}"
    )

    def execute(self, context):
        scene = context.scene

        # Add new message
        msg = scene.mixie_chat_messages.add()
        msg.sender = self.sender
        msg.text = self.text
        msg.message_type = self.message_type
        msg.metadata = self.metadata

        # Trigger redraw in all Mixie Chat areas
        redraw_chat_areas()

        return {'FINISHED'}


class MIXIE_CHAT_OT_clear_messages(Operator):
    """Clear all messages from the chat"""
    bl_idname = "mixie_chat.clear_messages"
    bl_label = "Clear Messages"
    bl_description = "Remove all messages from the chat"
    bl_options = {'REGISTER'}

    def execute(self, context):
        scene = context.scene
        paths = []
        for msg in scene.mixie_chat_messages:
            paths.extend(collect_message_file_image_paths(msg))
        scene.mixie_chat_messages.clear()
        cleanup_loaded_file_images(paths)
        # Re-arm the empty-state greeting now that the chat is empty.
        if hasattr(scene, "mixie_chat_user_has_engaged"):
            scene.mixie_chat_user_has_engaged = False

        # Clear incremental markdown cache (prevents unbounded growth)
        from ...core.markdown_parser import clear_incremental_cache
        clear_incremental_cache()

        # Trigger redraw in all Mixie Chat areas
        redraw_chat_areas()

        return {'FINISHED'}


class MIXIE_CHAT_OT_edit_message(Operator):
    """Edit an existing message in the chat"""
    bl_idname = "mixie_chat.edit_message"
    bl_label = "Edit Message"
    bl_description = "Modify an existing message"
    bl_options = {'REGISTER'}

    index: IntProperty(
        name="Index",
        description="Message index to edit",
        default=-1
    )
    text: StringProperty(
        name="Text",
        description="New message text (empty to keep current)",
        default=""
    )
    metadata: StringProperty(
        name="Metadata",
        description="New metadata (empty to keep current)",
        default=""
    )

    def execute(self, context):
        scene = context.scene
        messages = scene.mixie_chat_messages

        # Validate index
        if self.index < 0 or self.index >= len(messages):
            self.report({'ERROR'}, f"Invalid message index: {self.index}")
            return {'CANCELLED'}

        msg = messages[self.index]

        # Update fields if provided
        if self.text:
            msg.text = self.text
        if self.metadata:
            msg.metadata = self.metadata

        # Trigger redraw in all Mixie Chat areas
        redraw_chat_areas()

        return {'FINISHED'}


class MIXIE_CHAT_OT_remove_message(Operator):
    """Remove a message from the chat"""
    bl_idname = "mixie_chat.remove_message"
    bl_label = "Remove Message"
    bl_description = "Delete a message from the chat"
    bl_options = {'REGISTER'}

    index: IntProperty(
        name="Index",
        description="Message index to remove",
        default=-1
    )

    def execute(self, context):
        scene = context.scene
        messages = scene.mixie_chat_messages

        # Validate index
        if self.index < 0 or self.index >= len(messages):
            self.report({'ERROR'}, f"Invalid message index: {self.index}")
            return {'CANCELLED'}

        paths = collect_message_file_image_paths(messages[self.index])
        messages.remove(self.index)
        cleanup_loaded_file_images(paths)

        # Trigger redraw in all Mixie Chat areas
        redraw_chat_areas()

        return {'FINISHED'}


class MIXIE_CHAT_OT_add_image(Operator):
    """Add an image attachment to a message"""
    bl_idname = "mixie_chat.add_image"
    bl_label = "Add Image"
    bl_description = "Add an image attachment to a message"
    bl_options = {'REGISTER'}

    image_path: StringProperty(
        name="Image Path",
        description="Path to the image file",
        default="",
        subtype='FILE_PATH'
    )
    message_index: IntProperty(
        name="Message Index",
        description="Index of target message (-1 = last, -2 = new message)",
        default=-1
    )
    display_name: StringProperty(
        name="Display Name",
        description="Display name for the attachment (optional)",
        default=""
    )

    def execute(self, context):
        scene = context.scene
        messages = scene.mixie_chat_messages

        # Determine target message
        if self.message_index == -2 or len(messages) == 0:
            # Create new message for image
            msg = messages.add()
            msg.sender = 'USER'
            msg.text = ""
        elif self.message_index == -1:
            # Use last message
            if len(messages) == 0:
                self.report({'ERROR'}, "No messages available")
                return {'CANCELLED'}
            msg = messages[-1]
        else:
            # Use specific index
            if self.message_index < 0 or self.message_index >= len(messages):
                self.report({'ERROR'}, f"Invalid message index: {self.message_index}")
                return {'CANCELLED'}
            msg = messages[self.message_index]

        # Add attachment
        att = msg.attachments.add()
        att.image_path = self.image_path
        att.image_source = 'FILE'
        att.display_name = self.display_name if self.display_name else self.image_path

        # Trigger redraw in all Mixie Chat areas
        redraw_chat_areas()

        return {'FINISHED'}


classes = (
    MIXIE_CHAT_OT_add_message,
    MIXIE_CHAT_OT_clear_messages,
    MIXIE_CHAT_OT_edit_message,
    MIXIE_CHAT_OT_remove_message,
    MIXIE_CHAT_OT_add_image,
)
