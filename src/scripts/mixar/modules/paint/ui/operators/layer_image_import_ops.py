# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer image import operators for Mixar.

This module contains operators for importing multiple images as a single layer,
with automatic channel detection based on filename patterns.
"""

import os
import re

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty, CollectionProperty
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper

from .....config.logging_config import get_logger

logger = get_logger(__name__)

from ...core.io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ...core.io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ...core.layer.layer_utils import get_uv_layers
from ...core.node.create_nodes import check_new_node
from ...core.node.node_utils import get_active_mpaint_node
from ...core.subtree.get_subtree import get_tree
from ..layer.callbacks.layer_override_callbacks import (
    check_override_layer_channel_nodes,
    check_override_1_layer_channel_nodes,
)
from ...utils.blender_commons import (
    get_active_material,
    get_active_object,
    get_noncolor_name,
    get_unique_name,
    get_user_preferences,
    load_image,
)
from ...utils.constants import TEMP_UV, texcoord_type_items
from ..layer.helpers.layer_create_helpers import add_new_layer
from ..other.base_operator import OpenImage
from ..utils.ui_refresh import request_ui_refresh


# Synonym library for matching filenames to channels
SYNONYM_LIBS = {
    'color': ['albedo', 'diffuse', 'basecolor', 'base_color', 'base color', 'd', 'col', 'diff'],
    'metallic': ['metalness', 'metal', 'm', 'met', 'metalic'],
    'roughness': ['glossiness', 'smoothness', 'rough', 'r', 'gloss', 'smooth'],
    'normal': ['nor', 'nrm', 'n', 'normalmap', 'normal_map'],
    'alpha': ['opacity', 'a', 'transparency', 'trans'],
    'ambient occlusion': ['ao', 'occlusion', 'ambientocclusion'],
}

# Synonyms that should invert the value (glossiness -> roughness)
INVERT_SYNONYMS = {'glossiness', 'smoothness', 'gloss', 'smooth'}

# Bump/height synonyms for normal channel
BUMP_SYNONYMS = {'displacement', 'height', 'bump', 'disp'}


def is_synonym_in_image_name(synonym, filename):
    """Check if synonym exists in filename as suffix or separator-bounded.

    Args:
        synonym: The synonym to search for (e.g., 'color', 'metallic')
        filename: The filename without extension

    Returns:
        bool: True if synonym is found in filename pattern
    """
    name_lower = filename.lower()
    synonym_lower = synonym.lower()

    # Handle multi-word synonyms (e.g., 'base color')
    if ' ' in synonym_lower:
        # Replace spaces with common separators
        variants = [
            synonym_lower.replace(' ', '_'),
            synonym_lower.replace(' ', '-'),
            synonym_lower.replace(' ', ''),
            synonym_lower,
        ]
        for variant in variants:
            if variant in name_lower:
                return True
        return False

    # Check for exact match at end of string
    if name_lower.endswith(synonym_lower):
        return True

    # Check for separator-bounded patterns (_color, -color, .color)
    separators = ['_', '-', '.', ' ']
    for sep in separators:
        # Pattern: separator + synonym (e.g., _color)
        if sep + synonym_lower in name_lower:
            return True
        # Pattern: synonym + separator (e.g., color_)
        if synonym_lower + sep in name_lower:
            return True

    return False


def match_image_to_channel(image, mp):
    """Match an image to a channel based on filename patterns.

    Args:
        image: Blender image object
        mp: The mixar paint data structure

    Returns:
        tuple: (channel_index, matched_synonym, is_bump) or (None, None, False) if no match
    """
    # Get filename without extension
    if image.filepath:
        filename = os.path.splitext(os.path.basename(image.filepath))[0]
    else:
        filename = os.path.splitext(image.name)[0]

    # Remove trailing digits and spaces
    filename = re.sub(r'[\d\s]+$', '', filename)

    for ch_idx, root_ch in enumerate(mp.channels):
        ch_name = root_ch.name.lower()

        # Get synonyms for this channel
        synonyms = []
        if ch_name in SYNONYM_LIBS:
            synonyms = SYNONYM_LIBS[ch_name]
        synonyms = list(synonyms) + [ch_name]  # Include channel name itself

        # For normal channel, also check bump synonyms
        if root_ch.type == 'NORMAL':
            synonyms.extend(BUMP_SYNONYMS)

        for synonym in synonyms:
            if is_synonym_in_image_name(synonym, filename):
                is_bump = synonym in BUMP_SYNONYMS
                return ch_idx, synonym, is_bump

    return None, None, False


class LAYERS_OT_OpenImagesToLayer(Operator, ImportHelper, OpenImage):
    """Open multiple images as a single layer with auto-channel detection"""

    bl_idname = "layers.open_images_to_layer"
    bl_label = "Open Images as Layer"
    bl_description = "Load multiple images (color, metallic, roughness, normal) and create a layer with auto-channel assignment"
    bl_options = {'REGISTER', 'UNDO'}

    # File browser filter
    filter_glob: StringProperty(
        default="*.png;*.jpg;*.jpeg;*.tif;*.tiff;*.bmp;*.exr;*.hdr;*.tga",
        options={'HIDDEN'}
    )

    texcoord_type: EnumProperty(
        name='Coordinate Type',
        description='Texture coordinate type',
        items=texcoord_type_items,
        default='UV'
    )

    uv_map: StringProperty(
        name='UV Map',
        default='',
        description='UV map to use for texture coordinates'
    )

    uv_map_coll: CollectionProperty(type=bpy.types.PropertyGroup)

    @classmethod
    def poll(cls, context):
        """Check if operator can be executed."""
        return get_active_mpaint_node() is not None

    def invoke(self, context, event):
        """Initialize and open file browser."""
        obj = get_active_object()

        # Get default UV map
        if obj and obj.type == 'MESH':
            uv_layers = get_uv_layers(obj)
            if uv_layers:
                self.uv_map = uv_layers[0].name

            # UV Map collections update
            self.uv_map_coll.clear()
            for uv in uv_layers:
                if not uv.name.startswith(TEMP_UV):
                    self.uv_map_coll.add().name = uv.name

        return self.running_fileselect_modal(context, event)

    def execute(self, context):
        """Create layer from selected images."""
        import time
        T = time.time()

        node = get_active_mpaint_node()
        if not node or not node.node_tree:
            self.report({'ERROR'}, "No active Mixar node found")
            return {'CANCELLED'}

        group_tree = node.node_tree
        mp = group_tree.mp
        obj = get_active_object()
        mat = get_active_material()

        # Load selected images
        loaded_images = self.get_loaded_images()

        if not loaded_images or all(img is None for img in loaded_images):
            self.report({'ERROR'}, "No images selected")
            return {'CANCELLED'}

        # Filter out None images
        images = [img for img in loaded_images if img is not None]

        if not images:
            self.report({'ERROR'}, "Failed to load any images")
            return {'CANCELLED'}

        # Match images to channels
        channel_matches = []  # [(ch_idx, image, synonym, is_bump), ...]
        used_channels = set()

        for image in images:
            ch_idx, synonym, is_bump = match_image_to_channel(image, mp)

            if ch_idx is not None:
                # For normal channel, allow both bump and normal maps
                if mp.channels[ch_idx].type == 'NORMAL':
                    key = (ch_idx, 'bump' if is_bump else 'normal')
                else:
                    key = (ch_idx, None)

                if key not in used_channels:
                    channel_matches.append((ch_idx, image, synonym, is_bump))
                    used_channels.add(key)
                else:
                    logger.info(f"Skipping duplicate channel match: {image.name} -> {synonym}")

        if not channel_matches:
            self.report({'ERROR'}, "Could not match any images to channels. "
                       "Use naming like: texture_color.png, texture_roughness.png, texture_normal.png")
            # Clean up loaded images
            for img in images:
                if img.users == 0:
                    bpy.data.images.remove(img)
            return {'CANCELLED'}

        # Sort by channel index, prioritize color channel first
        channel_matches.sort(key=lambda x: (0 if mp.channels[x[0]].type == 'RGB' else 1, x[0]))

        # Use first matched image for layer creation
        primary_ch_idx, primary_image, primary_synonym, primary_is_bump = channel_matches[0]

        # Set relative paths
        for _, image, _, _ in channel_matches:
            if self.relative and bpy.data.filepath:
                try:
                    image.filepath = bpy.path.relpath(image.filepath)
                except Exception:
                    pass

        # Set colorspace for non-color channels
        for ch_idx, image, synonym, _ in channel_matches:
            root_ch = mp.channels[ch_idx]
            if root_ch.colorspace == 'LINEAR' and not image.is_dirty:
                image.colorspace_settings.name = get_noncolor_name()

        # Determine normal map type based on what we found
        normal_matches = [(ch_idx, img, syn, is_bump) for ch_idx, img, syn, is_bump in channel_matches
                         if mp.channels[ch_idx].type == 'NORMAL']

        has_bump = any(is_bump for _, _, _, is_bump in normal_matches)
        has_normal = any(not is_bump for _, _, _, is_bump in normal_matches)

        if has_bump and has_normal:
            normal_map_type = 'BUMP_NORMAL_MAP'
        elif has_normal:
            normal_map_type = 'NORMAL_MAP'
        else:
            normal_map_type = 'BUMP_MAP'

        # Generate unique layer name
        layer_name = os.path.splitext(os.path.basename(primary_image.filepath or primary_image.name))[0]
        # Remove channel suffix from name
        for synonyms in SYNONYM_LIBS.values():
            for syn in synonyms:
                if layer_name.lower().endswith('_' + syn) or layer_name.lower().endswith('-' + syn):
                    layer_name = layer_name[:-(len(syn) + 1)]
                    break
        layer_name = get_unique_name(layer_name, mp.layers)

        # Halt updates during layer creation
        ori_halt_update = mp.halt_update
        mp.halt_update = True

        try:
            # Create a FILL layer (COLOR type) - all images go through override system
            layer = add_new_layer(
                group_tree=group_tree,
                layer_name=layer_name,
                layer_type='COLOR',  # Fill layer, not paint layer
                channel_idx=0,  # Default to first channel
                blend_type='MIX',
                normal_blend_type='MIX',
                normal_map_type=normal_map_type,
                texcoord_type=self.texcoord_type,
                uv_name=self.uv_map,
                # No image parameter - all images via override
            )

            layer_tree = get_tree(layer)

            # Enable all matched channels and create cache nodes
            # For NORMAL channel: distinguish between bump and normal maps
            for ch_idx, image, synonym, is_bump in channel_matches:
                ch = layer.channels[ch_idx]
                ch.enable = True
                root_ch = mp.channels[ch_idx]

                # For NORMAL channel: use different cache based on bump vs normal
                if root_ch.type == 'NORMAL':
                    if not is_bump:  # This is a normal map (not bump/height)
                        # Use override_1 system for normal maps (Mixar Paint pattern)
                        image_node, _ = check_new_node(
                            layer_tree, ch, 'cache_1_image', 'ShaderNodeTexImage', '', True
                        )
                        if image_node:
                            image_node.image = image
                            image_node.interpolation = 'Cubic'
                    else:  # This is a bump/height map
                        # Use regular override system for bump maps
                        image_node, _ = check_new_node(
                            layer_tree, ch, 'cache_image', 'ShaderNodeTexImage', '', True
                        )
                        if image_node:
                            image_node.image = image
                else:
                    # Non-normal channels use regular override
                    image_node, _ = check_new_node(
                        layer_tree, ch, 'cache_image', 'ShaderNodeTexImage', '', True
                    )
                    if image_node:
                        image_node.image = image

            # Set as active layer
            mp.active_layer_index = len(mp.layers) - 1

        finally:
            mp.halt_update = ori_halt_update

        # Now with halt_update = False, set override_type to trigger callbacks
        # This will move cache nodes to source and set up node connections
        for ch_idx, image, synonym, is_bump in channel_matches:
            ch = layer.channels[ch_idx]
            root_ch = mp.channels[ch_idx]

            # For NORMAL channel: use override_1 for normal maps, override for bump
            if root_ch.type == 'NORMAL' and not is_bump:
                # Normal maps use override_1 system
                ch.override_1 = True
                ch.override_1_type = 'IMAGE'
                check_override_1_layer_channel_nodes(root_ch, layer, ch)
            else:
                # Bump maps and other channels use regular override
                ch.override = True
                ch.override_type = 'IMAGE'
                check_override_layer_channel_nodes(root_ch, layer, ch)

            # Handle glossiness/smoothness - add invert modifier
            if synonym in INVERT_SYNONYMS:
                from ...core.modifier.modifier import add_new_modifier
                add_new_modifier(ch, 'INVERT')

        # Reconnect and rearrange nodes
        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)
        reconnect_mp_nodes(group_tree)
        rearrange_mp_nodes(group_tree)

        # Clean up unused images
        for img in images:
            if img not in [m[1] for m in channel_matches] and img.users == 0:
                bpy.data.images.remove(img)

        # Request UI refresh
        request_ui_refresh()

        # Report success
        matched_channels = [mp.channels[m[0]].name for m in channel_matches]
        logger.info(f"Layer '{layer_name}' created with channels: {', '.join(matched_channels)} in {(time.time() - T) * 1000:.2f} ms!")
        self.report({'INFO'}, f"Created layer with {len(channel_matches)} channel(s): {', '.join(matched_channels)}")

        return {'FINISHED'}


# Classes for registration
classes = (
    LAYERS_OT_OpenImagesToLayer,
)
