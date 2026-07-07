# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent Bubble — composer footer.

Two stacked rows:

  1. Multi-line input via draw_multiline_text_input (the same wrapper
     mixie chat uses):
       * 1 line by default
       * Auto-grows to 4 lines as the user types or hits Shift+Enter
       * Internal scroll once content exceeds 4 lines
       * Shift+Enter inserts a newline; Enter submits (the
         interface_handlers.cc \\x1F submit-marker patch already
         covers SPACE_AGENT_BUBBLE)
  2. Action row with the Mode dropdown on the left and the Send
     icon-button on the right.

The C++ footer region prefsizey is sized to host the 1-line default
plus the action row (≈ 90 px). When the input expands past 1 line,
the wrapper scales its column vertically; if that pushes the
composer beyond the region, the wrapper's own scroll handles
overflow rather than clipping content out of view.
"""

import bpy
from bpy.types import Panel

from mixar.modules.common.utils.ui_utils import draw_multiline_text_input


class AGENT_BUBBLE_PT_footer(Panel):
    """Composer footer for the floating Agent Bubble editor."""

    bl_idname = "AGENT_BUBBLE_PT_footer"
    bl_space_type = 'AGENT_BUBBLE'
    bl_region_type = 'TOOLS'
    bl_label = ""
    bl_options = {'HIDE_HEADER'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        if scene is None:
            layout.label(text="(No scene)")
            return

        # Multi-line input. min_lines=1 keeps the default footprint
        # tight (1 row), max_lines=4 caps the auto-grow before the
        # wrapper switches to internal scroll.
        draw_multiline_text_input(
            layout,
            scene,
            "mixie_chat_input",
            text="",
            min_lines=1,
            max_lines=4,
        )

        # Action row — Send icon-button pushed to the right via
        # separator_spacer. Elements placed directly on the row so they
        # take their natural widths; earlier scale_x wrappers were
        # squeezing the Send button below the PLAY icon's drawable size
        # and clipping it to ">".
        action_row = layout.row(align=True)
        action_row.scale_y = 1.1

        # Mode dropdown (Agent / Generate) is hidden for now — the
        # composer is locked to Agent mode (mixie_chat_mode default
        # 'AGENT'). Restore the mode_sub.prop(scene, "mixie_chat_mode")
        # draw here to bring the selector back.

        # Paperclip — attach an image / file to the next message. Now
        # leads the control cluster on the left (the mode dropdown that
        # used to sit before it is hidden). Reuses the chat editor's
        # add_image_from_file operator so attachments end up in the
        # same collection.
        action_row.operator(
            "mixie_chat.add_image_from_file",
            text="",
            icon='LINKED',
        )

        # Push the Send button to the far right of the action row,
        # leaving visible space between the paperclip cluster and
        # the send affordance — also matches the Figma layout.
        action_row.separator_spacer()

        action_row.operator(
            "mixie_chat.send_message",
            text="",
            icon='PLAY',
        )


classes = (AGENT_BUBBLE_PT_footer,)
