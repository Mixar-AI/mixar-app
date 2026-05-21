# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Common utility modules shared across Mixar modules."""

from .image_utils import (
    image_to_png_bytes,
    compress_image_for_upload,
    compress_file_for_upload,
    compress_for_service,
    compress_file_for_service,
    load_image_from_base64,
    load_image_from_url,
    add_image_to_moodboard,
    IMAGE_BASE_SIZE,
    IMAGE_SPACING,
)

from .image_compression_config import (
    CompressionSettings,
    DEFAULT_COMPRESSION,
    SERVICE_SETTINGS,
    get_compression_settings,
)

from .platform_utils import (
    is_macos,
    is_windows,
    is_linux,
    get_command_modifier,
    get_keymap_modifier,
    format_shortcut,
    trigger_ui_redraw,
)

from .mixie_space_utils import (
    MIXIE_SPACE_AVAILABLE,
    show_generation_error,
    count_selected_moodboard_images,
    get_first_selected_moodboard_image,
    get_selected_moodboard_items,
)
