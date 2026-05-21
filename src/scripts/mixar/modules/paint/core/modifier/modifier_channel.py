# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Modifier channel type detection utilities.

This module provides functions for determining the channel type and colorspace
information for modifiers based on their position in the layer/channel hierarchy.
"""

import re


def get_modifier_channel_type(mod, return_non_color=False):
    """Determine the channel type and colorspace information for a modifier.

    Analyzes the modifier's position in the layer/channel hierarchy to determine
    what type of channel it operates on (RGB or VALUE) and whether it uses
    linear or sRGB colorspace. This version supports additional modifier paths
    including modifiers_1 collections.

    Args:
        mod: The modifier instance to analyze.
        return_non_color (bool, optional): If True, returns both channel type and
            non_color flag. If False, only returns channel type. Defaults to False.

    Returns:
        str or tuple: If return_non_color is False, returns the channel type as a string
            ('RGB' or 'VALUE'). If return_non_color is True, returns a tuple
            (channel_type, non_color) where non_color is a boolean indicating
            if linear colorspace is used.
    """
    mp = mod.id_data.mp
    match1 = re.match(r'mp\.layers\[(\d+)\]\.channels\[(\d+)\]\.modifiers\[(\d+)\]', mod.path_from_id())
    match2 = re.match(r'mp\.channels\[(\d+)\]\.modifiers\[(\d+)\]', mod.path_from_id())
    match3 = re.match(r'mp\.layers\[(\d+)\]\.modifiers\[(\d+)\]', mod.path_from_id())
    match4 = re.match(r'mp\.layers\[(\d+)\]\.channels\[(\d+)\]\.modifiers_1\[(\d+)\]', mod.path_from_id())

    if match1:
        root_ch = mp.channels[int(match1.group(2))]

        # Get non color flag and channel type
        non_color = root_ch.colorspace == 'LINEAR'
        channel_type = root_ch.type

    elif match2:
        root_ch = mp.channels[int(match2.group(1))]

        # Get non color flag and channel type
        non_color = root_ch.colorspace == 'LINEAR'
        channel_type = root_ch.type

    elif match3:

        # Image layer modifiers always use srgb colorspace
        layer = mp.layers[int(match3.group(1))]
        non_color = layer.type != 'IMAGE'
        channel_type = 'RGB'

    elif match4:
        non_color = True
        channel_type = 'RGB'

    else:
        non_color = True
        channel_type = 'VALUE'

    if return_non_color:
        return channel_type, non_color

    return channel_type
