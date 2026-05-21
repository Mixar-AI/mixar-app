# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""BSDF connection constants for paint module channels.

Maps Mixar channel names to Principled BSDF input sockets.
Targeting Blender 5.0 only - no legacy socket name support needed.
"""

# Channel name to BSDF socket mapping (Blender 5.0 socket names)
CHANNEL_TO_BSDF_SOCKET = {
    # Color channels (RGB)
    "Color": "Base Color",
    "Albedo": "Base Color",
    "Base Color": "Base Color",
    "Emission": "Emission Color",
    "Emission Color": "Emission Color",
    "Coat Tint": "Coat Tint",
    "Clearcoat Tint": "Coat Tint",
    # Value channels
    "Metallic": "Metallic",
    "Roughness": "Roughness",
    "Specular": "Specular IOR Level",
    "Specular Tint": "Specular Tint",
    "Subsurface": "Subsurface Weight",
    "Subsurface Weight": "Subsurface Weight",
    "Subsurface Scale": "Subsurface Scale",
    "Subsurface Anisotropy": "Subsurface Anisotropy",
    "Transmission": "Transmission Weight",
    "Transmission Weight": "Transmission Weight",
    "Sheen": "Sheen Weight",
    "Sheen Weight": "Sheen Weight",
    "Sheen Tint": "Sheen Tint",
    "Sheen Roughness": "Sheen Roughness",
    "Clearcoat": "Coat Weight",
    "Coat": "Coat Weight",
    "Coat Weight": "Coat Weight",
    "Clearcoat Roughness": "Coat Roughness",
    "Coat Roughness": "Coat Roughness",
    "Coat IOR": "Coat IOR",
    "Clearcoat IOR": "Coat IOR",
    "IOR": "IOR",
    "Anisotropic": "Anisotropic",
    "Anisotropic Rotation": "Anisotropic Rotation",
    "Emission Strength": "Emission Strength",
    "Alpha": "Alpha",
    # Normal/Vector channels
    "Normal": "Normal",
    "Bump": "Normal",
    "Clearcoat Normal": "Coat Normal",
    "Coat Normal": "Coat Normal",
    "Tangent": "Tangent",
}

# Prefixes for sockets that need companion weight/strength enabled
# Based on Mixar Paint bake_common.py pattern
BSDF_COMPANION_PREFIXES = ['Subsurface', 'Coat', 'Sheen', 'Emission']

# Companion socket suffix (all use "Weight" except Emission which uses "Strength")
# Key = prefix, Value = companion socket name
BSDF_COMPANION_SUFFIX_MAP = {
    'Subsurface': 'Subsurface Weight',
    'Coat': 'Coat Weight',
    'Sheen': 'Sheen Weight',
    'Emission': 'Emission Strength',
}

# Default values to set when creating channels with companions
# For emission, we want black default so painting adds emission
CHANNEL_DEFAULT_VALUES = {
    "Emission": (0.0, 0.0, 0.0, 1.0),
    "Emission Color": (0.0, 0.0, 0.0, 1.0),
}
