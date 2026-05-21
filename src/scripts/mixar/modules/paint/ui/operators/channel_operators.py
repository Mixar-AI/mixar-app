# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Channel management operators for Mixar

This module re-exports all channel-related operators for backward compatibility.
The actual implementations are split into separate modules:
- add_channel.py: CHANNELS_OT_AddChannel, CHANNELS_OT_AddChannelQuick
- remove_channel.py: CHANNELS_OT_RemoveChannel
- move_channel.py: CHANNELS_OT_MoveChannel
- channel_menu.py: CHANNELS_MT_AddChannelMenu
- layer_channel_ops.py: LAYERS_OT_ToggleLayerChannel, LAYERS_OT_DisableLayerChannel, LAYERS_OT_EnableLayerChannel
"""

# Re-export all classes for backward compatibility
from .add_channel import (
    CHANNELS_OT_AddChannel,
    CHANNELS_OT_AddChannelQuick,
)
from .remove_channel import CHANNELS_OT_RemoveChannel
from .move_channel import CHANNELS_OT_MoveChannel
from .channel_menu import CHANNELS_MT_AddChannelMenu
from .layer_channel_ops import (
    LAYERS_OT_ToggleLayerChannel,
    LAYERS_OT_DisableLayerChannel,
    LAYERS_OT_EnableLayerChannel,
    CHANNEL_OT_ToggleCustomOverride,
)

# Classes are registered by their respective source modules
# (add_channel.py, channel_menu.py, remove_channel.py, move_channel.py, layer_channel_ops.py)
# No classes tuple here to avoid double registration by bootstrap

# Expose all classes at module level for backward compatibility
__all__ = [
    "CHANNELS_OT_AddChannel",
    "CHANNELS_OT_AddChannelQuick",
    "CHANNELS_MT_AddChannelMenu",
    "CHANNELS_OT_RemoveChannel",
    "CHANNELS_OT_MoveChannel",
    "LAYERS_OT_ToggleLayerChannel",
    "LAYERS_OT_DisableLayerChannel",
    "LAYERS_OT_EnableLayerChannel",
    "CHANNEL_OT_ToggleCustomOverride",
]
