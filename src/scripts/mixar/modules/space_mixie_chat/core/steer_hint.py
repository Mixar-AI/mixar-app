# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tells a user who stopped a running run that typing would have steered it.

Users press Stop to redirect Mixie (the next message is a correction or the
same prompt resent) without knowing a message sent mid-run joins it and keeps
the work (core/composer_send.py:is_interjection). The island's placeholder and
Steer button say so while the run works; this toast says it once per app
session at the moment it matters, after a Stop on a run that could have been
steered.
"""

from mixar.modules.common.i18n import n_

TOAST_ID = "mixie_steer_hint"

# Once per app session: module state, never written into the .blend.
_shown = False


def steerable(session, scene) -> bool:
    """A message sent now would join the open run instead of starting a turn."""
    from ..constants import SessionState
    return session.get_state(scene) == SessionState.BUSY and session.run_open(scene)


def after_stop(was_steerable: bool, origin: str) -> bool:
    """Show the tip after the user's own Stop on a steerable run; True if shown."""
    global _shown
    if _shown or not was_steerable or origin not in ('stop_button', 'escape_key'):
        return False
    try:
        from mixar.modules.common.notifications import get_notification_store
        get_notification_store().push(
            'info', n_("Tip: you can steer Mixie without stopping"),
            n_("Type your change while Mixie works and press Steer. "
               "It adjusts the running work and keeps what it has built."),
            id=TOAST_ID, ttl_ms=9000)
    except Exception:  # noqa: BLE001 — a tip never breaks Stop
        return False
    _shown = True
    return True
