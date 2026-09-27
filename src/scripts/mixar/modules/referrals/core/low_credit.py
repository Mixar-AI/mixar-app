# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Low-credit toast pointing at Refer a Friend.

The usage poller hands every applied reading here. When the balance crosses
``LOW_CREDIT_THRESHOLD`` while the app is open, a sticky toast on the shared
notification stack offers **Refer a Friend**. Its button walks the user's
own path: the profile card opens under its chip, the pointer lands on the
card's Refer a Friend row and the dialog opens from there
(``open_via_profile``).

Live crossings only: the previous reading must be above the threshold. A user
who opens the app already low sees nothing (the first reading follows the
empty snapshot), and a dip re-arms once the balance climbs back above it. A
failed fetch keeps the previous figures (``state.snapshot_error``), so it can
neither fire nor hide a crossing.
"""

from __future__ import annotations

import json

import bpy

from mixar.config.logging_config import get_logger

from .. import constants as C
from .invites import format_credits

logger = get_logger(__name__)


def _metered(snapshot) -> bool:
    return (
        snapshot is not None
        and getattr(snapshot, "fetched_at", 0.0) > 0.0
        and getattr(snapshot, "has_subscription", False)
    )


def crossed(previous, current, threshold: int = C.LOW_CREDIT_THRESHOLD) -> bool:
    if not (_metered(previous) and _metered(current)) or getattr(current, "error", ""):
        return False
    return previous.credits_remaining > threshold >= current.credits_remaining


def toast_copy(credits_left: int) -> tuple:
    return ("Running low on credits",
            f"You have {format_credits(credits_left)} credits left. "
            "Invite friends to earn bonus credits.")


def notify_if_crossed(previous, current) -> bool:
    """Main thread. Push the toast on a crossing; True when it did."""
    if not crossed(previous, current):
        return False
    from mixar.modules.common.notifications.store import (
        NotificationAction,
        get_notification_store,
    )

    title, body = toast_copy(current.credits_remaining)
    get_notification_store().push(
        type_str="warning",
        title=title,
        body=body,
        priority="high",
        id=C.LOW_CREDIT_NOTIFICATION_ID,
        dismissible=True,
        actions=[NotificationAction(label="Refer a Friend",
                                    operator="mixar.refer_friend_via_profile",
                                    style="primary")],
    )
    logger.info("Low-credit referral toast shown at %s credits",
                current.credits_remaining)
    return True


def dismiss_toast() -> None:
    """Refer a Friend opened (from the toast or the card): the toast is done."""
    try:
        from mixar.modules.common.notifications.store import get_notification_store

        get_notification_store().dismiss(C.LOW_CREDIT_NOTIFICATION_ID)
    except Exception as exc:  # noqa: BLE001 — never block the dialog
        logger.debug("low-credit toast dismiss failed: %s", exc)


# ---------------------------------------------------------------------------
# Toast button: open Refer a Friend the way the user would, from the card
# ---------------------------------------------------------------------------

PROFILE_PANEL = "MIXAR_PT_profile"
REFER_OP = "MIXAR_OT_refer_friend"      # as the widget dump names it
_POLL_SECONDS = 0.05
_POLL_LIMIT = 30                         # ~1.5 s for the card to lay out


def _main_window():
    """The largest window that is not an Agent Bubble overlay."""
    best, best_px = None, -1
    for window in bpy.context.window_manager.windows:
        try:
            if any(a.type == "AGENT_BUBBLE" for a in window.screen.areas):
                continue
            px = int(window.width) * int(window.height)
        except Exception:  # noqa: BLE001
            continue
        if px > best_px:
            best, best_px = window, px
    return best


def refer_row_center(widgets, window_ptr):
    """Centre of the open card's Refer a Friend row (pure; tests pin it)."""
    for widget in widgets or ():
        if not (isinstance(widget, dict) and widget.get("popup")
                and widget.get("op") == REFER_OP):
            continue
        try:
            if int(widget.get("w")) != window_ptr:
                continue
            xmin, ymin, xmax, ymax = (float(v) for v in widget["rect"])
        except (KeyError, TypeError, ValueError):
            continue
        return int((xmin + xmax) / 2), int((ymin + ymax) / 2)
    return None


def _card_row(window):
    try:
        text = bpy.context.window_manager.mixar_qa_ui_dump or ""
        widgets = json.loads(text).get("widgets") if text else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("low-credit toast: widget dump unreadable: %s", exc)
        return None
    return refer_row_center(widgets, window.as_pointer())


def _invoke_refer(window) -> None:
    try:
        with bpy.context.temp_override(window=window):
            bpy.ops.mixar.refer_friend('INVOKE_DEFAULT')
    except Exception as exc:  # noqa: BLE001
        logger.error("low-credit toast: Refer a Friend failed to open: %s", exc)


def open_via_profile() -> None:
    """Open the profile card under its chip, put the pointer on its Refer a
    Friend row (hover-lit, where a click would land) and open the dialog
    there. Degrades to opening the dialog directly when the card cannot open
    (a build without ``Window.mixar_tour_popover_open``, no chip on screen)."""
    window = _main_window()
    if window is None:
        return
    opened = False
    try:
        opener = getattr(window, "mixar_tour_popover_open", None)
        opened = bool(opener and opener(panel=PROFILE_PANEL))
    except Exception as exc:  # noqa: BLE001
        logger.debug("low-credit toast: profile card did not open: %s", exc)
    if not opened:
        _invoke_refer(window)
        return

    window_ptr = window.as_pointer()
    tries = [0]

    def _step():
        target = _main_window()
        if target is None or target.as_pointer() != window_ptr:
            return None
        row = _card_row(target)
        if row is None:
            tries[0] += 1
            if tries[0] < _POLL_LIMIT:
                return _POLL_SECONDS
            _invoke_refer(target)   # the card never laid out: open the dialog anyway
            return None
        try:
            target.cursor_warp(*row)
        except Exception as exc:  # noqa: BLE001
            logger.debug("low-credit toast: cursor warp failed: %s", exc)
        bpy.app.timers.register(lambda: _invoke_refer(target), first_interval=0.12)
        return None

    bpy.app.timers.register(_step, first_interval=_POLL_SECONDS)
