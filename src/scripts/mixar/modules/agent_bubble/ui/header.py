# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent Bubble — header.

Two render modes, distinguished by region presence:

  * MAIN BUBBLE WINDOW (has TOOLS region):
      drag-handle ▬▬▬▬ centered + traffic-light buttons.

  * FLOATING PILL WINDOW (HEADER only, no TOOLS):
      just the status pill text + dot, centred as a clickable
      restore button. The pill window is a separate small window
      attached as a child of the main bubble — see
      Mixar_WindowSetParent and the open-op code in
      space_agent_bubble.cc that creates it. Both windows use the
      same SPACE_AGENT_BUBBLE editor, so this single Header drawer
      runs in both.

Detection uses region presence (TOOLS region exists only in the
main bubble) — DPI-invariant, unlike pixel-width thresholds.
"""

import sys

import bpy
from bpy.types import Header

from mixar.modules.agent_bubble.core.pill_icons import (
    get_pill_icon_id_named,
    get_running_text_suffix,
)


# Session-state values that mean the agent is actively working — these
# get the green pulsing-dot label. AWAITING_INPUT is intentionally NOT
# here: when the agent pauses to ask the user a question it has stopped
# running, so the "Running…" animation would lie about activity and
# read as "the agent is stuck."
_RUNNING_STATES = {"BUSY", "MODIFYING"}

_IS_WINDOWS = sys.platform == "win32"


def _transport_down() -> bool:
    """True when the WebSocket transport is currently disconnected.

    Session state deliberately preserves BUSY/AWAITING_INPUT/MODIFYING while
    the WS reconnects (so resumed tool calls aren't rejected — see
    connection_manager.on_disconnected), which means scene state alone says
    "Running" even with the network gone. The pill must not lie about that.

    Uses is_transport_live (recv-recency) rather than is_connected: on a
    silent network drop is_connected stays True until the 45s teardown
    watchdog, and the pill would keep implying a healthy connection for
    that whole window.
    """
    try:
        from mixar.modules.space_mixie_chat.core.connection_manager import (
            get_connection_manager,
        )
        return not get_connection_manager().is_transport_live
    except Exception:
        return False


def _get_status(scene) -> tuple[str, str, str]:
    """Return (label, custom icon colour, fallback icon) for the pill."""
    state = getattr(scene, "mixie_chat_state", "OFFLINE") or "OFFLINE"
    if state == "OFFLINE":
        return "Disconnected", "red", 'CANCEL'
    if state == "CONNECTING":
        return "Connecting", "blue", 'SORTTIME'
    if _transport_down():
        # Any non-offline state with the transport gone means the client is
        # auto-reconnecting (and, mid-turn, will re-attach to the stream).
        return "Reconnecting", "red", 'CANCEL'
    if state in _RUNNING_STATES:
        return "Running", "green", 'RECORD_ON'
    if state == "AWAITING_INPUT":
        # Blue instead of yellow — yellow is already the macOS close
        # traffic-light button. CONNECTING and AWAITING_INPUT can't be
        # active simultaneously, so reusing the same blue is safe and
        # avoids the visual collision.
        return "Awaiting Input", "blue", 'QUESTION'
    return "Idle", "grey", 'RECORD_OFF'


def _is_pill_window(context) -> bool:
    """The pill window only has a HEADER region (WINDOW and TOOLS are
    removed at creation in space_agent_bubble.cc).  The main bubble
    always has a TOOLS region.  This is DPI-invariant — no pixel
    threshold needed."""
    area = context.area
    if area is None:
        return False
    for region in area.regions:
        if region.type == 'TOOLS':
            return False
    return True


def _draw_status(layout, scene) -> None:
    """Render the connection / activity status pill (icon + text)."""
    label, icon_name, fallback_icon = _get_status(scene)
    if icon_name == "green":
        label = label + get_running_text_suffix()
    icon_id = get_pill_icon_id_named(icon_name)
    if icon_id:
        layout.label(text=label, icon_value=icon_id)
    else:
        layout.label(text=label, icon=fallback_icon)


class AGENT_BUBBLE_HT_header(Header):
    """Header for the floating Agent Bubble editor."""

    bl_space_type = 'AGENT_BUBBLE'
    bl_region_type = 'HEADER'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        if _is_pill_window(context):
            # Floating pill child window — render the entire pill as
            # a clickable operator button that calls
            # mixar.bubble_restore_user. When the bubble is minimised the
            # restore op brings it back; when not minimised the op
            # is a harmless no-op so casual clicks on the pill
            # behave intuitively (nothing weird happens).
            #
            # Centering: header rows flex horizontally with whatever
            # they hold left-aligned, so a single separator_spacer()
            # before the row pushes content to the right edge. To
            # genuinely centre, sandwich the operator between two
            # spacers — equal flex on both sides parks it dead
            # centre. We also wrap the operator in a fixed-width
            # row whose ui_units_x matches the icon+text natural
            # width so the spacers measure against a stable centre
            # point (without this Blender's auto-sized button drifts
            # under the larger scale_y, leaving the visual centre
            # lopsided).
            #
            # Centring — putting the operator DIRECTLY between two
            # separator_spacer() calls (NOT wrapped in a row). A row
            # wrapper collapses the surrounding spacers in Blender's
            # header layout pass, leaving the operator left-anchored.
            #
            # Bigger text in LARGE state — applied via
            # `layout.scale_y` on the ROOT layout instead of a row
            # wrapper. scale_y affects vertical scaling only, so the
            # horizontal flex of separator_spacer is preserved
            # (unlike row.scale_y which seems to interact with the
            # layout's flex pass and squashes the spacers). Detect
            # LARGE pill via context.window.height — SMALL is 28 px,
            # LARGE is 44 px, so any height ≥ 36 is the LARGE state.
            label, icon_name, fallback_icon = _get_status(scene)
            if icon_name == "green":
                label = label + get_running_text_suffix()
            icon_id = get_pill_icon_id_named(icon_name)

            # Centre the operator in the header.  separator_spacer()
            # pairs don't centre accurately because the header has
            # built-in left padding.  Instead, use a single centred
            # row that spans the full width — Blender centres its
            # children within the available space.
            row = layout.row()
            row.alignment = 'CENTER'
            # no_tooltip=True is a Mixar-only kwarg added to
            # bpy.types.UILayout.operator() (see rna_ui_api.cc). The
            # pill window is small; Blender's tooltip popup would be
            # clipped by the window bounds and only show "Restore" /
            # "Restore." as a partial fragment that looks like a UI
            # bug. Suppressing the tooltip entirely is cleaner.
            if icon_id:
                row.operator(
                    "mixar.bubble_restore_user",
                    text=label,
                    icon_value=icon_id,
                    emboss=False,
                    no_tooltip=True,
                )
            else:
                row.operator(
                    "mixar.bubble_restore_user",
                    text=label,
                    icon=fallback_icon,
                    emboss=False,
                    no_tooltip=True,
                )
            return

        # Main bubble window header (left → right):
        #   * Minimise button (+ close on macOS — routes to minimise)
        #   * Expand/collapse toggle button
        #   * Centred drag handle ▬▬▬▬
        #
        # On macOS: coloured traffic-light circles (custom pill icons).
        # On Windows: minimise + expand icon buttons only.
        traffic = layout.row(align=True)
        if _IS_WINDOWS:
            traffic.operator(
                "mixar.bubble_close",
                text="",
                icon='REMOVE',
                emboss=False,
                no_tooltip=True,
            )
            traffic.operator(
                "mixar.bubble_toggle_expand",
                text="",
                icon='FULLSCREEN_ENTER',
                emboss=False,
                no_tooltip=True,
            )
        else:
            yellow_id = get_pill_icon_id_named("yellow")
            green_id = get_pill_icon_id_named("green")
            if yellow_id:
                traffic.operator(
                    "mixar.bubble_close",
                    text="",
                    icon_value=yellow_id,
                    emboss=False,
                    no_tooltip=True,
                )
            if green_id:
                traffic.operator(
                    "mixar.bubble_toggle_expand",
                    text="",
                    icon_value=green_id,
                    emboss=False,
                    no_tooltip=True,
                )

        layout.separator_spacer()
        handle_row = layout.row()
        handle_row.alignment = 'CENTER'
        handle_row.label(text="▬▬▬▬")
        layout.separator_spacer()

        # Right-side buttons (left → right): reconnect, new chat, past chats.
        #
        # These are icon-only, so they keep Blender's DEFAULT tooltip box
        # (each operator's bl_description) as the hover affordance — unlike
        # the pill/traffic-light buttons above, which use no_tooltip=True
        # because the tiny pill window clips the popup into a fragment.
        right_controls = layout.row(align=True)

        # Reconnect button (mirrors the Connect button in mixie chat's
        # header, icon-only). Only rendered while disconnected — the
        # operator's poll additionally requires login, and hiding it
        # when logged out avoids a permanently greyed-out button.
        state = getattr(scene, "mixie_chat_state", "OFFLINE") or "OFFLINE"
        wm = context.window_manager
        if state == "OFFLINE" and getattr(wm, "mixie_chat_is_logged_in", False):
            right_controls.operator(
                "mixie_chat.connect",
                text="",
                icon='LINKED',
                emboss=False,
            )

        # New-chat and past-chats are hidden while a turn is executing
        # (same states as the "Running" pill): switching or clearing the
        # conversation mid-run would detach the UI from the turn the
        # agent is still working on.
        agent_running = state in _RUNNING_STATES

        # New-chat button on the right (mirrors the one in mixie chat's
        # header). Only rendered when there is chat history to clear:
        # an empty conversation already shows the empty state, and
        # "New Chat" on an empty chat is a no-op, so the button would
        # be visual noise.
        #
        # Messages live on Scene (scene.mixie_chat_messages) and are
        # shared between the mixie chat editor and the bubble — so
        # this draw stays in sync with what the user sees.
        msg_count = 0
        if scene is not None:
            msgs = getattr(scene, "mixie_chat_messages", None)
            if msgs is not None:
                try:
                    msg_count = len(msgs)
                except TypeError:
                    msg_count = 0
        if msg_count > 0 and not agent_running:
            right_controls.operator(
                "mixie_chat.new_session",
                text="",
                icon='FILE_NEW',
                emboss=False,
            )

        # Past chats — toggles the C++-drawn history overlay (shared with
        # the mixie chat editor; the bubble's main region reuses the same
        # draw callbacks). Shown even when the current chat is empty —
        # reopening an old chat from a fresh state is exactly the history
        # use-case. hasattr guard: registers in the deferred UI pass.
        if hasattr(bpy.types, 'MIXIE_CHAT_OT_show_history') and not agent_running:
            wm = context.window_manager
            right_controls.operator(
                "mixie_chat.show_history",
                text="",
                icon='RECOVER_LAST',
                emboss=False,
                depress=bool(getattr(wm, 'mixie_chat_history_visible', False)),
            )

        # Project rules — mirrors the docked header's Add Rules button:
        # toggles the C++-drawn rules overlay in the chat region (same
        # style as the past-chats overlay; see rules_ops.py /
        # mixie_chat_rules_overlay.cc). Icon-only here (header space is
        # tight); Blender's default tooltip (bl_description) is the hover
        # affordance, like the siblings above. depress mirrors the overlay
        # being open.
        if hasattr(bpy.types, 'MIXIE_CHAT_OT_add_rules') and not agent_running:
            wm = context.window_manager
            right_controls.operator(
                "mixie_chat.add_rules",
                text="",
                icon='TEXT',
                emboss=False,
                depress=bool(getattr(wm, 'mixie_chat_rules_visible', False)),
            )


classes = (AGENT_BUBBLE_HT_header,)
