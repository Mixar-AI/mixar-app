# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Onboarding core: who has seen the tour, and starting it for first-time
users. The tour itself lives in ``tour/``; ``persistence`` stores the
per-machine "seen" list.
"""

from . import persistence

__all__ = ["persistence", "maybe_show_for_user", "mark_current_user_seen"]

_scheduled_emails: set[str] = set()
# The signed-in email the tour was last launched for. The seen flag falls
# back to it: the per-Scene ``mixie_chat_user_id`` is only stamped on the
# scene that was current at sign-in, so it can be empty when the tour ends.
_tour_email = ""


def _operator_registered(op_path: str) -> bool:
    import bpy

    namespace, op_name = op_path.split(".", 1)
    op_namespace = getattr(bpy.ops, namespace, None)
    return op_namespace is not None and hasattr(op_namespace, op_name)


def _scene_user_id(scene) -> str:
    value = getattr(scene, "mixie_chat_user_id", "") if scene is not None else ""
    return value if isinstance(value, str) else ""


def _resolve_seen_email(context=None, email=None) -> str:
    """Who finished the tour, in order: the explicit ``email``; the live
    sign-in on the current scene (a different login mid-tour wins); the
    email the tour was launched for; the first scene carrying a user id."""
    import bpy

    if isinstance(email, str) and email:
        return email
    try:
        scene = (context or bpy.context).scene
    except Exception:  # noqa: BLE001
        scene = None
    live = _scene_user_id(scene)
    if live:
        return live
    if _tour_email:
        return _tour_email
    try:
        for other in bpy.data.scenes:
            found = _scene_user_id(other)
            if found:
                return found
    except Exception:  # noqa: BLE001
        pass
    return ""


def mark_current_user_seen(context=None, email=None) -> None:
    """Persist the 'seen onboarding' marker for the signed-in user (see
    ``_resolve_seen_email`` for where the email comes from)."""
    from mixar.config.logging_config import get_logger
    logger = get_logger(__name__)
    resolved = _resolve_seen_email(context, email)
    if not resolved:
        # INFO, not debug: a tour that keeps coming back is otherwise
        # undiagnosable from the log.
        logger.info("onboarding: no signed-in user id, seen flag not written")
        return
    persistence.mark_user_seen_onboarding(resolved)


def maybe_show_for_user(email: str) -> bool:
    """Start the onboarding tour if ``email`` hasn't seen it on this
    machine. Returns True if the tour was scheduled. Called from the
    auth-success hook, so the tour only ever opens after a sign-in, and
    again after the splash's mode choice for a user who still hasn't
    seen it.
    """
    import bpy

    from mixar.config.logging_config import get_logger
    logger = get_logger(__name__)

    if not email:
        return False
    if persistence.has_user_seen_onboarding(email):
        logger.debug("Onboarding: user %s has already seen the tour", email)
        return False
    if email in _scheduled_emails:
        return False

    # A timer, so no operator ever runs on the auth daemon thread. Startup
    # auth can finish while the splash is still open and before deferred UI
    # loading has registered the tour operator, so keep polling for both.
    def _fire():
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
            _scheduled_emails.discard(email)
            return None
        if not tour_pkg.is_available():
            logger.warning("Onboarding: no tour video bundled; not starting")
            _scheduled_emails.discard(email)
            return None
        op_path = tour_pkg.config.OP_TOUR
        if not _operator_registered(op_path):
            return 0.2
        global _tour_email
        _tour_email = email
        try:
            namespace, op_name = op_path.split(".", 1)
            getattr(getattr(bpy.ops, namespace), op_name)("INVOKE_DEFAULT")
        except Exception as exc:
            logger.warning("Onboarding: %s invoke failed: %s", op_path, exc)
        finally:
            _scheduled_emails.discard(email)
        return None

    try:
        _scheduled_emails.add(email)
        bpy.app.timers.register(_fire, first_interval=0.1)
    except Exception as exc:
        _scheduled_emails.discard(email)
        logger.warning("Onboarding: timer registration failed: %s", exc)
        return False

    logger.info("Onboarding: scheduling the tour for first-time user %s", email)
    return True
