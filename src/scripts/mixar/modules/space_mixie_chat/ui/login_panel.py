# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixie Chat Login Panel

Login panel for user authentication via browser SSO.
"""

import bpy
from bpy.types import Panel

from mixar.modules.common.utils import panel_style


def draw_login(layout, wm):
    """Draw the login form into *layout*.

    Split out from the panel so the real draw path is callable (and
    testable) without a registered ``bpy.types.Panel`` — the styled
    ``panel_style`` primitives degrade to stock widgets on older builds.
    """
    col = layout.column(align=True)

    # Session expired message
    if getattr(wm, 'mixie_chat_session_expired', False):
        box = panel_style.section(col)
        box.alert = True
        box.label(text="Session expired", icon='ERROR')
        box.label(text="Please log in again.")
        panel_style.section_separator(col)

    # Show error if present (non-expired errors)
    elif wm.mixie_chat_login_error:
        error_col = panel_style.section(col, align=True)
        error_col.alert = True
        error_col.label(text="Login Failed", icon='ERROR')
        # Word wrap error message (max ~30 chars per line)
        words = wm.mixie_chat_login_error.split()
        line = ""
        for word in words:
            if len(line) + len(word) + 1 > 30:
                error_col.label(text=line)
                line = word
            else:
                line = f"{line} {word}".strip()
        if line:
            error_col.label(text=line)
        panel_style.section_separator(col)

    col.label(text="Sign in with your Mixar account", icon='USER')
    col.separator()

    # SSO Login button — styled primary CTA when the build supports it.
    row = col.row()
    row.scale_y = panel_style.ACTION_SCALE_Y
    if wm.mixie_chat_is_logging_in:
        row.enabled = False
        panel_style.primary_operator(
            row, "mixie_chat.login",
            text="Waiting for browser...", icon='SORTTIME',
        )
    else:
        panel_style.primary_operator(
            row, "mixie_chat.login",
            text="Login with Browser", icon='URL',
        )


class MIXIE_CHAT_PT_login(Panel):
    """Login panel for Mixie Chat"""
    bl_label = "Login"
    bl_idname = "MIXIE_CHAT_PT_login"
    bl_space_type = 'MIXIE_CHAT'
    bl_region_type = 'WINDOW'

    @classmethod
    def poll(cls, context):
        """Only show when not logged in"""
        wm = context.window_manager
        return not wm.mixie_chat_is_logged_in

    def draw(self, context):
        draw_login(self.layout, context.window_manager)


classes = (
    MIXIE_CHAT_PT_login,
)
