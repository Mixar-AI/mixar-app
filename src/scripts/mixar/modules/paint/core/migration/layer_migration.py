# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer schema versioning for Substance Painter style architecture.

Current architecture (v2):
- Unified layer source for all channels (SP style)
- No per-channel override system
- Channels control: enable, blend mode, opacity, input selection (RGB/A/R/G/B)
- Different channel sources → create separate layers with specific channels enabled

Schema version is used to identify old files and auto-upgrade them.
"""

from .....config.logging_config import get_logger

logger = get_logger(__name__)

# Current schema version
CURRENT_SCHEMA_VERSION = 2


def ensure_schema_version(layer):
    """Ensure layer has current schema version set.

    Called when loading old files to mark them as current.

    Args:
        layer: The MLayer to check.
    """
    if getattr(layer, 'schema_version', 1) < CURRENT_SCHEMA_VERSION:
        layer_name = getattr(layer, 'name', 'Unknown')
        logger.debug(f"Updating layer '{layer_name}' to schema v{CURRENT_SCHEMA_VERSION}")
        layer.schema_version = CURRENT_SCHEMA_VERSION


def ensure_all_layers_schema(mp):
    """Ensure all layers have current schema version.

    Args:
        mp: The paint data structure containing layers.
    """
    if not hasattr(mp, 'layers'):
        return

    for layer in mp.layers:
        ensure_schema_version(layer)


def get_schema_version(layer):
    """Get the schema version of a layer.

    Args:
        layer: The MLayer to check.

    Returns:
        int: The schema version.
    """
    return getattr(layer, 'schema_version', CURRENT_SCHEMA_VERSION)
