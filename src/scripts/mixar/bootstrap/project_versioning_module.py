# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bootstrap the feature-flagged Lore checkpoint lifecycle.

The bootstrap path never imports the native Lore SDK. A dedicated worker owns
that import and every blocking `.wait()` / `.collect()` call.
"""

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def register() -> None:
    try:
        from mixar.modules.project_versioning.core import handlers

        handlers.register()
    except Exception as exc:  # noqa: BLE001 - optional pilot cannot break startup
        logger.error("project versioning bootstrap failed: %s", exc, exc_info=True)


def unregister() -> None:
    try:
        from mixar.modules.project_versioning.core import handlers

        handlers.unregister()
    except Exception as exc:  # noqa: BLE001 - shutdown must remain best effort
        logger.debug("project versioning unregister failed: %s", exc)
