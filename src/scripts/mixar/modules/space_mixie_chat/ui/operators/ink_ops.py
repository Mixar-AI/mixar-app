# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scribble operators — Python side of the handwriting ink overlay.

The C++-drawn ink canvas (``editors/space_mixie_chat/mixie_chat_ink_overlay.cc``)
is raised two ways: the Scribble control in the chat header
(``mixar.scribble_toggle``, which arms the chat canvas AND the viewport
marks together — see ``scribble_mark/core/scribble_mode.py``), or a stylus
press on the composer / on empty chat background, which C++ handles by
writing the same WM flag and opens the canvas alone.

While it is open the overlay captures strokes and dispatches
``mixie_chat.ink_commit`` twice over: at EVERY pen-up with
``provisional=True`` (the ink so far, canvas kept — a preview whose text
shows in the composer as soon as it lands), and once the pen has been still
for ``SCRIBBLE_IDLE_COMMIT_MS`` as the FINAL commit, which clears the canvas
so the user can keep writing. All the work that follows — validation,
rasterizing, the recognition request, the composer — lives in
``core/scribble.py`` and ``core/scribble_live.py``.
"""

from bpy.props import BoolProperty, StringProperty
from bpy.types import Operator

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


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
    # A pen-up preview of the batch so far, not its final commit: the text
    # is shown provisionally and the ink stays on the canvas. An empty
    # provisional payload means the user cleared the canvas — discard the
    # preview shown for it.
    provisional: BoolProperty(
        name="Provisional",
        description="Preview the batch written so far without committing it",
        default=False,
        options={'SKIP_SAVE', 'HIDDEN'},
    )

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def execute(self, context):
        from ...core import scribble

        try:
            scribble.handle_commit(
                context.scene, self.strokes_json, provisional=self.provisional
            )
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
    MIXIE_CHAT_OT_ink_commit,
)
