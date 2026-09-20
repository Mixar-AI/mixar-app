# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The "Cinema Mode" pill on the right of the topbar.

Appended to ``TOPBAR_HT_upper_bar`` (RIGHT region) rather than to the
editor-menus list, per the design: the pill sits between the topbar's own
right-hand content and the profile chip, and the Zen/Engine slider owns
the centre (``workflow/ui/headers/mode_filter_header.py``).

Ordering note: the profile chip is appended by
``space_mixie_chat/ui/topbar.py``. Header ``append`` callbacks run in
registration order, and the UI auto-loader walks modules alphabetically —
``director`` before ``space_mixie_chat`` — so this pill lands to the LEFT
of the profile, as designed. If that ever flips, the pill and the profile
swap places; nothing else breaks.

The feature is still called "director" everywhere in code (operator
idnames are frozen agent contracts); only what the user reads changed.
"""

import bpy

_PILL_UNITS = 7.5
"""Pill width in UI units — the design's 150 px at 1x (1 unit = 20 px)."""


def draw_director_entry(self, context):
    """Draw the Cinema Mode pill. Right region only."""
    region = getattr(context, "region", None)
    if region is None or region.alignment != 'RIGHT':
        return

    state = getattr(context.scene, "mixar_director", None)
    if state is None:
        return

    layout = self.layout
    layout.separator()

    sub = layout.row(align=True)
    sub.ui_units_x = _PILL_UNITS
    is_directing = bool(state.is_directing)
    if is_directing:
        # Clicking the active pill leaves Cinema Mode without losing the take.
        sub.operator("mixar.director_finish", text="Cinema Mode")
    else:
        sub.operator("mixar.director_enter", text="Cinema Mode")

    # Native pill chrome: dark fill, hairline border, label graded grey to
    # white (interface_mixar_topbar.cc). Guarded so a build without the
    # widget still shows a working, if stock, button.
    if hasattr(sub, "mixar_topbar_element"):
        sub.mixar_topbar_element(kind='CINEMA_PILL', active=is_directing)

    # The switch knob eases across in C++; that needs frames, and a redraw
    # tagged from a draw callback does not wake the idle loop. Same pump the
    # mode slider uses — it no-ops unless the state actually changed.
    try:
        from mixar.modules.workflow.ui.operators import mode_slider_anim

        mode_slider_anim.note_flag("cinema", is_directing)
    except Exception:  # noqa: BLE001 — never let the pump break the topbar
        pass


def _move_profile_chip_last(cls) -> None:
    """Keep the profile chip right-most by re-appending it after us.

    Header `append` callbacks draw in registration order, and module
    registration order is not guaranteed, so whichever of the two lands
    first wins the left slot. Rather than depend on that, re-append the
    profile if it is already installed; if it registers later it naturally
    ends up after us. Either way the design order holds: pill, then profile.
    """
    try:
        from mixar.modules.space_mixie_chat.ui import topbar as chat_topbar

        profile_draw = getattr(chat_topbar, "_draw_topbar_profile_right", None)
        if profile_draw is None:
            return
        cls.remove(profile_draw)
    except Exception:  # noqa: BLE001 — not installed yet is the normal case
        return
    try:
        cls.append(profile_draw)
    except Exception:  # noqa: BLE001
        pass


def register():
    cls = bpy.types.TOPBAR_HT_upper_bar
    cls.append(draw_director_entry)
    _move_profile_chip_last(cls)


def unregister():
    try:
        bpy.types.TOPBAR_HT_upper_bar.remove(draw_director_entry)
    except (AttributeError, ValueError):
        pass
