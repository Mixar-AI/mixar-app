# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar Profile Dropdown — injected into Blender's main top bar.

The user-profile dropdown (Dashboard / About / Docs / Logout) used to
live in the Mixie Chat editor header. It's been promoted to the global
top bar (`TOPBAR_HT_upper_bar`, RIGHT region) so it's reachable from
every editor — including the floating Agent Bubble — and so the Mixie
Chat header can stay tightly focused on chat-specific controls.

How it integrates with upstream Blender's top bar:

  * `_draw_topbar_profile_right` is appended to `TOPBAR_HT_upper_bar`
    via `bpy.types.TOPBAR_HT_upper_bar.append()`. Header.append()
    callbacks fire AFTER the class's own draw(), so whatever they
    emit lands at the END of the row — i.e. the right-most position.
  * The same Header callback fires for both the LEFT and RIGHT regions
    of the top bar (the upstream class picks via region.alignment),
    so we also gate on `region.alignment == 'RIGHT'` to keep our
    contribution out of the left side.
  * The popover panel `MIXAR_PT_profile` is declared with
    bl_space_type='TOPBAR' / bl_region_type='HEADER' so it's a
    natural inhabitant of the bar it now lives on.
"""

from __future__ import annotations

import bpy
from bpy.types import Header, Panel

from ..constants import SessionState  # noqa: F401  (kept for parity)


class MIXAR_PT_profile(Panel):
    """Profile / account dropdown — opened from the global top bar."""

    bl_label = "Profile"
    bl_idname = "MIXAR_PT_profile"
    bl_space_type = 'TOPBAR'
    bl_region_type = 'HEADER'

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager

        layout.operator("mixie_chat.open_dashboard", text="Dashboard", icon='URL')

        if hasattr(bpy.types, 'MIXAR_BYOK_OT_open_dialog'):
            byok_icon = 'KEY_HLT' if getattr(wm, 'byok_is_active', False) else 'PREFERENCES'
            layout.operator(
                "mixar_byok.open_dialog",
                text="AI Provider Settings",
                icon=byok_icon,
            )

        layout.separator()

        layout.operator(
            "wm.url_open", text="About Mixar", icon='INFO',
        ).url = "https://www.mixar.app/about"
        layout.operator(
            "wm.url_open", text="Documentation", icon='HELP',
        ).url = "https://www.mixar.app/docs"
        layout.operator(
            "wm.url_open", text="Report a Bug", icon='URL',
        ).url = "https://www.mixar.app/bug-report"

        layout.separator()

        layout.operator("mixie_chat.logout", text="Logout", icon='PANEL_CLOSE')


def _draw_topbar_profile_right(self, context):
    """Append the profile dropdown / login button to the right side of the top bar.

    Runs after `TOPBAR_HT_upper_bar.draw_right`, so it lands to the
    right of the view-layer search (the prior right-most item) — which
    becomes the new "shifted-left" item the user asked for.
    """
    region = getattr(context, "region", None)
    if region is None or region.alignment != 'RIGHT':
        return

    layout = self.layout
    wm = context.window_manager
    scene = context.scene

    # Small visual breather between the view-layer search and the
    # profile pill so the two clusters don't read as one control.
    layout.separator()

    if getattr(wm, 'mixie_chat_is_logged_in', False):
        # Logged in → email pill that opens the profile popover.
        # ui_units_x mirrors the sizing previously used in the mixie
        # chat header so the pill width still grows with the email.
        email = getattr(scene, 'mixie_chat_user_id', "") if scene is not None else ""
        profile_sub = layout.row(align=True)
        profile_sub.ui_units_x = len(email) * 0.35 + 2.5
        profile_sub.popover(panel="MIXAR_PT_profile", text=email, icon='USER')
    else:
        # Not logged in → login popover (preferred) with operator fallback
        # for the brief window where the login panel class hasn't
        # finished registering yet.
        if hasattr(bpy.types, 'MIXIE_CHAT_PT_login'):
            layout.popover(panel="MIXIE_CHAT_PT_login", text="Login", icon='USER')
        else:
            layout.operator("mixie_chat.login", text="Login", icon='USER')


def register():
    bpy.utils.register_class(MIXAR_PT_profile)
    bpy.types.TOPBAR_HT_upper_bar.append(_draw_topbar_profile_right)


def unregister():
    try:
        bpy.types.TOPBAR_HT_upper_bar.remove(_draw_topbar_profile_right)
    except Exception:
        pass
    try:
        bpy.utils.unregister_class(MIXAR_PT_profile)
    except Exception:
        pass
