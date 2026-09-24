# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Canvas frame property group.

A frame is a **first-class canvas object**: its own rect, name, colour and
stable id, like a Blender node frame or a Figma/FigJam frame. It is NOT a
bounding box derived from its members, which is what the legacy
``MixieMoodboardGroup`` + ``group_index`` pair was -- and which is why that
could not be empty, could not be moved to open canvas, could not be resized,
and drew nothing at all unless something inside it happened to be selected.

Membership lives on the ITEM (``frame_id``), resolved from geometry when an
item is dropped. A stable string id rather than a collection index: removing
one group used to mean renumbering every higher ``group_index`` by hand, and
three separate operators each carried their own copy of that loop.
"""

from bpy.types import PropertyGroup
from bpy.props import (
    BoolProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    StringProperty,
)

from mixar.modules.moodboard.constants import (
    FRAME_DEFAULT_HEIGHT,
    FRAME_DEFAULT_WIDTH,
    FRAME_MIN_HEIGHT,
    FRAME_MIN_WIDTH,
    FRAME_NAME_MAXLEN,
    FRAME_PALETTE_SIZE,
    GRAPH_NODE_ID_MAXLEN,
)


class MixieMoodboardFrame(PropertyGroup):
    """One frame on the moodboard canvas."""

    # Stable identity. Every member points back at this, so deleting a frame
    # can never repoint another frame's membership.
    frame_id: StringProperty(
        name="Frame ID",
        description="Stable identifier members refer to",
        default="",
        maxlen=GRAPH_NODE_ID_MAXLEN,
    )
    name: StringProperty(
        name="Name",
        description="Frame name, painted above its top-left corner",
        default="Frame",
        maxlen=FRAME_NAME_MAXLEN,
    )
    # The frame's OWN rect, in canvas units; (position_x, position_y) is the
    # bottom-left corner, matching every other board item.
    position_x: FloatProperty(name="Position X", default=0.0)
    position_y: FloatProperty(name="Position Y", default=0.0)
    width: FloatProperty(
        name="Width", default=FRAME_DEFAULT_WIDTH, min=FRAME_MIN_WIDTH, max=100000.0
    )
    height: FloatProperty(
        name="Height", default=FRAME_DEFAULT_HEIGHT, min=FRAME_MIN_HEIGHT, max=100000.0
    )
    # An INDEX into FRAME_PALETTE, not an RGBA: the palette can be retuned and
    # saved boards follow it, and two frames can never end up with colours that
    # are merely near each other.
    palette_index: IntProperty(
        name="Colour",
        description="Which of the frame palette's pastels this frame wears",
        default=0,
        min=0,
        max=FRAME_PALETTE_SIZE - 1,
    )
    # Escape hatch only; the palette is the norm. `custom_color` is ignored
    # unless `use_custom_color` is on, so turning the flag off restores the
    # palette colour rather than losing it.
    use_custom_color: BoolProperty(name="Use Custom Colour", default=False)
    custom_color: FloatVectorProperty(
        name="Custom Colour",
        subtype='COLOR',
        size=3,
        default=(0.65, 0.77, 0.94),
        min=0.0,
        max=1.0,
    )
    selected: BoolProperty(name="Selected", default=False)
    locked: BoolProperty(
        name="Locked",
        description="Ignore this frame's border and interior when clicking, so "
        "only its members can be selected",
        default=False,
    )
    collapsed: BoolProperty(
        name="Collapsed",
        description="Draw the frame as a titled bar and hide its body",
        default=False,
    )


# Deliberately NO module-level `classes` tuple: like every other moodboard
# PropertyGroup, this one is registered by `moodboard_scene_registration.py`
# alongside the scene collection that holds it. Exposing `classes` here would
# have the UI auto-discovery register it a second time.
