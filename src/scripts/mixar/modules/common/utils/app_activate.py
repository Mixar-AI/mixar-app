# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bring Mixar in front of other applications.

Wraps the native ``mixar.activate_app`` operator (``MIXAR_OT_activate_app``
in ``space_agent_bubble.cc``: ``[NSApp activateIgnoringOtherApps:YES]`` on
macOS, ``SetForegroundWindow`` on the main window on Windows, a no-op
elsewhere). The only caller is the sign-in flow, after a browser SSO login
SUCCEEDED: the user finished in the browser and expects to land back in
the app. Never call it on a failed or cancelled login. Main thread only.
"""

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

OPERATOR_NAME = "activate_app"


def activate_app() -> bool:
    """Best-effort: True when the native operator ran and finished.

    A build without the operator (or a platform where it is a no-op)
    returns False and logs at debug level; the caller does nothing else.
    """
    try:
        ops_mixar = getattr(bpy.ops, "mixar", None)
        op = getattr(ops_mixar, OPERATOR_NAME, None) if ops_mixar is not None else None
        if op is None:
            logger.debug("activate_app: native operator unavailable")
            return False
        result = op()
    except Exception as exc:  # noqa: BLE001 — an unbuilt op raises on call
        logger.debug("activate_app: native operator failed: %s", exc)
        return False
    finished = 'FINISHED' in result
    if not finished:
        logger.debug("activate_app: native operator returned %s", result)
    return finished
