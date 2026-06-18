# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""operation_history module bootstrap.

Registers the persistent per-scene history-id property and installs the manual-op capture
handlers + timer. Imports the concrete submodules directly (like scene_graph_module /
workflow_module) to avoid relying on the synthetic package init.
"""

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def register():
    try:
        from mixar.modules.operation_history.core import capture_service, properties
        properties.register()
        capture_service.register()
        logger.debug("operation_history bootstrap: registered")
    except Exception as e:  # never break startup
        logger.error("operation_history bootstrap: FAILED - %s", e, exc_info=True)


def unregister():
    try:
        from mixar.modules.operation_history.core import capture_service, properties
        capture_service.unregister()
        properties.unregister()
    except Exception as e:
        logger.error("operation_history bootstrap unregister failed: %s", e)
