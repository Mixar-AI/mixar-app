# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Automatic channel detection from texture filenames.

This module provides utilities to automatically detect which PBR channel
a texture map belongs to based on its filename. This enables automatic
assignment of textures to the correct channels when importing texture sets.

Supports common naming conventions from:
- Substance Painter/Designer
- Quixel Mixer
- ArmorPaint
- Generic PBR workflows
"""

import os
import re
from typing import Dict, List, Optional, Tuple


# Channel suffix patterns (case-insensitive)
# Each channel has a list of common suffixes used in texture naming
CHANNEL_SUFFIXES: Dict[str, List[str]] = {
    "Color": [
        "_basecolor", "_base_color", "_albedo", "_diffuse", "_color",
        "_col", "_diff", "_d", "_bc", "_alb",
    ],
    "Roughness": [
        "_roughness", "_rough", "_rgh", "_r",
    ],
    "Metallic": [
        "_metallic", "_metalness", "_metal", "_met", "_m",
    ],
    "Normal": [
        "_normal", "_norm", "_nrm", "_n", "_normalgl", "_normaldx",
        "_normal_opengl", "_normal_directx",
    ],
    "Height": [
        "_height", "_displacement", "_disp", "_bump", "_h",
    ],
    "AO": [
        "_ao", "_ambient_occlusion", "_ambientocclusion", "_occlusion",
        "_mixed_ao", "_cavity",
    ],
    "Emission": [
        "_emission", "_emissive", "_emit", "_e", "_glow",
    ],
    "Alpha": [
        "_alpha", "_opacity", "_mask", "_a", "_transparency",
    ],
    "Transmission": [
        "_transmission", "_translucency", "_trans",
    ],
    "Subsurface": [
        "_subsurface", "_sss", "_scattering",
    ],
    "Specular": [
        "_specular", "_spec", "_s", "_reflection",
    ],
    "Glossiness": [
        "_glossiness", "_gloss", "_smoothness", "_smooth",
    ],
    "Clearcoat": [
        "_clearcoat", "_coat", "_cc",
    ],
    "Anisotropic": [
        "_anisotropic", "_aniso", "_anisotropy",
    ],
    "Sheen": [
        "_sheen",
    ],
}

# Special handling for packed textures (multiple channels in one file)
PACKED_TEXTURE_PATTERNS: Dict[str, Dict[str, str]] = {
    # ORM: Occlusion, Roughness, Metallic (RGB channels)
    "_orm": {"R": "AO", "G": "Roughness", "B": "Metallic"},
    "_arm": {"R": "AO", "G": "Roughness", "B": "Metallic"},
    "_rma": {"R": "Roughness", "G": "Metallic", "B": "AO"},
    "_mra": {"R": "Metallic", "G": "Roughness", "B": "AO"},
    # MR: Metallic, Roughness
    "_metallicroughness": {"R": "Metallic", "G": "Roughness"},
    "_mr": {"R": "Metallic", "G": "Roughness"},
}


def detect_channel_from_filename(filename: str) -> Optional[str]:
    """Detect which PBR channel a texture belongs to from its filename.

    Args:
        filename: The texture filename (with or without path/extension)

    Returns:
        Channel name if detected (e.g., "Color", "Roughness", "Normal"),
        or None if no match found.

    Examples:
        >>> detect_channel_from_filename("wood_basecolor.png")
        "Color"
        >>> detect_channel_from_filename("metal_roughness_2k.exr")
        "Roughness"
        >>> detect_channel_from_filename("brick_normal_opengl.png")
        "Normal"
    """
    # Get just the filename without path and extension
    basename = os.path.basename(filename)
    name_without_ext = os.path.splitext(basename)[0].lower()

    # Check each channel's suffixes
    for channel, suffixes in CHANNEL_SUFFIXES.items():
        for suffix in suffixes:
            # Check if filename ends with this suffix (before any resolution tag)
            # Pattern: name_suffix or name_suffix_2k, etc.
            pattern = rf".*{re.escape(suffix)}(_\d+k)?$"
            if re.match(pattern, name_without_ext):
                return channel

            # Also check for suffix anywhere in the name (less strict)
            if suffix in name_without_ext:
                return channel

    return None


def detect_packed_texture(filename: str) -> Optional[Dict[str, str]]:
    """Detect if a texture is a packed multi-channel texture.

    Args:
        filename: The texture filename

    Returns:
        Dictionary mapping RGB channels to PBR channels, or None if not packed.

    Examples:
        >>> detect_packed_texture("material_orm.png")
        {"R": "AO", "G": "Roughness", "B": "Metallic"}
    """
    basename = os.path.basename(filename)
    name_without_ext = os.path.splitext(basename)[0].lower()

    for suffix, channel_map in PACKED_TEXTURE_PATTERNS.items():
        if suffix in name_without_ext:
            return channel_map

    return None


def extract_texture_set_name(filename: str) -> str:
    """Extract the base texture set name from a filename.

    Removes the channel suffix and resolution tags to get the base name.

    Args:
        filename: The texture filename

    Returns:
        Base texture set name

    Examples:
        >>> extract_texture_set_name("wood_basecolor_2k.png")
        "wood"
        >>> extract_texture_set_name("brick_normal.exr")
        "brick"
    """
    basename = os.path.basename(filename)
    name_without_ext = os.path.splitext(basename)[0].lower()

    # Remove resolution suffixes first
    name = re.sub(r"_\d+k$", "", name_without_ext)

    # Try to remove known channel suffixes
    for suffixes in CHANNEL_SUFFIXES.values():
        for suffix in suffixes:
            if name.endswith(suffix):
                return name[:-len(suffix)].rstrip("_")

    return name


def group_textures_by_set(filenames: List[str]) -> Dict[str, Dict[str, str]]:
    """Group textures by their texture set name.

    Args:
        filenames: List of texture filenames

    Returns:
        Dictionary mapping texture set names to their channel->filename mappings.

    Examples:
        >>> files = ["wood_basecolor.png", "wood_roughness.png", "brick_normal.png"]
        >>> group_textures_by_set(files)
        {
            "wood": {"Color": "wood_basecolor.png", "Roughness": "wood_roughness.png"},
            "brick": {"Normal": "brick_normal.png"}
        }
    """
    texture_sets: Dict[str, Dict[str, str]] = {}

    for filename in filenames:
        set_name = extract_texture_set_name(filename)
        channel = detect_channel_from_filename(filename)

        if channel:
            if set_name not in texture_sets:
                texture_sets[set_name] = {}
            texture_sets[set_name][channel] = filename

    return texture_sets


def find_matching_textures(
    directory: str,
    base_name: str,
    extensions: Optional[List[str]] = None
) -> Dict[str, str]:
    """Find all textures in a directory that match a base texture set name.

    Args:
        directory: Directory to search in
        base_name: Base texture set name to match
        extensions: List of valid extensions (default: common image formats)

    Returns:
        Dictionary mapping channel names to full file paths.
    """
    if extensions is None:
        extensions = [".png", ".jpg", ".jpeg", ".tga", ".exr", ".tiff", ".tif"]

    result: Dict[str, str] = {}

    if not os.path.isdir(directory):
        return result

    base_lower = base_name.lower()

    for filename in os.listdir(directory):
        # Check extension
        ext = os.path.splitext(filename)[1].lower()
        if ext not in extensions:
            continue

        # Check if it matches our base name
        name_lower = os.path.splitext(filename)[0].lower()
        if not name_lower.startswith(base_lower):
            continue

        # Detect channel
        channel = detect_channel_from_filename(filename)
        if channel:
            result[channel] = os.path.join(directory, filename)

    return result
