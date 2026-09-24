# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — pre-tour UI snapshot and restore.

``snapshot_state()`` records what the tour is about to move (UI mode,
moodboard drawer, island state and tab); ``restore_state(snapshot)`` puts
it back on a cancelled or error exit. Completed and user-exited tours run
``actions.tour_cleanup`` instead, which leaves the drawer open on purpose.
Split out of ``actions.py`` for size; every app write goes through the
same operators ``actions`` uses, so both modules share its rules: main
thread only, never raise, log and report ``False``.
"""

from mixar.config.config import UI_MODE_AI, UI_MODE_PRO
from mixar.config.logging_config import get_logger

from . import actions

_logger = get_logger(__name__)

ISLAND_PILL = "pill"
ISLAND_EXPANDED = "expanded"
ISLAND_NONE = "none"


def _island_state() -> str:
    actions._anchor_cache.invalidate()
    if actions._resting_pill_visible():
        return ISLAND_PILL
    if actions._shown_bubble_windows():
        return ISLAND_EXPANDED
    return ISLAND_NONE


def snapshot_state() -> dict:
    """UI state the tour will move. Every field degrades to a harmless
    default so a partial read never blocks the tour from starting."""
    snap = {"ui_mode": None, "drawer_amount": None, "island": ISLAND_NONE,
            "bubble_tab": None}
    try:
        snap["ui_mode"] = actions.get_ui_mode()
    except Exception as exc:  # noqa: BLE001
        _logger.debug("tour snapshot: ui mode unreadable: %s", exc)
    wm = actions._wm()
    if wm is not None:
        try:
            snap["drawer_amount"] = float(wm.mixar_moodboard_drawer_amount)
        except Exception as exc:  # noqa: BLE001
            _logger.debug("tour snapshot: drawer amount unreadable: %s", exc)
        try:
            tab = getattr(wm, "mixar_bubble_tab", None)
            snap["bubble_tab"] = tab if tab in actions.TAB_IDS else None
        except Exception as exc:  # noqa: BLE001
            _logger.debug("tour snapshot: bubble tab unreadable: %s", exc)
    try:
        snap["island"] = _island_state()
    except Exception as exc:  # noqa: BLE001
        _logger.debug("tour snapshot: island state unreadable: %s", exc)
    return snap


def _restore_ui_mode(mode) -> bool:
    if mode not in (UI_MODE_AI, UI_MODE_PRO):
        return True
    try:
        if actions.get_ui_mode() == mode:
            return True
    except Exception:  # noqa: BLE001
        pass
    with actions._LegacyRestartSuppressed():
        return actions._call_op("mixar.set_ui_mode_ai" if mode == UI_MODE_AI
                                else "mixar.set_ui_mode_pro")


def _restore_island(state: str) -> bool:
    if state == ISLAND_PILL:
        if not actions.pill_supported():
            return actions.island_expand({})
        if actions._bubble_windows():
            # No poll; CANCELLED means "already a pill".
            actions._call_op("mixar.bubble_minimise")
            return True
        try:
            from mixar.modules.agent_bubble.core.bubble_autoshow import try_invoke_bubble
            return bool(try_invoke_bubble(start_minimised=True))
        except Exception as exc:  # noqa: BLE001
            _logger.warning("tour restore: island pill invoke failed: %s", exc)
            return False
    if state == ISLAND_EXPANDED:
        return actions.island_expand({})
    # ISLAND_NONE (or unknown): leave whatever the tour opened alone —
    # closing a window the user may already be typing in is worse than an
    # extra island.
    return True


def restore_state(snapshot: dict) -> bool:
    """Best-effort, in the order the user notices: mode, drawer, island,
    tab. Each step is independent; the result is the AND of all of them."""
    snapshot = dict(snapshot or {})
    ok = True
    if not _restore_ui_mode(snapshot.get("ui_mode")):
        _logger.info("tour restore: ui mode not restored")
        ok = False
    amount = snapshot.get("drawer_amount")
    if amount is not None and not actions.drawer_set({"amount": amount}):
        _logger.info("tour restore: drawer not restored")
        ok = False
    if not _restore_island(str(snapshot.get("island") or ISLAND_NONE)):
        _logger.info("tour restore: island not restored")
        ok = False
    tab = snapshot.get("bubble_tab")
    if tab in actions.TAB_IDS and not actions.island_tab({"tab": tab}):
        _logger.info("tour restore: island tab not restored")
        ok = False
    actions._anchor_cache.invalidate()
    return ok
