# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — app actions for the Library and Creator Program beats.

Split out of ``actions.py`` for size; ``actions`` merges ``EXTRA_ACTIONS``
into its registry. Every action returns True on success and never raises.

* ``library_source`` flips the island Library between the generations grid
  (``AI``) and the connected Blender asset libraries (``LIBRARY``), where the
  "Add Library…" button lives.
* ``help_menu_open`` opens the REAL top-bar Help menu under its own button
  (``Window.mixar_tour_menu_open``: the public popup API, no synthesized
  input) with the Creator Program row highlighted; ``help_menu_close``
  closes it again. The highlight is a WindowManager ID property the Help
  menu's draw reads, so it disappears with the menu.

``reset_transients`` undoes whatever these left behind; the session calls it
on every stop, whatever the reason.
"""

import bpy

from mixar.config.logging_config import get_logger

from . import anchors

_logger = get_logger(__name__)

HELP_MENU = "TOPBAR_MT_help"
HIGHLIGHT_KEY = "mixar_tour_highlight"   # WindowManager ID property
HIGHLIGHT_CREATOR = "creator_program"
LIBRARY_SOURCES = ("AI", "LIBRARY")

_library_source_changed = False


def _wm():
    try:
        return bpy.context.window_manager
    except Exception:  # noqa: BLE001
        return None


def library_source(args: dict) -> bool:
    global _library_source_changed
    source = str(args.get("source", "AI"))
    if source not in LIBRARY_SOURCES:
        _logger.warning("tour actions: unknown library source %r", source)
        return False
    wm = _wm()
    if wm is None or not hasattr(wm, "mixar_generations_source"):
        return False
    try:
        if wm.mixar_generations_source != source:
            wm.mixar_generations_source = source
            _library_source_changed = source != "AI"
    except Exception as exc:  # noqa: BLE001
        _logger.warning("tour actions: library_source(%s) failed: %s", source, exc)
        return False
    return True


def _set_highlight(value: str) -> None:
    wm = _wm()
    if wm is None:
        return
    try:
        if value:
            wm[HIGHLIGHT_KEY] = value
        elif HIGHLIGHT_KEY in wm:
            del wm[HIGHLIGHT_KEY]
    except Exception as exc:  # noqa: BLE001
        _logger.debug("tour actions: highlight %r failed: %s", value, exc)


def help_menu_open(args: dict) -> bool:
    """Open the Help menu with the Creator Program row highlighted."""
    window = anchors.main_window()
    if window is None or not hasattr(window, "mixar_tour_menu_open"):
        return False
    _set_highlight(str(args.get("highlight", HIGHLIGHT_CREATOR)))
    try:
        opened = bool(window.mixar_tour_menu_open(menu=HELP_MENU))
    except Exception as exc:  # noqa: BLE001
        _logger.warning("tour actions: help_menu_open failed: %s", exc)
        opened = False
    if not opened:
        _set_highlight("")
    return opened


def help_menu_close(_args: dict) -> bool:
    _set_highlight("")
    window = anchors.main_window()
    if window is None or not hasattr(window, "mixar_tour_menu_close"):
        return False
    try:
        return bool(window.mixar_tour_menu_close())
    except Exception as exc:  # noqa: BLE001
        _logger.debug("tour actions: help_menu_close failed: %s", exc)
        return False


def reset_transients() -> None:
    """Close the tour's menu, drop the highlight, put the Library back on
    the generations grid if the tour moved it."""
    global _library_source_changed
    help_menu_close({})
    if _library_source_changed:
        library_source({"source": "AI"})
        _library_source_changed = False


EXTRA_ACTIONS = {
    "library_source": library_source,
    "help_menu_open": help_menu_open,
    "help_menu_close": help_menu_close,
}
