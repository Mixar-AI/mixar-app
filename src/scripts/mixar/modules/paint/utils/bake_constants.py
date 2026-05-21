# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Bake-related constants for the paint module.

Contains constants for bake types, items, labels, suffixes, and export formats.
"""

# =============================================================================
# EXPORT FORMAT CONSTANTS
# =============================================================================

# File format to extension mapping
EXPORT_FORMAT_EXTENSIONS = {
    'PNG': '.png',
    'OPEN_EXR': '.exr',
    'TIFF': '.tiff',
    'JPEG': '.jpg',
}

# File format items for EnumProperty
EXPORT_FILE_FORMAT_ITEMS = [
    ('PNG', 'PNG', 'PNG format - lossless with alpha support'),
    ('OPEN_EXR', 'OpenEXR', 'OpenEXR format - HDR with high precision'),
    ('TIFF', 'TIFF', 'TIFF format - lossless with wide compatibility'),
    ('JPEG', 'JPEG', 'JPEG format - lossy compression, no alpha'),
]

# Characters not allowed in filenames (cross-platform)
INVALID_FILENAME_CHARS = r'[<>:"/\\|?*\x00-\x1f]'

# Bake type items
bake_type_items = (
    ("AO", "Ambient Occlusion", ""),
    ("POINTINESS", "Pointiness", ""),
    ("CAVITY", "Cavity", ""),
    ("DUST", "Dust", ""),
    ("PAINT_BASE", "Paint Base", ""),
    ("BEVEL_NORMAL", "Bevel Normal", ""),
    ("BEVEL_MASK", "Bevel Grayscale", ""),
    ("MULTIRES_NORMAL", "Multires Normal", ""),
    ("MULTIRES_DISPLACEMENT", "Multires Displacement", ""),
    ("OTHER_OBJECT_NORMAL", "Other Objects Normal", "Other object's normal"),
    ("OTHER_OBJECT_EMISSION", "Other Objects Color", "Other object's color"),
    (
        "OTHER_OBJECT_CHANNELS",
        "Other Objects Channels",
        "Other object's Mixar Paint channels",
    ),
    ("SELECTED_VERTICES", "Selected Vertices/Edges/Faces", ""),
    ("FLOW", "Flow Map based on straight UVMap", ""),
    ("OBJECT_SPACE_NORMAL", "Object Space Normal", ""),
    ("POSITION", "Position Map", "Bake object/world space position"),
)

# Bake type labels
bake_type_labels = {
    "AO": "Ambient Occlusion",
    "POINTINESS": "Pointiness",
    "CAVITY": "Cavity",
    "DUST": "Dust",
    "PAINT_BASE": "Paint Base",
    "BEVEL_NORMAL": "Bevel Normal",
    "BEVEL_MASK": "Bevel Grayscale",
    "MULTIRES_NORMAL": "Multires Normal",
    "MULTIRES_DISPLACEMENT": "Multires Displacement",
    "OTHER_OBJECT_NORMAL": "Other Objects Normal",
    "OTHER_OBJECT_EMISSION": "Other Objects Color",
    "OTHER_OBJECT_CHANNELS": "Other Objects Channels",
    "SELECTED_VERTICES": "Selected Vertices",
    "FLOW": "Flow",
    "OBJECT_SPACE_NORMAL": "Object Space Normal",
    "POSITION": "Position Map",
}

# Bake type suffixes
bake_type_suffixes = {
    "AO": "AO",
    "POINTINESS": "Pointiness",
    "CAVITY": "Cavity",
    "DUST": "Dust",
    "PAINT_BASE": "Paint Base",
    "BEVEL_NORMAL": "Bevel Normal",
    "BEVEL_MASK": "Bevel Grayscale",
    "MULTIRES_NORMAL": "Normal Multires",
    "MULTIRES_DISPLACEMENT": "Displacement Multires",
    "OTHER_OBJECT_NORMAL": "OO Normal",
    "OTHER_OBJECT_EMISSION": "OO Color",
    "OTHER_OBJECT_CHANNELS": "OO Channel",
    "SELECTED_VERTICES": "Selected Vertices",
    "FLOW": "Flow",
    "OBJECT_SPACE_NORMAL": "Object Space Normal",
    "POSITION": "Position",
}
