# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Usage Meter Bootstrap Module

Starts the poller that keeps the top-bar credit meter current. The poller
itself is a timer supervisor (``mixar.modules.common.usage.core.poller``)
that no-ops while logged out, so starting it unconditionally at boot is
safe — it only reaches the network once a session exists.

Loaded by bootstrap/__init__.py during the startup sequence.
"""

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def register() -> None:
    """Called by bootstrap during startup — start the refresh timer."""
    try:
        from mixar.modules.common.usage.core.poller import start

        start()
    except Exception as exc:  # noqa: BLE001 — never block startup
        logger.warning("Usage meter poller failed to start: %s", exc)


def unregister() -> None:
    """Called by bootstrap during shutdown — cancel the refresh timer."""
    try:
        from mixar.modules.common.usage.core.poller import stop

        stop()
    except Exception:  # noqa: BLE001 — module may already be gone
        pass
