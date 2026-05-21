# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
UI-related constants for the paint module.

Contains layout scale factors, icon names, and other UI configuration values
to ensure consistency across all UI drawing code.
"""

# ========== Layout Scale Factors ==========
# Standard row height scales for consistent UI appearance

UI_SCALE_Y = 1.2               # Standard row height scale
UI_HEADER_SCALE_Y = 1.3        # Header row height scale
LABEL_SPLIT_FACTOR = 0.3       # Split factor for label:control ratio
NAME_SPLIT_FACTOR = 0.15       # Split factor for channel name column
SEPARATOR_FACTOR = 0.3         # Standard separator factor
SECTION_SEPARATOR_FACTOR = 0.2 # Section separator factor
IMAGE_BTN_SCALE_X = 0.8        # Image button scale


# ========== Icon Names ==========
class Icons:
    """Blender icon name constants for consistent icon usage.

    Use these constants instead of hardcoded icon strings to ensure
    consistency and make it easy to change icons across the codebase.
    """

    # Navigation/Expand icons
    EXPAND = 'TRIA_DOWN'
    COLLAPSE = 'TRIA_RIGHT'

    # Action icons
    REMOVE = 'X'
    MODIFIER = 'MODIFIER'
    CUSTOM_OVERRIDE = 'GREASEPENCIL'  # Pencil icon for custom toggle

    # Data type icons
    IMAGE = 'IMAGE_DATA'
    FILE_BROWSER = 'FILEBROWSER'

    # Brush/paint icons
    BRUSH = 'BRUSH_DATA'


# ========== Channel Detection ==========
# Sets of channel names for type detection (case-insensitive, checked via .upper())

AO_CHANNEL_NAMES = frozenset({
    'AO',
    'AMBIENT OCCLUSION',
    'AMBIENTOCCLUSION',
    'OCCLUSION'
})

EMISSION_CHANNEL_NAMES = frozenset({
    'EMISSION',
    'EMISSIVE'
})


# ========== Override Default Values ==========
class OverrideDefaults:
    """Default values for channel overrides by channel type.

    These are sensible defaults for PBR workflow:
    - Metallic: 0.0 (non-metal by default)
    - Roughness: 0.5 (mid-range)
    - AO: 1.0 (fully lit by default)
    """

    METALLIC = 0.0
    ROUGHNESS = 0.5
    AO = 1.0
    GENERIC_VALUE = 0.5
    EMISSION_COLOR = (0.0, 0.0, 0.0)  # Black (no emission)

    # Extended PBR channel defaults
    CLEARCOAT = 0.0          # No clear coat
    CLEARCOAT_ROUGHNESS = 0.03  # Smooth clear coat when enabled
    COAT_IOR = 0.5           # Default coat IOR (mid-range in 0-1 slider)
    SUBSURFACE = 0.0         # No subsurface scattering
    SUBSURFACE_SCALE = 0.05  # Small subsurface radius
    SUBSURFACE_ANISOTROPY = 0.0  # Isotropic subsurface scattering
    SHEEN = 0.0              # No sheen
    SHEEN_ROUGHNESS = 0.5    # Mid-range sheen roughness
    SHEEN_TINT_COLOR = (1.0, 1.0, 1.0)  # White sheen tint (RGB channel)
    SPECULAR = 0.5           # Default specular IOR level
    SPECULAR_TINT = 0.0      # No specular tint
    TRANSMISSION = 0.0       # Opaque (no transmission)
    IOR = 0.5                # Mid-range IOR (override_value is clamped 0-1)
    ANISOTROPIC = 0.0        # No anisotropy
    ANISOTROPIC_ROTATION = 0.0  # No rotation


# ========== Normal Map Types ==========
# Sets for checking normal map types

BUMP_NORMAL_TYPES = frozenset({'BUMP_MAP', 'BUMP_NORMAL_MAP'})
NORMAL_STRENGTH_TYPES = frozenset({'NORMAL_MAP', 'BUMP_NORMAL_MAP'})
