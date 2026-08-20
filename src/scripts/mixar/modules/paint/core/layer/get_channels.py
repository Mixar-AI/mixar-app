# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re

from ...utils.blender_commons import get_srgb_name
from ...utils.common import get_write_height
from ...utils.constants import GAMMA
from ..layer.layer_utils import (
    get_height_channel,
    get_layer_and_root_ch_from_layer_ch,
    get_layer_from_node_name,
)
from ..node.get_nodes import get_layer_source
from ..subtree.get_subtree import (
    get_channel_source_tree,
    get_mask_tree,
    get_source_tree,
    get_tree,
)
from .check_layers import get_channel_enabled, get_layer_enabled, get_mask_enabled
from .....config.logging_config import get_logger
logger = get_logger(__name__)


def get_write_height_normal_channels(layer):
    """Get all normal channels in the layer that write height data.

    Args:
        layer: The layer object to check.

    Returns:
        list: A list of channel objects that are normal channels with write_height enabled.
    """
    mp = layer.id_data.yps

    channels = []

    for i, root_ch in enumerate(mp.channels):
        if root_ch.type == 'NORMAL':
            ch = layer.channels[i]
            write_height = get_write_height(ch)
            if write_height:
                channels.append(ch)

    return channels

def get_write_height_normal_channel(layer):
    """Get the first normal channel in the layer that writes height data.

    Args:
        layer: The layer object to check.

    Returns:
        Channel object if found, None otherwise.
    """
    mp = layer.id_data.mp

    for i, root_ch in enumerate(mp.channels):
        if root_ch.type == 'NORMAL':
            ch = layer.channels[i]
            write_height = get_write_height(ch)
            if write_height:
                return ch

    return None

def is_image_source_srgb(image, source):
    """Check if an image source is using sRGB colorspace.

    Args:
        image: The Blender image object to check.
        source: The image source node.

    Returns:
        bool: True if the image is using sRGB colorspace, False otherwise.
    """
    # HACK: Sometimes just loaded UDIM images has empty colorspace settings name
    if image.source == 'TILED' and image.colorspace_settings.name == '':
        return True

    return image.colorspace_settings.name == get_srgb_name()

def get_bump_chain(layer, ch=None):
    """Get the bump transition chain index for the layer.

    Args:
        layer: The layer object to check.
        ch: Optional channel object (currently unused). Default: None.

    Returns:
        int: The bump chain index, clamped to the number of masks in the layer.
    """
    mp = layer.id_data.mp

    chain = -1

    height_ch = get_height_channel(layer)
    if height_ch:
        chain = height_ch.transition_bump_chain

    return min(chain, len(layer.masks))

def get_layer_and_channel_prop_name_from_data_path(mp, channel_index, data_path):
    """Extract layer and property name from a data path string.

    This function parses data paths for channel properties in node inputs or
    layer channel paths.

    Args:
        mp: The MPaint material data object.
        channel_index: The channel index to look for.
        data_path: The data path string to parse.

    Returns:
        tuple: (layer, prop_name) where layer is the layer object (or None) and
               prop_name is the property name string (or empty string).
    """
    tree = mp.id_data

    layer = None
    prop_name = ''

    m0 = re.match(r'^nodes\["(.+)"\]\.inputs\[(\d+)\]\.default_value$', data_path)
    m1 = re.match(r'mp\.layers\[(\d+)\]\.channels\[' + str(channel_index) + '\]\.(.+)', data_path)

    if m0:
        # Get layer based on node name
        layer = get_layer_from_node_name(mp, m0.group(1))
        input_index = int(m0.group(2))

        if layer:
            # Get the input
            node = tree.nodes.get(layer.group_node)
            inp = node.inputs[input_index] if input_index <= len(node.inputs) else None

            if inp:
                # Get the channel index from input name
                m = re.match(r'\.channels\[' + str(channel_index) + '\]\.(.+)', inp.name)
                if m: prop_name = m.group(1)

    elif m1:
        try: layer = mp.layers[int(m1.group(1))]
        except Exception as e: logger.error("Error getting layer channel normal gamma value: %s", e)

        if layer:
            prop_name = m1.group(2)

    return layer, prop_name

def get_layer_channel_normal_gamma_value(ch, layer=None, root_ch=None):
    """Get the gamma correction value for a normal channel override.

    Args:
        ch: The channel object to check.
        layer: The parent layer object. Default: None (will auto-detect).
        root_ch: The root channel object. Default: None (will auto-detect).

    Returns:
        float: The gamma value to apply (1.0/GAMMA for sRGB images, 1.0 otherwise).
    """
    mp = ch.id_data.mp
    if not layer or not root_ch: layer, root_ch = get_layer_and_root_ch_from_layer_ch(ch)

    channel_enabled = get_channel_enabled(ch, layer, root_ch)
    if not channel_enabled: return 1.0

    image = None
    source = None
    layer_tree = get_tree(layer)
    if ch.override_1 and ch.override_1_type == 'IMAGE':
        source = layer_tree.nodes.get(ch.source_1)
        if source: image = source.image

    # Convert srgb normal map override to linear
    if ch.override_1 and image and is_image_source_srgb(image, source):
        return 1.0 / GAMMA

    return 1.0

