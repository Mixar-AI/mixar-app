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
from ..core import account_usage, avatar_icon


def _account_subtitle(wm) -> str:
    """Dimmed one-liner under the email: plan, trial, team pool.

    Folding these into a single secondary line keeps the popover to one
    idea per row — identity, then balance, then actions — instead of a
    stack of "Label: value" rows competing for the same weight.
    """
    parts = [getattr(wm, 'mixie_account_plan_name', '') or "Free"]

    trial_days = int(getattr(wm, 'mixie_account_trial_days', -1))
    if trial_days >= 0:
        unit = "day" if trial_days == 1 else "days"
        parts.append(f"{trial_days} {unit} left")

    if getattr(wm, 'mixie_account_team_is_active', False):
        team = getattr(wm, 'mixie_account_team_name', '') or "Team"
        parts.append(f"{team} pool")

    return "   ".join(parts)


class MIXAR_PT_profile(Panel):
    """Profile / account dropdown — opened from the global top bar."""

    bl_label = "Profile"
    bl_idname = "MIXAR_PT_profile"
    bl_space_type = 'TOPBAR'
    bl_region_type = 'HEADER'
    # Fixed width: the balance and the plan line both change length as the
    # account refreshes, and an auto-sized popover visibly resizes under the
    # cursor when they do.
    bl_ui_units_x = 13

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager

        account_usage.schedule_stale_refresh(wm)

        self._draw_identity(layout, context, wm)
        self._draw_balance(layout, wm)
        self._draw_actions(layout, wm)

    @staticmethod
    def _draw_identity(layout, context, wm):
        scene = context.scene
        email = getattr(scene, 'mixie_chat_user_id', "") if scene is not None else ""

        head = layout.column(align=True)
        row = head.row(align=True)
        # Green avatar disc with the account initial; 0 means the generator
        # failed (e.g. Pillow missing) → stock USER icon.
        avatar_id = avatar_icon.get_avatar_icon_id(email)
        if avatar_id:
            row.label(text=email or "Signed in", icon_value=avatar_id)
        else:
            row.label(text=email or "Signed in", icon='USER')

        if getattr(wm, 'mixie_account_loaded', False):
            sub = head.row(align=True)
            sub.active = False  # secondary text
            # BLANK1 pads the subtitle to the same indent as the email above.
            sub.label(text=_account_subtitle(wm), icon='BLANK1')

    @staticmethod
    def _draw_balance(layout, wm):
        loading = getattr(wm, 'mixie_account_loading', False)

        layout.separator()

        row = layout.row(align=True)
        row.scale_y = 1.25  # the balance is the one number people open this for
        if getattr(wm, 'mixie_account_loaded', False):
            credits = int(getattr(wm, 'mixie_account_credits', 0))
            row.label(text=f"{credits:,} credits", icon='SOLO_ON')
        elif loading:
            row.label(text="Refreshing...", icon='SORTTIME')
        else:
            row.label(text="Usage unavailable", icon='INFO')

        refresh = row.row(align=True)
        refresh.alignment = 'RIGHT'
        refresh.enabled = not loading
        refresh.operator(
            "mixie_chat.refresh_credits", text="", icon='FILE_REFRESH', emboss=False,
        )

        if getattr(wm, 'byok_is_active', False):
            note = layout.row(align=True)
            note.active = False
            note.label(text="Own provider — agent requests are free", icon='KEY_HLT')

        if getattr(wm, 'mixie_account_error', ''):
            err = layout.row(align=True)
            err.alert = True
            err.label(text="Couldn't refresh — showing last known", icon='ERROR')

    @staticmethod
    def _draw_actions(layout, wm):
        layout.separator()

        # Aligned column → the primary actions read as one contiguous menu
        # block rather than three free-floating buttons.
        actions = layout.column(align=True)
        actions.operator("mixie_chat.open_dashboard", text="Dashboard", icon='URL')
        if hasattr(bpy.types, 'MIXAR_BYOK_OT_open_dialog'):
            byok_icon = 'KEY_HLT' if getattr(wm, 'byok_is_active', False) else 'PREFERENCES'
            actions.operator(
                "mixar_byok.open_dialog", text="AI Provider", icon=byok_icon,
            )

        layout.separator()

        # Secondary links share one row: they're rarely used and don't earn
        # three full-width rows of their own. Text-only keeps the row legible
        # at a third of the popover width each.
        links = layout.row(align=True)
        links.operator(
            "wm.url_open", text="About",
        ).url = "https://www.mixar.app/about"
        links.operator(
            "wm.url_open", text="Docs",
        ).url = "https://www.mixar.app/docs"
        links.operator(
            "wm.url_open", text="Report Bug",
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
        # Grows with the email, but capped: a long address would otherwise
        # crowd the view-layer controls to its left. Blender elides the
        # overflow, and the full address is the first line of the popover.
        profile_sub.ui_units_x = min(len(email) * 0.35 + 2.5, 12.0)
        # Green avatar disc with the account initial; 0 means the
        # generator failed (e.g. Pillow missing) → stock USER icon.
        avatar_id = avatar_icon.get_avatar_icon_id(email)
        if avatar_id:
            profile_sub.popover(
                panel="MIXAR_PT_profile", text=email, icon_value=avatar_id)
        else:
            profile_sub.popover(
                panel="MIXAR_PT_profile", text=email, icon='USER')
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
    avatar_icon.unregister()
