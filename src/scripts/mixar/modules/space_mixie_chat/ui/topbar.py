# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar Profile Dropdown — injected into Blender's main top bar.

The user-profile dropdown (account actions, AI connections, Docs and Logout) used to
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

from ..constants import SOUND_FEEDBACK_WIDTHS, SessionState  # noqa: F401  (kept for parity)
from ..core import avatar_icon, sound_feedback
from ..core.completion_sound import OFF, get_completion_sound, get_notifications_muted
from ...common.utils import topbar_layout
from ...common.i18n import iface_
from ...workflow.constants import BASIC_WORKSPACE_NAME
from .login_panel import draw_profile_sign_in


class MIXAR_PT_profile(Panel):
    """Profile / account dropdown — opened from the global top bar.

    The contents are drawn natively by `layout.mixar_profile_card()`
    (`interface_mixar_profile_card.cc`): a greeting, the plan chip, the
    credit balance and the account actions, laid out as one card
    rather than a menu. Python still owns registration and every
    operator the card invokes — C++ owns only pixels.
    """

    bl_label = "Profile"
    bl_idname = "MIXAR_PT_profile"
    bl_space_type = 'TOPBAR'
    bl_region_type = 'HEADER'
    #: Narrow enough that the card reads as a card rather than a wide,
    #: sparse strip — at 17 the content sat in the left third and every
    #: label looked undersized for the surface it was on.
    bl_ui_units_x = 15

    def draw(self, context):
        layout = self.layout
        if not topbar_layout.account_signed_in(context.window_manager):
            draw_profile_sign_in(layout, context.window_manager)

        try:
            layout.mixar_profile_card()
        except AttributeError:
            # Build whose C++ predates the card item — fall back to the
            # plain menu so the account actions are never unreachable.
            self._draw_fallback_menu(context, layout)

    @staticmethod
    def _draw_fallback_menu(context, layout) -> None:
        logged_in = topbar_layout.account_signed_in(context.window_manager)
        if logged_in:
            layout.operator("mixie_chat.open_dashboard", text="Dashboard", icon='URL')
        if logged_in and hasattr(bpy.types, "MIXAR_OT_refer_friend"):
            refer = layout.row()
            refer.operator_context = 'INVOKE_DEFAULT'
            refer.operator("mixar.refer_friend", text="Refer a Friend", icon='FUND')

        # Same dialog and WindowManager state as the chat model picker.
        if hasattr(bpy.types, "MIXAR_BYOK_OT_open_dialog"):
            settings = layout.row()
            settings.operator_context = 'INVOKE_DEFAULT'
            settings.operator(
                "mixar_byok.open_dialog", text="AI Provider Settings",
                icon='KEY_HLT' if context.window_manager.byok_is_active else 'PREFERENCES',
            )

        if hasattr(bpy.types, "MIXAR_OT_connect_ai"):
            connect = layout.row()
            connect.operator_context = 'INVOKE_DEFAULT'
            connect.operator("mixar.connect_ai", icon='LINKED')

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

        if logged_in:
            layout.separator()
            layout.operator("mixie_chat.logout", text="Logout", icon='PANEL_CLOSE')



def _draw_sound_toggle(layout, context):
    if not (hasattr(bpy.types, 'MIXIE_CHAT_OT_toggle_completion_sound') and
            hasattr(context.window_manager, 'mixar_notifications_muted')):
        return
    # The persisted config is the truth; the enum mirror's index lookup can
    # miss a catalog clip and read as Off while that clip plays.
    enabled = not get_notifications_muted() and get_completion_sound() != OFF
    fraction = sound_feedback.expansion() if enabled else 0.0
    closed, opened = SOUND_FEEDBACK_WIDTHS
    row = layout.mixar_surface(theme='ZEN').row(align=True)
    row.alignment = 'EXPAND'
    row.ui_units_x = closed + (opened - closed) * fraction
    # Native icon-only buttons otherwise retain their fixed one-unit width.
    row.scale_x = row.ui_units_x if fraction < 0.999 else 1.0
    # Keep the full label readable; expand first, then reveal it for the hold.
    # The icon and tooltip convey sound state; keep the button neutral in both states.
    row.operator('mixie_chat.toggle_completion_sound',
                 text='Sound on' if fraction >= 0.999 else '',
                 icon=('NONE' if fraction >= 0.999 else
                       'NOTIFICATION_SOUND' if enabled else 'NOTIFICATION_SOUND_OFF'),
                 depress=False)
    row.mixar_style(component='ACTION', variant='GHOST')


def _account_lane(context):
    """(window logical width, is Engine, Engine shows full selectors) or None
    outside a real header."""
    area = getattr(context, "area", None)
    if area is None:
        return None
    width = topbar_layout.logical_width(area.width, context.preferences.system.ui_scale)
    workspace = getattr(context, "workspace", None)
    engine = workspace is None or workspace.name != BASIC_WORKSPACE_NAME
    selectors = engine and topbar_layout.engine_full_selectors(
        width, topbar_layout.context_account_units(context))
    return width, engine, selectors


def _show_sound_toggle(context, logged_in):
    lane = _account_lane(context)
    return lane is None or topbar_layout.show_sound_toggle(
        lane[0], engine=lane[1], logged_in=logged_in)


def _profile_pill_size(context, email, sound):
    """(ui_units_x, label) for the account pill at the window's width."""
    lane = _account_lane(context)
    if lane is None:
        return len(email) * 0.35 + 3.8, email
    return topbar_layout.profile_pill(
        email, lane[0], engine=lane[1], sound=sound, selectors=lane[2])


def _draw_topbar_profile_right(self, context):
    """Append the shared account / guest dropdown to the right of the top bar.

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

    logged_in = topbar_layout.account_signed_in(wm)
    # On the narrowest windows the account button keeps the lane; sound
    # stays reachable from Preferences.
    sound = _show_sound_toggle(context, logged_in)
    if sound:
        _draw_sound_toggle(layout, context)
        layout.separator(factor=0.4)

    # The native right-header layout fills the menu-bar height. Reserve room
    # for its taller account icon so the label remains fully visible.
    account = layout.row(align=True)

    email = getattr(scene, 'mixie_chat_user_id', "") if scene is not None else ""
    caption = topbar_layout.account_label(wm, email, iface_("Guest"))
    profile_sub = account.row(align=True)
    # Guest uses the same lane budget and avatar-only narrow-window fallback.
    profile_sub.ui_units_x, label = _profile_pill_size(context, caption, sound)
    if hasattr(profile_sub, "mixar_topbar_element"):
        profile_sub.popover(panel="MIXAR_PT_profile", text=label, translate=False)
        profile_sub.mixar_topbar_element(kind='PROFILE_PILL', active=True)
    else:
        profile_sub.popover(panel="MIXAR_PT_profile", text=label,
                            icon='USER', translate=False)


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
