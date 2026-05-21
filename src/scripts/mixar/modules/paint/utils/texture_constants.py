# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Texture and image-related constants for the paint module.

Contains constants for texture coordinates, image resolution, interpolation,
paint tools, and valid file extensions.
"""

# Texture coordinate lists
texcoord_lists = [
    "Generated",
    "Normal",
    # 'UV',
    "Object",
    "Camera",
    "Window",
    "Reflection",
]

# Texture coordinate type items
texcoord_type_items = (
    ("Generated", "Generated", ""),
    ("Normal", "Normal", ""),
    ("UV", "UV", ""),
    ("Object", "Object", ""),
    ("Camera", "Camera", ""),
    ("Window", "Window", ""),
    ("Reflection", "Reflection", ""),
    ("Decal", "Decal", ""),
)

# Mask texture coordinate type items
mask_texcoord_type_items = (
    ("Generated", "Generated", ""),
    ("Normal", "Normal", ""),
    ("UV", "UV", ""),
    ("Object", "Object", ""),
    ("Camera", "Camera", ""),
    ("Window", "Window", ""),
    ("Reflection", "Reflection", ""),
    ("Decal", "Decal", ""),
    ("Layer", "Use Layer Vector", ""),
)

# Interpolation type items
interpolation_type_items = (
    ("Linear", "Linear", "Linear interpolation."),
    ("Closest", "Closest", "No interpolation (sample closest texel)."),
    ("Cubic", "Cubic", "Cubic interpolation."),
)

# Image resolution items
image_resolution_items = (
    ("512", "512", "Create a 512x512 texture image"),
    ("1024", "1024", "Create a 1024x1024 texture image"),
    ("2048", "2048", "Create a 2048x2048 texture image"),
    ("4096", "4096", "Create a 4096x4096 texture image"),
)

# Resolution options (merged from texturing module)
RESOLUTION_OPTIONS = [
    (512, '512', '512x512 pixels'),
    (1024, '1024', '1024x1024 pixels'),
    (2048, '2048', '2048x2048 pixels'),
    (4096, '4096', '4096x4096 pixels'),
]

# Default resolution
DEFAULT_RESOLUTION = 2048

# Valid image file extensions
valid_image_extensions = [".jpg", ".gif", ".png", ".tga", ".jpeg", ".mp4", ".webp"]

# Eraser names by mode
eraser_names = {
    "TEXTURE_PAINT": "Eraser Tex",
    "VERTEX_PAINT": "Eraser Vcol",
    "SCULPT": "Eraser Paint",
}

# Texture eraser asset names
tex_eraser_asset_names = ["Erase Hard", "Erase Hard Pressure", "Erase Soft"]

# Default texture brushes
tex_default_brushes = [
    "Airbrush",
    "Paint Hard",
    "Paint Hard Pressure",
    "Paint Soft",
    "Paint Soft Pressure",
]
