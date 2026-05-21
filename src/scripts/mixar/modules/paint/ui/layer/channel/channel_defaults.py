# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Channel-specific default values for per-channel sources.

This module provides intelligent defaults for solid color/value settings
based on channel type. This enables proper initialization when using
solid fills for different PBR channels.
"""


# Channel type to default value mapping
# Format: {channel_name_pattern: {"type": "color"|"value", "value": default}}
CHANNEL_DEFAULTS = {
    # Color/Albedo channels - mid-gray color
    "color": {"type": "color", "value": (0.5, 0.5, 0.5)},
    "albedo": {"type": "color", "value": (0.5, 0.5, 0.5)},
    "diffuse": {"type": "color", "value": (0.5, 0.5, 0.5)},
    "basecolor": {"type": "color", "value": (0.5, 0.5, 0.5)},
    "base_color": {"type": "color", "value": (0.5, 0.5, 0.5)},

    # Metallic - default to non-metallic (0)
    "metallic": {"type": "value", "value": 0.0},
    "metal": {"type": "value", "value": 0.0},
    "metalness": {"type": "value", "value": 0.0},

    # Roughness - default to mid-rough (0.5)
    "roughness": {"type": "value", "value": 0.5},
    "rough": {"type": "value", "value": 0.5},

    # Smoothness (inverse of roughness) - default to mid-smooth (0.5)
    "smoothness": {"type": "value", "value": 0.5},
    "smooth": {"type": "value", "value": 0.5},
    "glossiness": {"type": "value", "value": 0.5},
    "gloss": {"type": "value", "value": 0.5},

    # Normal - flat normal (0.5, 0.5, 1.0 in tangent space)
    "normal": {"type": "color", "value": (0.5, 0.5, 1.0)},
    "norm": {"type": "color", "value": (0.5, 0.5, 1.0)},
    "nrm": {"type": "color", "value": (0.5, 0.5, 1.0)},

    # Height/Displacement - mid-height (0.5)
    "height": {"type": "value", "value": 0.5},
    "displacement": {"type": "value", "value": 0.5},
    "disp": {"type": "value", "value": 0.5},
    "bump": {"type": "value", "value": 0.5},

    # Ambient Occlusion - full white (no occlusion), RGB type
    "ao": {"type": "color", "value": (1.0, 1.0, 1.0)},
    "ambient_occlusion": {"type": "color", "value": (1.0, 1.0, 1.0)},
    "ambientocclusion": {"type": "color", "value": (1.0, 1.0, 1.0)},
    "occlusion": {"type": "color", "value": (1.0, 1.0, 1.0)},

    # Emission - black (no emission)
    "emission": {"type": "color", "value": (0.0, 0.0, 0.0)},
    "emissive": {"type": "color", "value": (0.0, 0.0, 0.0)},

    # Alpha/Opacity - fully opaque (1.0)
    "alpha": {"type": "value", "value": 1.0},
    "opacity": {"type": "value", "value": 1.0},
    "transparency": {"type": "value", "value": 0.0},  # Inverse

    # Transmission - no transmission (0)
    "transmission": {"type": "value", "value": 0.0},

    # Subsurface - no subsurface (0)
    "subsurface": {"type": "value", "value": 0.0},
    "sss": {"type": "value", "value": 0.0},

    # Specular - default specular (0.5)
    "specular": {"type": "value", "value": 0.5},
    "spec": {"type": "value", "value": 0.5},

    # IOR - default glass-like (1.5 normalized to 0-1 scale)
    "ior": {"type": "value", "value": 0.5},

    # Clearcoat / Coat
    "clearcoat": {"type": "value", "value": 0.0},
    "coat": {"type": "value", "value": 0.0},
    "clearcoat roughness": {"type": "value", "value": 0.03},
    "coat roughness": {"type": "value", "value": 0.03},
    "coat ior": {"type": "value", "value": 0.5},

    # Anisotropic
    "anisotropic": {"type": "value", "value": 0.0},
    "aniso": {"type": "value", "value": 0.0},
    "anisotropic rotation": {"type": "value", "value": 0.0},

    # Sheen
    "sheen": {"type": "value", "value": 0.0},
    "sheen roughness": {"type": "value", "value": 0.5},
    "sheen tint": {"type": "color", "value": (1.0, 1.0, 1.0)},

    # Subsurface extended
    "subsurface scale": {"type": "value", "value": 0.05},
    "subsurface anisotropy": {"type": "value", "value": 0.0},

    # Specular Tint
    "specular tint": {"type": "value", "value": 0.0},
}


def get_default_solid_for_channel(channel_name):
    """Get the appropriate default solid value for a channel type.

    Args:
        channel_name: Name of the channel (e.g., "Color", "Roughness", "Normal")

    Returns:
        dict: {"type": "color"|"value", "value": default_value}
              - For "color" type, value is (R, G, B) tuple
              - For "value" type, value is a single float
    """
    name_lower = channel_name.lower().strip()

    # Try exact match first
    if name_lower in CHANNEL_DEFAULTS:
        return CHANNEL_DEFAULTS[name_lower]

    # Try substring match
    for pattern, default in CHANNEL_DEFAULTS.items():
        if pattern in name_lower:
            return default

    # Fallback: assume it's a value channel with 0.5 default
    return {"type": "value", "value": 0.5}


def apply_channel_defaults(channel_source, channel_name):
    """Apply appropriate defaults to a MChannelSource based on channel type.

    Args:
        channel_source: MChannelSource property group to configure
        channel_name: Name of the channel for determining defaults
    """
    defaults = get_default_solid_for_channel(channel_name)

    if defaults["type"] == "color":
        channel_source.solid_color = defaults["value"]
        channel_source.solid_value = 0.5  # Not used for color channels
    else:
        channel_source.solid_value = defaults["value"]
        channel_source.solid_color = (0.5, 0.5, 0.5)  # Not used for value channels


def is_color_channel(channel_name):
    """Check if a channel typically uses color (RGB) values.

    Args:
        channel_name: Name of the channel

    Returns:
        bool: True if channel uses color values, False if scalar
    """
    defaults = get_default_solid_for_channel(channel_name)
    return defaults["type"] == "color"


def is_value_channel(channel_name):
    """Check if a channel typically uses scalar (grayscale) values.

    Args:
        channel_name: Name of the channel

    Returns:
        bool: True if channel uses scalar values, False if color
    """
    defaults = get_default_solid_for_channel(channel_name)
    return defaults["type"] == "value"
