# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""scene_graph module bootstrap.

Registers the per-scene scene-graph property and the depsgraph/load handlers
that keep each scene's graph fresh. Imports the concrete submodules directly
(like workflow_module) to avoid relying on the synthetic package __init__.
"""

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def register():
    try:
        from mixar.modules.scene_graph.core import properties, watcher
        properties.register()
        watcher.register()
        logger.debug("scene_graph bootstrap: registered")
    except Exception as e:  # noqa: BLE001 - never break startup
        logger.error("scene_graph bootstrap: FAILED - %s", e, exc_info=True)


def unregister():
    try:
        from mixar.modules.scene_graph.core import properties, watcher
        watcher.unregister()
        properties.unregister()
    except Exception as e:  # noqa: BLE001 - defensive on shutdown
        logger.error("scene_graph bootstrap unregister failed: %s", e)
