# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Image operations helper functions.

This module re-exports all helper functions from the refactored modules
for backward compatibility. The functionality has been split into:

- float_image_helpers: Float image processing and saving
- image_format_helpers: Color mode, depth, and file format helpers
- image_save_helpers: Save/pack operations and temporary scene handling
"""

# Re-export float image helpers
from .float_image_helpers import (
    preserve_float_color_hack_before_saving,
    save_float_image,
    pack_float_image_27x,
    preserve_float_color_hack_before_packing,
)

# Re-export image format helpers
from .image_format_helpers import (
    color_mode_items,
    color_depth_items,
    update_save_as_file_format,
    get_file_format_items,
)

# Re-export image save helpers
from .image_save_helpers import (
    clean_object_references,
    create_temp_scene,
    unpack_image,
    remove_unpacked_image_path,
    save_pack_all,
)

# Re-export from image_ops_utils for backward compatibility
from .image_ops_utils import pack_image

# Export all functions for backward compatibility
__all__ = [
    # Float image helpers
    "preserve_float_color_hack_before_saving",
    "save_float_image",
    "pack_float_image_27x",
    "preserve_float_color_hack_before_packing",
    # Image format helpers
    "color_mode_items",
    "color_depth_items",
    "update_save_as_file_format",
    "get_file_format_items",
    # Image save helpers
    "clean_object_references",
    "create_temp_scene",
    "unpack_image",
    "remove_unpacked_image_path",
    "save_pack_all",
    # Image ops utils
    "pack_image",
]
