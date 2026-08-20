# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer override callback functions."""

import re

from ......config.logging_config import get_logger

logger = get_logger(__name__)

from ....core.io.input_outputs.input_outputs import check_layer_channel_linear_node
from ....core.io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ....core.io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ....core.layer.check_layers import get_channel_enabled
from ....core.node.check_nodes import check_all_layer_channel_io_and_nodes, check_uv_nodes
from ....core.node.create_nodes import replace_new_node
from ....core.node.get_nodes import get_channel_source_tree, get_layer_source
from ....core.node.node_utils import remove_node
from ....core.subtree.check_subtree import (
    disable_channel_source_tree,
    enable_channel_source_tree,
)
from ....core.subtree.get_subtree import get_tree
from ....utils.common import get_vcol_bl_idname
from ...modifier.modifier_operators_helper import disable_modifiers_tree, enable_modifiers_tree


def check_override_1_layer_channel_nodes(root_ch, layer, ch):
    """Check and update secondary override nodes for layer channel.

    Args:
        root_ch: Root channel definition.
        layer: YLayer object.
        ch: YLayerChannel object.
    """

    mp = layer.id_data.mp
    layer_tree = get_tree(layer)

    # Current source
    source = layer_tree.nodes.get(ch.source_1)

    prev_type = ""

    # Source 1 will only use default value or image for now
    if source:
        if source.bl_idname == "ShaderNodeRGB":
            prev_type = "DEFAULT"
        else:
            prev_type = "IMAGE"

        if prev_type != ch.override_1_type or not ch.override_1:

            # Save source to cache if it's not default
            if prev_type != "DEFAULT":

                ch.cache_1_image = source.name
                # Remove uv input link
                if any(source.inputs) and any(source.inputs[0].links):
                    layer_tree.links.remove(source.inputs[0].links[0])
                source.label = ""
                ch.source_1 = ""

    # Try to get channel source
    if ch.override_1 and ch.override_1_type != "DEFAULT":
        source_label = root_ch.name + " Override 1 : " + ch.override_1_type

        cache = layer_tree.nodes.get(ch.cache_1_image)
        if cache:
            # Delete non cached source
            if prev_type == "DEFAULT":
                remove_node(layer_tree, ch, "source_1")

            ch.source_1 = cache.name
            ch.cache_1_image = ""

            cache.label = source_label
        else:
            source = replace_new_node(
                layer_tree, ch, "source_1", "ShaderNodeTexImage", source_label
            )

    else:
        remove_node(layer_tree, ch, "source_1")

    # Update linear stuff
    check_layer_channel_linear_node(ch, layer, root_ch, reconnect=True)


