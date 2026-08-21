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
    BoolProperty,
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
        default="",
        # Must match TodoItemSlotData::id (char[64]) in
        # mixie_chat_ui_types.hh — the C++ slot reader copies this string
        # into that fixed buffer.
        maxlen=64
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
    # Asset-picker fields (multi-match HITL). The asset_* identity comes from
    # the wire; `image` is set LOCALLY ONLY by asset_choice_previews after it
    # generates/finds the preview in bpy.data.images — never from the backend.
    image: StringProperty(
        name="Preview Image",
        description="bpy.data.images name of the locally generated preview "
                    "thumbnail (empty = plain text button)",
        default="",
        # Must match ActionSlotData::image (char[64]) in mixie_chat_ui_types.hh
        # — the C++ slot reader copies this string into that fixed buffer.
        maxlen=64
    )
    asset_name: StringProperty(
        name="Asset Name",
        description="Library asset (object/collection) name inside the .blend",
        default="",
        maxlen=256
    )
    library: StringProperty(
        name="Library",
        description="Asset library name (preferences.filepaths.asset_libraries)",
        default="",
        maxlen=256
    )
    blend_file: StringProperty(
        name="Blend File",
        description="Library-relative .blend path holding the asset",
        default="",
        maxlen=1024
    )
    asset_type: StringProperty(
        name="Asset Type",
        description="Asset type hint from search metadata",
        default="",
        maxlen=32
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


class MixieChatStepItem(PropertyGroup):
    """Property group for a single tool-call row in the agent steps block."""
    item_id: StringProperty(
        name="Item ID",
        description="Unique identifier for this step row",
        default="",
        maxlen=63
    )
    # Order MUST stay READ, WRITE, COMMAND, SEARCH, TOOL — the C++ side reads
    # this enum as an int index (RNA_property_enum_get) to pick the row icon.
    kind: EnumProperty(
        name="Kind",
        description="What kind of tool call this row represents",
        items=[
            ('READ', "Read", "File read"),
            ('WRITE', "Write", "File write"),
            ('COMMAND', "Command", "Shell command"),
            ('SEARCH', "Search", "Search / grep"),
            ('TOOL', "Tool", "Generic tool call"),
        ],
        default='TOOL'
    )
    label: StringProperty(
        name="Label",
        description="Row label, e.g. 'Read'",
        default="",
        maxlen=256
    )
    target: StringProperty(
        name="Target",
        description="Row target, e.g. a filename",
        default="",
        maxlen=256
    )
    detail: StringProperty(
        name="Detail",
        description="Second-level detail body (command output / snippet)",
        default="",
        maxlen=4096
    )
    # Order MUST stay PENDING, RUNNING, DONE, FAILED (C++ reads as int index).
    status: EnumProperty(
        name="Status",
        description="Current status of this step",
        items=[
            ('PENDING', "Pending", "Not started"),
            ('RUNNING', "Running", "In progress"),
            ('DONE', "Done", "Completed"),
            ('FAILED', "Failed", "Failed"),
        ],
        default='DONE'
    )
    expanded: BoolProperty(
        name="Expanded",
        description="Whether this row's detail is expanded",
        default=False
    )


classes = (
    MixieChatTodoItem,
    MixieChatActionItem,
    MixieChatImageItem,
    MixieChatStepItem,
)
