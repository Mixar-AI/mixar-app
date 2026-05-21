# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Addon and version utilities for the paint module."""

import random
import string

from .constants import FEATURE_NAME


def version_tuple(version_string):
    """Convert a version string to a tuple of integers.

    Args:
        version_string (str): Version string in dot-separated format (e.g., "1.2.3").

    Returns:
        tuple: Tuple of integers representing the version, or (0, 0, 0) if empty string.
    """
    return (
        tuple(map(int, version_string.split(".")))
        if version_string != ""
        else (0, 0, 0)
    )


def get_addon_name():
    """Get the addon's internal name.

    Returns:
        str: The feature name constant.
    """
    return FEATURE_NAME


def get_addon_title():
    """Get the addon's display title.

    Returns:
        str: The feature name constant.
    """
    return FEATURE_NAME


def id_generator(size=4, chars=string.ascii_uppercase + string.digits):
    """Generate a random ID string.

    Args:
        size (int, optional): Length of the generated ID. Defaults to 4.
        chars (str, optional): Characters to use for ID generation. Defaults to uppercase letters and digits.

    Returns:
        str: Randomly generated ID string.
    """
    return "".join(random.choice(chars) for _ in range(size))
