# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Onboarding core: whether this device has seen the tour, and starting it on
a device that has not. The tour itself lives in ``tour/``; ``persistence``
stores the per-device "seen" flag.
"""

from . import persistence

__all__ = ["persistence", "maybe_show_tour", "mark_seen"]

_scheduled = False


def _operator_registered(op_path: str) -> bool:
    import bpy

    namespace, op_name = op_path.split(".", 1)
    op_namespace = getattr(bpy.ops, namespace, None)
    return op_namespace is not None and hasattr(op_namespace, op_name)


def mark_seen() -> None:
    """Persist the 'seen onboarding' flag for this device."""
    persistence.mark_device_seen_onboarding()


def maybe_show_tour(identity: str) -> bool:
    """Start the onboarding tour if this device hasn't seen it. Returns True
    if the tour was scheduled. ``identity`` is the session's email (an
    account's or a guest's); an empty one means no session yet, and the
    auth-success hook calls again once there is one. Called from that hook
    and again after a Zen/Engine mode choice.
    """
    import bpy

    from mixar.config.logging_config import get_logger
    logger = get_logger(__name__)

    global _scheduled
    if not identity:
        return False
    if persistence.has_device_seen_onboarding():
        logger.debug("Onboarding: this device has already seen the tour")
        return False
    if _scheduled:
        return False

    # A timer, so no operator ever runs on the auth daemon thread. Startup
    # auth can finish while the splash is still open and before deferred UI
    # loading has registered the tour operator, so keep polling for both.
    def _fire():
        global _scheduled
        try:
            from mixar.bootstrap import splash_menu
            # Wait until the user has left the splash (picked a workspace
            # mode): a tour started behind the splash would have its
            # first beat eaten by the mode click.
            if not splash_menu.onboarding_can_start():
                return 0.3
        except Exception:
            pass
        try:
            from mixar.modules.onboarding.core import tour as tour_pkg
        except Exception as exc:  # noqa: BLE001
            logger.warning("Onboarding: tour package unavailable: %s", exc)
            _scheduled = False
            return None
        if not tour_pkg.is_available():
            logger.warning("Onboarding: no tour video bundled; not starting")
            _scheduled = False
            return None
        op_path = tour_pkg.config.OP_TOUR
        if not _operator_registered(op_path):
            return 0.2
        try:
            namespace, op_name = op_path.split(".", 1)
            getattr(getattr(bpy.ops, namespace), op_name)("INVOKE_DEFAULT")
        except Exception as exc:
            logger.warning("Onboarding: %s invoke failed: %s", op_path, exc)
        finally:
            _scheduled = False
        return None

    try:
        _scheduled = True
        bpy.app.timers.register(_fire, first_interval=0.1)
    except Exception as exc:
        _scheduled = False
        logger.warning("Onboarding: timer registration failed: %s", exc)
        return False

    logger.info("Onboarding: scheduling the tour for this device")
    return True
