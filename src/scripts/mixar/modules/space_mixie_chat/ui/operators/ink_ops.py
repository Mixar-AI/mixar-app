# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scribble operators — Python side of the handwriting ink overlay.

The pen icon in the chat header toggles the C++-drawn ink canvas
(``editors/space_mixie_chat/mixie_chat_ink_overlay.cc``); a stylus press on
the composer or on empty chat background opens it too, writing the same WM
flag from C++.

While it is open the overlay captures strokes and, once the pen has been
still for ``SCRIBBLE_IDLE_COMMIT_MS``, dispatches ``mixie_chat.ink_commit``
with them and clears its canvas so the user can keep writing. All the work
that follows — validation, rasterizing, the recognition request, appending
to the composer — lives in ``core/scribble.py``.
"""

from bpy.props import StringProperty
from bpy.types import Operator

from mixar.config.logging_config import get_logger

from ...core.ui_utils import redraw_chat_areas

logger = get_logger(__name__)


class MIXIE_CHAT_OT_toggle_scribble(Operator):
    """Toggle the handwriting canvas over the chat"""

    bl_idname = "mixie_chat.toggle_scribble"
    bl_label = "Scribble"
    bl_description = (
        "Write with a stylus over the chat — your handwriting is converted "
        "to text in the message box"
    )
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def execute(self, context):
        wm = context.window_manager
        opening = not getattr(wm, 'mixie_chat_ink_visible', False)
        if opening:
            # Scribble, project rules and past chats are all modal over the
            # same chat surface — only one may be open at a time.
            if getattr(wm, 'mixie_chat_rules_visible', False):
                wm.mixie_chat_rules_visible = False
            if getattr(wm, 'mixie_chat_history_visible', False):
                wm.mixie_chat_history_visible = False
        else:
            # Closing from the header: convert whatever is still on the
            # canvas first — the C++ closing edge cannot dispatch the
            # commit itself and would drop the strokes.
            from ...core import scribble
            scribble.flush_pending_ink()
        wm.mixie_chat_ink_visible = opening
        redraw_chat_areas()
        return {'FINISHED'}


class MIXIE_CHAT_OT_ink_commit(Operator):
    """Convert one batch of captured ink to text (dispatched by the C++
    overlay on idle, and once more when it closes)."""

    bl_idname = "mixie_chat.ink_commit"
    bl_label = "Convert Handwriting"
    bl_options = {'INTERNAL'}

    # No maxlen: C++ caps the payload at INK_JSON_MAX before dispatching and
    # core/scribble re-checks it against SCRIBBLE_COMMIT_MAXLEN. A maxlen here
    # would truncate an over-cap payload into malformed JSON instead.
    strokes_json: StringProperty(
        name="Strokes",
        description="Captured ink as JSON (region-local pixels, y up)",
        default="",
        options={'SKIP_SAVE', 'HIDDEN'},
    )

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def execute(self, context):
        from ...core import scribble

        try:
            scribble.handle_commit(context.scene, self.strokes_json)
        except ValueError as e:
            # Version skew between the C++ capture and this parser: nothing
            # the user can act on, but it must never abort their writing.
            logger.warning("[Scribble] rejected ink payload: %s", e)
            self.report({'WARNING'}, "Could not read the captured handwriting")
            return {'CANCELLED'}
        except Exception as e:
            logger.error("[Scribble] ink commit failed: %s", e, exc_info=True)
            self.report({'WARNING'}, f"Handwriting conversion failed: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}


classes = (
    MIXIE_CHAT_OT_toggle_scribble,
    MIXIE_CHAT_OT_ink_commit,
)
