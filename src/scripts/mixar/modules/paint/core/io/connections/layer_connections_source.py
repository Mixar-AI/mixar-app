# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer connection source processing - coordinator module.

This module re-exports source processing, channel override, and related functions
for layer node reconnection from submodules.

Submodules:
- layer_connections_override: Override and normal override processing
- layer_connections_channel: Group, source type, procedural, modifier processing
"""

# Re-export override-related functions
from .layer_connections_override import (
    connect_channel_direction_sources,
    connect_channel_uv_neighbor,
    process_channel_override,
    process_normal_override,
)

# Re-export channel-related functions
from .layer_connections_channel import (
    connect_intensity_multiplier,
    process_channel_modifiers,
    process_channel_source_type,
    process_group_channel,
    process_group_normal_channel,
    process_procedural_channel,
)


# Define __all__ for explicit exports
__all__ = [
    # Override functions
    'process_channel_override',
    'connect_channel_uv_neighbor',
    'connect_channel_direction_sources',
    'process_normal_override',
    # Channel functions
    'process_group_channel',
    'process_channel_source_type',
    'process_procedural_channel',
    'connect_intensity_multiplier',
    'process_group_normal_channel',
    'process_channel_modifiers',
]
