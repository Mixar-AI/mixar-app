# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer enum helper functions and constants."""

from ....core.node.node_utils import get_active_mpaint_node

# Constants for default suffixes
DEFAULT_NEW_IMG_SUFFIX = " Layer"
DEFAULT_NEW_VCOL_SUFFIX = " VCol"
DEFAULT_NEW_VDM_SUFFIX = " VDM"


def channel_items(self, context):
    """Generate list of channel items for UI enumeration.

    Args:
        self: The property being updated.
        context: Blender context.

    Returns:
        list: List of tuples containing channel enum items in format
            (identifier, name, description, icon, number).
    """
    items = []

    node = get_active_mpaint_node()
    if node:
        mp = node.node_tree.mp
        for i, ch in enumerate(mp.channels):
            # Add two spaces to prevent text from being translated
            text_ch_name = ch.name + "  "
            # Use Blender built-in icon names directly since get_icon() returns None
            icon_name = 'MATERIAL'  # Default icon for channels
            items.append((str(i), text_ch_name, "", icon_name, i))

    items.append(("-1", "All Channels", "", 'MATERIAL', len(items)))

    return items


def get_normal_map_type_items(self, context):
    """Generate list of normal map type items for UI enumeration.

    Args:
        self: The property being updated.
        context: Blender context.

    Returns:
        list: List of tuples containing normal map type enum items.
    """
    items = []

    items.append(("BUMP_MAP", "Bump Map", ""))
    items.append(("NORMAL_MAP", "Normal Map", ""))
    items.append(("BUMP_NORMAL_MAP", "Bump + Normal Map", ""))
    items.append(("VECTOR_DISPLACEMENT_MAP", "Vector Displacement Map", ""))
    return items
