# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""User-visible feedback for the SAM mask tools (Magic Select, Box, Lasso).

Every result these tools produce arrives in a callback run from a timer, and
``Operator.report()`` issued there never reaches the screen: Blender flushes
an operator's reports only when the operator call itself returns. So the
tools talk to the user through two channels that DO work from the main-thread
timer: the workspace status line (progress and hints) and the notification
toasts (terminal failures). ``describe_failure`` is pure so the wording is
unit-tested rather than only observable in a running app.
"""

from typing import Tuple

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

UPLOAD_FAILED_TITLE = "Couldn't prepare the image"
NO_OBJECT_TITLE = "No object found here"
NO_CREDITS_TITLE = "Not enough credits"
UNAVAILABLE_TITLE = "Segmentation is unavailable right now"
TIMED_OUT_TITLE = "Segmentation timed out"
FAILED_TITLE = "Segmentation failed"


def describe_failure(message: str, *, upload: bool = False) -> Tuple[str, str]:
    """(title, body) for a failed upload or segmentation, in the user's words.

    The service's message is kept as the body wherever it says something a
    person can act on (a NET-* support code, a plain-English server message);
    the generic branches replace opaque HTTP statuses with a next step.
    """
    text = (message or "").strip()
    lower = text.lower()
    if "402" in lower or "credit" in lower:
        return NO_CREDITS_TITLE, "Segmentation uses credits. Add credits and try again."
    if not upload and ("no object" in lower or "empty" in lower):
        return NO_OBJECT_TITLE, "Try clicking on a different spot of the object."
    if "timed out" in lower or "timeout" in lower:
        return TIMED_OUT_TITLE, "The service took too long. Try again."
    if "503" in lower or "unavailable" in lower:
        return UNAVAILABLE_TITLE, "Try again in a minute."
    if upload:
        return UPLOAD_FAILED_TITLE, text or "Try again."
    return FAILED_TITLE, text or "Try again."


def set_status(text) -> None:
    """Show ``text`` on every window's status line; ``None`` restores it.

    Main thread only. Guarded because the tools' callbacks run from timers
    after the operator's own context is gone.
    """
    try:
        import bpy

        for window in bpy.context.window_manager.windows:
            workspace = window.workspace
            if workspace is not None:
                workspace.status_text_set(text)
    except Exception as exc:  # noqa: BLE001 — feedback must never break a tool
        logger.debug("Mask tool status text failed: %s", exc)


def clear_status() -> None:
    set_status(None)


def toast(kind: str, title: str, body: str = "") -> None:
    """Best-effort notification toast (``kind``: info, warning, error)."""
    try:
        from ...common.notifications import get_notification_store

        get_notification_store().push(kind, title, body=body or "")
    except Exception as exc:  # noqa: BLE001
        logger.debug("Mask tool toast failed: %s", exc)


def toast_failure(message: str, *, upload: bool = False) -> None:
    title, body = describe_failure(message, upload=upload)
    if title == NO_CREDITS_TITLE:
        # Out of credits gets the whole-window banner, not a toast.
        try:
            from ...common.notifications.credits_banner import request_credits_banner

            request_credits_banner("mask_tool")
            return
        except Exception as exc:  # noqa: BLE001 — fall back to the toast
            logger.debug("Mask tool credits banner failed: %s", exc)
    kind = "warning" if title == NO_OBJECT_TITLE else "error"
    toast(kind, title, body)
