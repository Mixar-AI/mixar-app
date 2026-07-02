# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Slot-Based PropertyGroups for Chat Bubbles

These PropertyGroups support the slot-based rendering architecture where
the backend sends declarative UI updates and the frontend simply renders
the slots received.
"""

from bpy.props import (
    EnumProperty,
    FloatProperty,
    StringProperty,
)
from bpy.types import PropertyGroup


class MixieChatTodoItem(PropertyGroup):
    """Property group for a single todo/step item in a chat bubble."""
    item_id: StringProperty(
        name="Item ID",
        description="Unique identifier for this todo item",
        default=""
    )
    text: StringProperty(
        name="Text",
        description="Todo item text",
        default="",
        maxlen=512
    )
    status: EnumProperty(
        name="Status",
        description="Current status of the todo item",
        items=[
            ('PENDING', "Pending", "Task not yet started"),
            ('IN_PROGRESS', "In Progress", "Task is being executed"),
            ('DONE', "Done", "Task completed successfully"),
            ('FAILED', "Failed", "Task failed"),
        ],
        default='PENDING'
    )


class MixieChatActionItem(PropertyGroup):
    """Property group for an action button in a chat bubble."""
    label: StringProperty(
        name="Label",
        description="Button display text",
        default="",
        maxlen=256
    )
    value: StringProperty(
        name="Value",
        description="Value sent when button is clicked",
        default="",
        maxlen=256
    )
    style: EnumProperty(
        name="Style",
        description="Button visual style",
        items=[
            ('PRIMARY', "Primary", "Primary action (highlighted)"),
            ('DEFAULT', "Default", "Default action"),
            ('DANGER', "Danger", "Destructive action (red)"),
        ],
        default='DEFAULT'
    )


class MixieChatImageItem(PropertyGroup):
    """Property group for an image in a chat bubble's image gallery."""
    url: StringProperty(
        name="URL",
        description="Image URL or path",
        default="",
        maxlen=1024
    )
    alt: StringProperty(
        name="Alt Text",
        description="Alternative text for accessibility",
        default="",
        maxlen=256
    )
    caption: StringProperty(
        name="Caption",
        description="Image caption",
        default="",
        maxlen=512
    )
    thumbnail_url: StringProperty(
        name="Thumbnail URL",
        description="Thumbnail URL for preview",
        default="",
        maxlen=1024
    )
    local_path: StringProperty(
        name="Local Path",
        description="Local file path after download",
        default="",
        subtype='FILE_PATH'
    )
    width: FloatProperty(
        name="Width",
        description="Image width in pixels from backend metadata",
        default=0.0,
        min=0.0
    )
    height: FloatProperty(
        name="Height",
        description="Image height in pixels from backend metadata",
        default=0.0,
        min=0.0
    )


classes = (
    MixieChatTodoItem,
    MixieChatActionItem,
    MixieChatImageItem,
)
