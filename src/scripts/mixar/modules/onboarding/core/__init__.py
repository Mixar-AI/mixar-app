# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Onboarding Core

State machine, step table, and the tour driver that owns every
side effect (sidebar switching, prompt pre-fill, generation polling).
UI surfaces (operators, banners, menu) live under ``../ui``.
"""

from . import persistence, state, steps, tour_driver
from mixar.modules.onboarding.constants import OP_CARD_MODAL, OP_WELCOME

__all__ = ["persistence", "state", "steps", "tour_driver"]

_scheduled_welcome_emails: set[str] = set()


def _operator_registered(op_path: str) -> bool:
    import bpy

    namespace, op_name = op_path.split(".", 1)
    op_namespace = getattr(bpy.ops, namespace, None)
    return op_namespace is not None and hasattr(op_namespace, op_name)


def maybe_show_for_user(email: str) -> bool:
    """Public entry point — fire the welcome card if ``email`` hasn't
    completed or skipped the onboarding on this machine.

    Returns True if welcome was scheduled, False otherwise. Call
    this from the auth-success hook in ``auth_ops`` so the tour
    only ever opens after a successful sign-in.
    """
    import bpy

    from mixar.config.logging_config import get_logger
    logger = get_logger(__name__)

    if not email:
        return False
    if persistence.has_user_seen_onboarding(email):
        logger.debug("Onboarding: user %s has already seen the tour", email)
        return False
    if email in _scheduled_welcome_emails:
        return False

    # Schedule the welcome via a timer so we never invoke ops on a
    # background thread (auth check runs in a daemon). Startup auth can
    # complete while the splash is still open and before deferred UI
    # loading has registered the welcome operator, so keep polling until
    # both are ready.
    def _fire():
        try:
            from mixar.bootstrap import splash_menu
            if splash_menu.is_splash_visible():
                return 0.3
        except Exception:
            pass
        if not _operator_registered(OP_WELCOME) or not _operator_registered(OP_CARD_MODAL):
            return 0.2
        try:
            bpy.ops.mixar.onboarding_welcome("INVOKE_DEFAULT")
        except Exception as exc:
            logger.warning("Onboarding: welcome invoke failed: %s", exc)
        finally:
            _scheduled_welcome_emails.discard(email)
        return None

    try:
        _scheduled_welcome_emails.add(email)
        bpy.app.timers.register(_fire, first_interval=0.1)
    except Exception as exc:
        _scheduled_welcome_emails.discard(email)
        logger.warning("Onboarding: timer registration failed: %s", exc)
        return False

    logger.info("Onboarding: scheduling welcome for first-time user %s", email)
    return True
