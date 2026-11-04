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


class MIXIE_CHAT_PT_login(Panel):
    """Login panel for Mixie Chat"""
    bl_label = "Login"
    bl_idname = "MIXIE_CHAT_PT_login"
    bl_space_type = 'TOPBAR'
    bl_region_type = 'WINDOW'

    @classmethod
    def poll(cls, context):
        """Only show when not signed in to an account (a guest is not)"""
        wm = context.window_manager
        return not wm.mixie_chat_is_logged_in or getattr(wm, 'mixie_chat_is_guest', False)

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager

        col = layout.column(align=True)

        if getattr(wm, 'mixie_chat_is_guest', False):
            col.label(text="You're using Mixar as a guest.", icon='INFO')
            col.label(text="Sign in for Mixar models and generation.")
            col.separator()

        draw_login_feedback(col, wm)

        col.label(text="Sign in with your Mixar account", icon='USER')
        col.separator()

        draw_browser_sign_in(col, wm)


classes = (
    MIXIE_CHAT_PT_login,
)


def draw_login_feedback(col, wm):
    """Existing session/error feedback shared by every sign-in surface."""
    # Session expired message
    if getattr(wm, 'mixie_chat_session_expired', False):
        box = col.box()
        box.alert = True
        box.label(text="Session expired", icon='ERROR')
        box.label(text="Please log in again.")
        col.separator()

    # Show error if present (non-expired errors)
    elif wm.mixie_chat_login_error:
        error_box = col.box()
        error_box.alert = True
        error_col = error_box.column(align=True)
        error_col.label(text="Login Failed", icon='ERROR')
        # Word wrap error message (max ~30 chars per line)
        words = wm.mixie_chat_login_error.split()
        line = ""
        for word in words:
            if len(line) + len(word) + 1 > 30:
                error_col.label(text=line, translate=False)
                line = word
            else:
                line = f"{line} {word}".strip()
        if line:
            error_col.label(text=line, translate=False)
        col.separator()


def draw_browser_sign_in(col, wm, *, card=False):
    """Keep one browser attempt, with an explicit way to cancel and retry."""
    # While the browser owns the sign-in: a plain status line and an
    # explicit Cancel, never a clickable "waiting" button (a click there
    # started a second sign-in and orphaned the first tab). Cancel brings
    # Login with Browser back, so a closed tab is never a dead end.
    if wm.mixie_chat_is_logging_in:
        col.label(text="Continue in your browser", icon='SORTTIME')
        col.operator("mixie_chat.cancel_login", text="Cancel")
    else:
        if card:
            col.operator("mixie_chat.login", text="Sign in to Mixar")
        else:
            col.operator("mixie_chat.login", text="Login with Browser", icon='URL')
    if card and hasattr(col, 'mixar_card_button'):
        col.mixar_card_button(kind='GHOST' if wm.mixie_chat_is_logging_in else 'ACCENT')


def draw_profile_sign_in(layout, wm):
    """Option B: sign-in first, above the native card's shared guest tools."""
    from mixar.modules.common.i18n import iface_
    from mixar.modules.common.ui.constants import CARD_ROW_CTA, CARD_ROW_HEADING

    heading = layout.row()
    heading.scale_y = CARD_ROW_HEADING
    if hasattr(heading, 'mixar_card_label'):
        heading.mixar_card_label(text=iface_("You're using Mixar as a guest"), kind='HEADING')
    else:
        heading.label(text="You're using Mixar as a guest")
    layout.label(text="Sign in for Mixar models and generation.")
    draw_login_feedback(layout, wm)
    action = layout.column(align=True)
    action.scale_y = CARD_ROW_CTA
    draw_browser_sign_in(action, wm, card=True)
    layout.separator()
