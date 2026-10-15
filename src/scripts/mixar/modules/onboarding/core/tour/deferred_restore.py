# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — the UI restore after a file load ended the tour.

``load_pre`` may only do synchronous, non-operator teardown: running
``mixar.set_ui_mode_*``, the drawer or the island operators there would
queue notifiers against the outgoing Main and could open an Agent Bubble
window during the file read, which must never find one. So a tour stopped
by ``load_pre`` hands its pre-tour snapshot here; a one-shot handler on
``load_post`` AND ``load_post_fail`` (``@persistent``, so the read does not
drop it; a failed read must restore too, never leave the snapshot for a
much later load) removes itself and registers a timer that runs the
transient reset and a reduced restore:

* the UI mode (a persisted global setting);
* the island, only while someone is still signed in.

The drawer amount and the island tab are skipped: they belonged to the
outgoing file's window state. Nothing runs when a new tour started in the
meantime.
"""

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger

_logger = get_logger(__name__)

RESTORE_DELAY_S = 0.1

_pending = None   # the pre-tour snapshot waiting for load_post, or None


def schedule(snapshot) -> None:
    """Hold ``snapshot`` until the file load finishes (``load_post``)."""
    global _pending
    _pending = dict(snapshot or {})
    for handlers in _handler_lists():
        if _on_load_post not in handlers:
            handlers.append(_on_load_post)


def pending():
    return _pending


def cancel() -> None:
    global _pending
    _pending = None
    _remove_handler()


def _handler_lists():
    handlers = bpy.app.handlers
    return [lst for lst in (getattr(handlers, "load_post", None),
                            getattr(handlers, "load_post_fail", None))
            if lst is not None]


def _remove_handler() -> None:
    for handlers in _handler_lists():
        try:
            if _on_load_post in handlers:
                handlers.remove(_on_load_post)
        except Exception:  # noqa: BLE001
            pass


@persistent
def _on_load_post(*_args):
    _remove_handler()
    if _pending is None:
        return
    try:
        bpy.app.timers.register(run, first_interval=RESTORE_DELAY_S, persistent=True)
    except Exception as exc:  # noqa: BLE001
        _logger.debug("tour: deferred restore timer unavailable: %s", exc)


def _signed_in() -> bool:
    try:
        return bool(getattr(bpy.context.window_manager, "mixie_chat_is_logged_in", False))
    except Exception:  # noqa: BLE001
        return False


def _tour_running() -> bool:
    try:
        from . import session as tour_session
        live = tour_session.current()
        return live is not None and bool(live.running)
    except Exception:  # noqa: BLE001
        return False


def run():
    """Timer body: reset the tour's transients and restore mode + island."""
    global _pending
    snapshot, _pending = _pending, None
    if snapshot is None or _tour_running():
        return None
    try:
        from . import actions_extra
        actions_extra.reset_transients()
    except Exception as exc:  # noqa: BLE001
        _logger.debug("tour: deferred transient reset skipped: %s", exc)
    reduced = {"ui_mode": snapshot.get("ui_mode")}
    if _signed_in():
        reduced["island"] = snapshot.get("island")
    try:
        from . import actions
        actions.restore_state(reduced)
    except Exception as exc:  # noqa: BLE001
        _logger.debug("tour: deferred restore skipped: %s", exc)
    return None