def update_layer_channel_override_1(self, context):
    """Update callback for secondary layer channel override changes.

    Args:
        self: The property being updated (YLayerChannel).
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    m = re.match(r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", self.path_from_id())
    ch_index = int(m.group(2))
    layer = mp.layers[int(m.group(1))]
    root_ch = mp.channels[ch_index]
    ch = self

    # Preserve expand_blend_settings state before node operations
    # This prevents the UI from collapsing when override_type changes
    saved_expand_blend = getattr(ch, 'expand_blend_settings', False)

    # Auto-enable override_1 when type is set to IMAGE
    # This ensures source_1 node gets created
    if ch.override_1_type == "IMAGE" and not ch.override_1:
        ch.override_1 = True

    check_override_1_layer_channel_nodes(root_ch, layer, ch)

    # Disable active edit if override is off
    if not ch.override_1:
        ch.halt_update = True
        ch.active_edit_1 = False
        ch.halt_update = False

    check_all_layer_channel_io_and_nodes(layer)
    check_uv_nodes(mp)
    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)

    reconnect_mp_nodes(self.id_data)
    rearrange_mp_nodes(self.id_data)

    # Restore expand_blend_settings state after node operations
    if hasattr(ch, 'expand_blend_settings'):
        ch.expand_blend_settings = saved_expand_blend


def check_override_layer_channel_nodes(root_ch, layer, ch):
    """Check and update override nodes for layer channel.

    Args:
        root_ch: Root channel definition.
        layer: YLayer object.
        ch: YLayerChannel object.
    """

    mp = layer.id_data.mp
    layer_tree = get_tree(layer)

    channel_enabled = get_channel_enabled(ch, layer, root_ch)

    # Disable source tree first to avoid error
    if root_ch.type == "NORMAL" and root_ch.enable_smooth_bump and channel_enabled:
        disable_channel_source_tree(layer, root_ch, ch, rearrange=False, force=True)
        disable_modifiers_tree(ch)

    # Current source
    source = layer_tree.nodes.get(ch.source)

    prev_type = ""

    if source:
        if source.bl_idname in {"ShaderNodeRGB", "ShaderNodeValue"}:
            prev_type = "DEFAULT"
        elif source.bl_idname == get_vcol_bl_idname():
            prev_type = "VCOL"
        else:
            prev_type = source.bl_idname.replace("ShaderNodeTex", "").upper()

        if prev_type != ch.override_type:

            # Save source to cache if it's not default
            if prev_type != "DEFAULT":

                setattr(ch, "cache_" + prev_type.lower(), source.name)
                # Remove uv input link
                if any(source.inputs) and any(source.inputs[0].links):
                    layer_tree.links.remove(source.inputs[0].links[0])
                source.label = ""
                ch.source = ""

    # Try to get channel source for IMAGE type (new 4-option system)
    # or for legacy override types (VCOL, NOISE, etc.)
    if ch.override_type == "IMAGE" or (ch.override and ch.override_type not in ("DEFAULT", "LAYER", "PASSTHROUGH", "OVERRIDE")):
        source_label = root_ch.name + " Override : " + ch.override_type

        src_tree = get_channel_source_tree(ch, layer)

        cache = layer_tree.nodes.get(getattr(ch, "cache_" + ch.override_type.lower()))
        if cache:
            # Delete non cached source
            if prev_type == "DEFAULT":
                remove_node(layer_tree, ch, "source")

            ch.source = cache.name
            setattr(ch, "cache_" + ch.override_type.lower(), "")

            cache.label = source_label
        else:
            if ch.override_type == "VCOL":
                source = replace_new_node(
                    src_tree, ch, "source", get_vcol_bl_idname(), source_label
                )
            else:
                source = replace_new_node(
                    src_tree,
                    ch,
                    "source",
                    "ShaderNodeTex" + ch.override_type.capitalize(),
                    source_label,
                )

        # Channel IMAGE overrides use the layer's shared mapping node
        # No separate mapping node is created per channel

    elif ch.override_type not in ("IMAGE",):
        # Only remove source for non-IMAGE types
        remove_node(layer_tree, ch, "source")

    # Update linear stuff
    # Don't reconnect here - let update_layer_channel_override handle it after IO check
    check_layer_channel_linear_node(ch, layer, root_ch, reconnect=False)

    # Enable source tree back again
    if (
        root_ch.type == "NORMAL"
        and root_ch.enable_smooth_bump
        and channel_enabled
        and ch.override_type == "IMAGE"
    ):
        enable_channel_source_tree(layer, root_ch, ch)
        enable_modifiers_tree(ch)


def update_layer_channel_override(self, context):
    """Update callback for layer channel override property changes.

    Args:
        self: The property being updated (YLayerChannel).
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        logger.debug(f"update_layer_channel_override: BLOCKED by halt_update")
        return

    m = re.match(r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", self.path_from_id())
    ch_index = int(m.group(2))
    layer = mp.layers[int(m.group(1))]
    root_ch = mp.channels[ch_index]
    ch = self

    # Preserve expand_blend_settings state before node operations
    # This prevents the UI from collapsing when override_type changes
    saved_expand_blend = getattr(ch, 'expand_blend_settings', False)

    logger.debug(f"update_layer_channel_override: override={ch.override}, override_type={ch.override_type}, channel={root_ch.name}")

    # When enabling override, try to preserve the current layer color
    if ch.override and ch.override_type == 'DEFAULT' and root_ch.type != 'VALUE':
        tree = get_tree(layer)
        source = get_layer_source(layer, tree)
        if source and hasattr(source, 'outputs') and len(source.outputs) > 0:
            # For COLOR layers: read from default_value
            if hasattr(source.outputs[0], 'default_value'):
                current_color = source.outputs[0].default_value
                if len(current_color) >= 3:
                    ch.override_color = (current_color[0], current_color[1], current_color[2])
                    logger.debug(f"Preserved COLOR layer default_value: {ch.override_color}")
            # For IMAGE layers: read from generated_color if available
            elif layer.type == 'IMAGE' and hasattr(source, 'image') and source.image:
                img = source.image
                if hasattr(img, 'generated_color'):
                    gen_color = img.generated_color
                    if len(gen_color) >= 3:
                        ch.override_color = (gen_color[0], gen_color[1], gen_color[2])
                        logger.debug(f"Preserved IMAGE layer generated_color: {ch.override_color}")

    check_override_layer_channel_nodes(root_ch, layer, ch)

    # Disable active edit if override is off
    if not ch.override:
        ch.halt_update = True
        ch.active_edit = False
        ch.halt_update = False

    check_all_layer_channel_io_and_nodes(layer)
    check_uv_nodes(mp)

    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)

    reconnect_mp_nodes(self.id_data)
    rearrange_mp_nodes(self.id_data)

    mpui = context.window_manager.mpui
    # Update UI expansion state (with error handling for backward compatibility)
    try:
        if hasattr(mpui.layer_ui, 'channels') and len(mpui.layer_ui.channels) > ch_index:
            mpui.layer_ui.channels[ch_index].expand_source = ch.override_type not in {'DEFAULT', 'IMAGE', 'VCOL'}
    except (IndexError, AttributeError) as e:
        logger.warning(f"Could not update channel UI expansion state: {e}")

    # Reselect layer so vcol or image will be updated
    mp.active_layer_index = mp.active_layer_index

    # Restore expand_blend_settings state after node operations
    if hasattr(ch, 'expand_blend_settings'):
        ch.expand_blend_settings = saved_expand_blend