def get_layer_mask_gamma_value(mask, mask_tree=None):
    """Get the gamma correction value for a mask image.

    Args:
        mask: The mask object to check.
        mask_tree: The mask's node tree. Default: None (will auto-detect).

    Returns:
        float: The gamma value to apply (1.0/GAMMA for sRGB images, 1.0 otherwise).
    """
    if not mask_tree: mask_tree = get_mask_tree(mask)

    if get_mask_enabled(mask) and mask.type == 'IMAGE':

        source = mask_tree.nodes.get(mask.source)
        image = source.image

        if not image: return 1.0

        # Convert srgb mask image to linear
        if is_image_source_srgb(image, source):
            return 1.0 / GAMMA

    return 1.0

def get_layer_gamma_value(layer):
    """Get the gamma correction value for a layer's image source.

    Args:
        layer: The layer object to check.

    Returns:
        float: The gamma value to apply based on image type and colorspace.
               Returns (1.0/GAMMA)^2 for float sRGB images,
               1.0/GAMMA for other sRGB images, or 1.0 otherwise.
    """
    mp = layer.id_data.mp

    if get_layer_enabled(layer) and layer.type == 'IMAGE':
        source_tree = get_source_tree(layer)
        source = source_tree.nodes.get(layer.source)
        image = source.image
        if image:

            # Should linearize srgb image and float image
            if not mp.use_linear_blending:
                if image.is_float:

                    # Float image with srgb will use double gamma calculation
                    if is_image_source_srgb(image, source):
                        return pow(1.0 / GAMMA, 2.0)
                    else: return 1.0 / GAMMA

                elif is_image_source_srgb(image, source):
                    return 1.0 / GAMMA

    return 1.0

def get_layer_channel_gamma_value(ch, layer=None, root_ch=None):
    """Get the gamma correction value for a layer channel.

    This function determines the appropriate gamma correction based on the channel's
    override settings, the root channel's colorspace, and whether linear blending is enabled.

    Args:
        ch: The channel object to check.
        layer: The parent layer object. Default: None (will auto-detect).
        root_ch: The root channel object. Default: None (will auto-detect).

    Returns:
        float: The gamma value to apply. Returns GAMMA for gamma space conversions,
               1.0/GAMMA for linearization, or 1.0 for no correction.
    """
    mp = ch.id_data.mp
    if not layer or not root_ch: layer, root_ch = get_layer_and_root_ch_from_layer_ch(ch)

    channel_enabled = get_channel_enabled(ch, layer, root_ch)
    if not channel_enabled: return 1.0

    source_tree = get_channel_source_tree(ch, layer)

    image = None
    source = None
    if ch.override and ch.override_type == 'IMAGE':
        source = source_tree.nodes.get(ch.source)
        if source: image = source.image
    elif layer.type == 'IMAGE':
        source = get_layer_source(layer)
        if source: image = source.image

    if mp.use_linear_blending:

        # Convert non image layer data to srgb if gamma space option is enabled
        if ( 
            not ch.override
            and ch.gamma_space 
            and root_ch.type != 'NORMAL' 
            and root_ch.colorspace == 'SRGB' 
            and ch.layer_input == 'RGB' 
            and layer.type not in {'IMAGE', 'BACKGROUND', 'GROUP'}
        ):
            return GAMMA

        # NOTE: Linear blending currently will only use gamma correction on normal channel
        if not ch.override_1 and image and is_image_source_srgb(image, source) and root_ch.type == 'NORMAL' and ch.normal_map_type in {'NORMAL_MAP', 'BUMP_NORMAL_MAP', 'VECTOR_DISPLACEMENT_MAP'}:
            return 1.0 / GAMMA

    else:
        # Convert srgb override image to linear
        if ch.override and image and is_image_source_srgb(image, source):
            return 1.0 / GAMMA

        # Convert non image override data to linear
        if ch.override and ch.override_type not in {'IMAGE'} and root_ch.type != 'NORMAL' and root_ch.colorspace == 'SRGB':
            return 1.0 / GAMMA

        # Convert non image layer data to linear
        if (
            not ch.override 
            and not ch.gamma_space 
            and root_ch.type != 'NORMAL' 
            and root_ch.colorspace == 'SRGB' 
            and ch.layer_input == 'RGB' 
            and layer.type not in {'IMAGE', 'BACKGROUND', 'GROUP'}
        ):
            return 1.0 / GAMMA

    return 1.0