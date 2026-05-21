# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Bake-related utility functions for the paint module.

Contains utility functions for bake operations, including filename sanitization.
"""

import re

from .bake_constants import INVALID_FILENAME_CHARS


def sanitize_filename(name):
    """Sanitize a string to be safe for use as a filename.

    Removes or replaces characters that are invalid in filenames across
    Windows, macOS, and Linux. Also handles edge cases like reserved names.

    Args:
        name: String to sanitize.

    Returns:
        str: Sanitized filename-safe string.
    """
    if not name:
        return "unnamed"

    # Replace invalid characters with underscore
    sanitized = re.sub(INVALID_FILENAME_CHARS, '_', name)

    # Replace multiple consecutive underscores with single underscore
    sanitized = re.sub(r'_+', '_', sanitized)

    # Remove leading/trailing underscores and spaces
    sanitized = sanitized.strip('_ ')

    # Handle Windows reserved names (CON, PRN, AUX, NUL, COM1-9, LPT1-9)
    reserved_names = {
        'CON', 'PRN', 'AUX', 'NUL',
        'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
        'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9',
    }
    if sanitized.upper() in reserved_names:
        sanitized = f"_{sanitized}_"

    # Ensure we have a valid name
    if not sanitized:
        sanitized = "unnamed"

    return sanitized
