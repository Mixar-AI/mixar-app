# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Where AI Provider Settings opens, and keeping the island out of its way.

The Agent Bubble island is an always-on-top OS window. A props dialog is a
region inside the main window, so the island is drawn over it whatever the
dialog does — and the island's chip row, where the toggle lives, sits right
where a cursor-anchored dialog would open. So the dialog:

- opens in the main window (a popup inside the small island window would be
  clipped over the composer);
- opens centred, not under the cursor (``mixar_invoke_props_dialog_centered``;
  stock ``invoke_props_dialog`` on a build without it);
- minimises an open island to its pill for as long as it is up, and restores
  it once the dialog closes, so the result (the toggle) is visible again.
"""

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# True while this dialog minimised the island and owes it a restore.
_island_minimised = False


def _dialog_host_window(context):
    """The main window the dialog should open over, or None to stay put.

    An Agent Bubble window (island or pill) is a small always-on-top overlay:
    a props dialog opened there is clipped to its height. Prefer the window
    with the most areas that is NOT a bubble — the primary workspace window.
    """
    try:
        from mixar.modules.agent_bubble.core.bubble_lifecycle import (
            is_agent_bubble_window,
        )
    except Exception:  # noqa: BLE001 — stripped builds: stay in place
        return None
    try:
        if not is_agent_bubble_window(context.window):
            return None
        candidates = [w for w in context.window_manager.windows
                      if not is_agent_bubble_window(w) and w.screen.areas]
    except Exception:  # noqa: BLE001
        return None
    if not candidates:
        return None
    return max(candidates, key=lambda w: len(w.screen.areas))


def _minimise_island() -> None:
    """Pill the island if it is open. The raw C++ operator returns CANCELLED
    when there is no island or it is already a pill — then nothing is owed."""
    global _island_minimised
    try:
        _island_minimised = bpy.ops.mixar.bubble_minimise() == {'FINISHED'}
    except (AttributeError, RuntimeError):  # no island module / no bubble
        _island_minimised = False


def _restore_island():
    try:
        bpy.ops.mixar.bubble_restore()
    except (AttributeError, RuntimeError) as exc:
        logger.debug("Island restore after provider settings failed: %s", exc)
    return None  # one-shot timer


def dialog_closed() -> None:
    """Called from the dialog's execute()/cancel(). The restore runs on the
    next tick: the popup is still being torn down inside this call."""
    global _island_minimised
    if not _island_minimised:
        return
    _island_minimised = False
    bpy.app.timers.register(_restore_island, first_interval=0.05)


def open_dialog(context, operator, width):
    """Invoke ``operator``'s props dialog over the main window, centred, with
    the island minimised. Returns the invoke result."""
    wm = context.window_manager
    _minimise_island()

    def invoke():
        if hasattr(wm, 'mixar_invoke_props_dialog_centered'):
            return wm.mixar_invoke_props_dialog_centered(operator, width=width)
        return wm.invoke_props_dialog(operator, width=width, title="")

    # Override the WINDOW only: the bubble's screen is a temporary one and
    # `temp_override(screen=...)` refuses it outright ("Overriding context
    # with an active temporary screen isn't supported").
    host = _dialog_host_window(context)
    try:
        if host is not None and host != context.window:
            with context.temp_override(window=host):
                return invoke()
        return invoke()
    except Exception:
        dialog_closed()
        raise


classes = ()
