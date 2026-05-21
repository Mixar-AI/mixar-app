# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Channel detection utilities for the paint module.

Provides functions to identify special channel types (AO, Emission, etc.)
based on channel name and type. These functions are used across multiple
layer handlers to determine channel-specific behavior.
"""

from .ui_constants import (
    AO_CHANNEL_NAMES,
    EMISSION_CHANNEL_NAMES,
    OverrideDefaults,
)


def is_ao_channel(root_ch) -> bool:
    """Check if channel is an AO (Ambient Occlusion) channel.

    Args:
        root_ch: Root channel with name and type info.

    Returns:
        True if this is an AO channel (RGB type with AO-like name).
    """
    if root_ch.type not in {'VALUE', 'RGB'}:
        return False
    name_upper = root_ch.name.upper().replace(' ', '').replace('_', '')
    # Check both with and without space/underscore normalization
    return (root_ch.name.upper() in AO_CHANNEL_NAMES or
            name_upper in {'AO', 'AMBIENTOCCLUSION', 'OCCLUSION'})


def is_emission_channel(root_ch) -> bool:
    """Check if channel is an Emission channel.

    Args:
        root_ch: Root channel with name and type info.

    Returns:
        True if this is an Emission channel (RGB type with Emission-like name).
    """
    if root_ch.type != 'RGB':
        return False
    return root_ch.name.upper() in EMISSION_CHANNEL_NAMES


def is_color_channel(root_ch) -> bool:
    """Check if channel is the main Color channel.

    Args:
        root_ch: Root channel with name and type info.

    Returns:
        True if this is the Color channel (RGB type named 'Color').
    """
    return root_ch.type == 'RGB' and root_ch.name.lower() == 'color'


def get_override_default_value(root_ch) -> float:
    """Get the default override value for a VALUE channel.

    Returns appropriate defaults based on channel name for PBR workflow:
    - Metallic: 0.0
    - Roughness: 0.5
    - AO: 1.0
    - Others: 0.5

    Args:
        root_ch: Root channel with name info.

    Returns:
        Default float value based on channel name.
    """
    name_lower = root_ch.name.lower()
    if 'metallic' in name_lower:
        return OverrideDefaults.METALLIC
    elif 'roughness' in name_lower:
        return OverrideDefaults.ROUGHNESS
    elif 'ao' in name_lower or 'occlusion' in name_lower:
        return OverrideDefaults.AO
    return OverrideDefaults.GENERIC_VALUE


def get_override_default_color(root_ch) -> tuple:
    """Get the default override color for an RGB channel.

    Args:
        root_ch: Root channel with name info.

    Returns:
        Default color tuple (R, G, B) based on channel name.
    """
    if is_emission_channel(root_ch):
        return OverrideDefaults.EMISSION_COLOR
    return (1.0, 1.0, 1.0)  # White for other RGB channels
