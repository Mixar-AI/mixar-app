# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene and WindowManager state for Scribble Marks.

Split by lifetime, which is the whole reason there are two homes:

* **Scene** — the marks themselves, their serial counter, and the name of the
  frozen frame. These belong to the .blend: a mark is a scene noun the agent
  can address turns later, and the vertex groups and cameras it names are
  saved alongside it. Losing them on file reload would make "make it a bit
  taller" unresolvable.
* **WindowManager** — whether mark mode is currently armed, and how the
  user asked the ink to be READ (marks or a sketch). Both describe an
  in-progress gesture, never the saved document; a .blend that reopened
  mid-freeze, with the viewport blocked and no modal running to unblock it,
  would be a file the user could not navigate.

The structured half of each mark is a JSON string rather than nested
PropertyGroups. The payload shape is versioned and shared with the backend
schema; mirroring it into RNA would give it a second definition to drift
against, and every field move would need a .blend migration.
"""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

#: How the user asked the freeze's ink to be read. AUTO is the client's own
#: reading (``core/sketch.py``); the other two override it. A visible,
#: flippable reading is the whole point: a drawing silently taken as nine
#: placement targets is a mode the user could neither see nor correct.
INTENT_ITEMS = (
    ('AUTO', "Auto", "Read from the ink: a few gestures are marks, a drawing "
     "is a sketch", 'AUTO', 0),
    ('SKETCH', "Sketch", "Everything drawn is ONE drawing of what to build, "
     "laid out as drawn", 'GREASEPENCIL', 1),
    ('POINT', "Marks", "Each gesture points at a thing or a spot",
     'RESTRICT_SELECT_OFF', 2),
)


def _on_intent_update(self, context):
    """Re-read the drafts under the new setting and repaint the hint."""
    try:
        from mixar.modules.scribble_mark.core import marks as mark_store, overlay

        mark_store.refresh_reading(context.scene, self)
        overlay.tag_redraw()
    except Exception:  # noqa: BLE001 — an RNA update callback must not raise
        pass


class MixarScribbleMark(PropertyGroup):
    """One thing the user pointed at."""

    serial: IntProperty(
        name="Serial",
        description="Stable id — also names this mark's vertex group",
        default=0,
    )
    state: StringProperty(
        name="State",
        description="DRAFT until the message carrying it is sent, then SENT",
        default="DRAFT",
    )
    gesture: StringProperty(
        name="Gesture",
        description="How the mark was read: circle, arrow, point, strike, stroke",
        default="",
    )
    view_name: StringProperty(
        name="View Camera",
        description="Camera baked at the moment this mark's frame was frozen",
        default="",
    )
    mark_json: StringProperty(
        name="Mark",
        description="The serialized mark — region, gesture and resolved objects",
        default="",
    )
    view_json: StringProperty(
        name="View",
        description="The serialized frozen frame this mark was drawn on",
        default="",
    )


classes = (MixarScribbleMark,)


def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)

    # --- saved with the file: marks are addressable scene nouns ---------
    bpy.types.Scene.mixar_marks = CollectionProperty(type=MixarScribbleMark)
    bpy.types.Scene.mixar_mark_serial = IntProperty(
        name="Last Mark Serial",
        description=(
            "Monotonic mark counter. Never reused even after marks are "
            "cleared — an earlier mark's vertex group may still be referenced "
            "in the conversation, and reusing its name would repoint that "
            "reference at different geometry"
        ),
        default=0,
    )
    bpy.types.Scene.mixar_mark_frame_name = StringProperty(
        name="Frozen Frame",
        description="bpy.data.images name of the still the marks were drawn on",
        default="",
    )

    # --- session only: an in-progress gesture, never the saved document --
    bpy.types.WindowManager.mixar_mark_armed = BoolProperty(
        name="Stylus Marking",
        description=(
            "Freeze the viewport and draw marks on it. The frozen frame is "
            "sent with your message, and each mark is resolved against the "
            "scene so the agent knows exactly what you pointed at"
        ),
        default=False,
        options={'SKIP_SAVE'},
    )
    bpy.types.WindowManager.mixar_mark_busy = BoolProperty(
        name="Resolving Mark",
        description="True while a mark is being raycast against the scene",
        default=False,
        options={'SKIP_SAVE'},
    )
    bpy.types.WindowManager.mixar_mark_intent = EnumProperty(
        name="Read Ink As",
        description=(
            "How the ink on the frozen viewport is read: marks that each "
            "point at something, or one sketch of what to build. Auto "
            "decides from the ink itself; Tab flips it while drawing"
        ),
        items=INTENT_ITEMS,
        default='AUTO',
        options={'SKIP_SAVE'},
        update=_on_intent_update,
    )


def unregister():
    from bpy.utils import unregister_class

    for attr in ("mixar_mark_armed", "mixar_mark_busy", "mixar_mark_intent"):
        if hasattr(bpy.types.WindowManager, attr):
            delattr(bpy.types.WindowManager, attr)
    for attr in ("mixar_marks", "mixar_mark_serial", "mixar_mark_frame_name"):
        if hasattr(bpy.types.Scene, attr):
            delattr(bpy.types.Scene, attr)

    for cls in reversed(classes):
        unregister_class(cls)
