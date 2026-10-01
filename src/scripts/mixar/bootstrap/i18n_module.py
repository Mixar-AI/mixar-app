# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Registers Mixar's interface translations for the active UI language."""

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def register():
    try:
        from mixar.modules.common.i18n.core import runtime
        runtime.register()
    except Exception:
        logger.error("Mixar translations failed to register", exc_info=True)


def unregister():
    try:
        from mixar.modules.common.i18n.core import runtime
        runtime.unregister()
    except Exception:
        logger.debug("Mixar translations failed to unregister", exc_info=True)
