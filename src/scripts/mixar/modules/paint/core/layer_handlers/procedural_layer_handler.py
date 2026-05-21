# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Procedural layer handler.

Implements channel setup and UI behavior for Procedural layers.
Procedural layers use node groups that provide all PBR outputs
from a single material source. All outputs flow through the full
channel pipeline with blend modes, opacity, and masks.
"""

from typing import Set
from .base_handler import LayerTypeHandler
from ...utils.ui_constants import UI_SCALE_Y, UI_HEADER_SCALE_Y, Icons
from ..layer.ensure_procedural_channels import PROCEDURAL_OUTPUT_TO_CHANNEL


class ProceduralLayerHandler(LayerTypeHandler):
    """Handler for Procedural layers (type='PROCEDURAL').

    Procedural layer characteristics:
    - All channels use LAYER mode (procedural source provides values)
    - Channels are enabled dynamically based on node group outputs
    - No per-channel overrides (material provides all outputs)
    - Simplified UI showing blend mode and opacity
    """

    LAYER_TYPE = 'PROCEDURAL'

    # Core channels always enabled for procedural layers
    _CORE_CHANNELS = {"Color", "Metallic", "Roughness", "Normal"}

    # ========== Channel Setup ==========

    def get_default_enabled_channels(self, mp) -> Set[str]:
        """Enable channels based on procedural node group outputs.

        Always enables Color, Metallic, Roughness, Normal.
        Also enables any other channel that has a matching output
        in the procedural node group.
        """
        channels = set(self._CORE_CHANNELS)

        node_group = self._get_active_node_group(mp)
        if node_group:
            output_names = self._get_node_group_output_names(node_group)
            existing_channels = {ch.name for ch in mp.channels}

            for output_name in output_names:
                # Map output name to channel name
                channel_info = PROCEDURAL_OUTPUT_TO_CHANNEL.get(output_name)
                if channel_info is None:
                    # None means handled elsewhere (Height, Alpha)
                    # Height is handled via Normal channel's BUMP_MAP mode
                    if output_name == "Height":
                        channels.add("Normal")
                    continue

                channel_name = channel_info[0]
                if channel_name in existing_channels:
                    channels.add(channel_name)

        return channels

    @staticmethod
    def _get_active_node_group(mp):
        """Get the node group from the active procedural layer's source.

        Args:
            mp: Mixar Paint properties.

        Returns:
            The node group (ShaderNodeTree) or None.
        """
        from ..node.get_nodes import get_layer_source
        from ..subtree.get_subtree import get_tree

        if mp.active_layer_index < 0 or mp.active_layer_index >= len(mp.layers):
            return None

        layer = mp.layers[mp.active_layer_index]
        if layer.type != 'PROCEDURAL':
            return None

        tree = get_tree(layer)
        source = get_layer_source(layer, tree)
        if source and hasattr(source, 'node_tree'):
            return source.node_tree
        return None

    @staticmethod
    def _get_node_group_output_names(node_group):
        """Get output socket names from a node group interface.

        Args:
            node_group: A ShaderNodeTree.

        Returns:
            Set of output socket names.
        """
        names = set()
        if hasattr(node_group, 'interface') and hasattr(node_group.interface, 'items_tree'):
            for item in node_group.interface.items_tree:
                if hasattr(item, 'in_out') and item.in_out == 'OUTPUT':
                    names.add(item.name)
        return names

    def get_channel_override_default(self, root_ch) -> str:
        """All channels use LAYER mode (procedural source)."""
        return 'LAYER'

    def setup_channel_defaults(self, ch, root_ch, solid_color=(1, 1, 1)):
        """Set up default values for procedural layer channel."""
        ch.override_type = self.get_channel_override_default(root_ch)

    # ========== UI Drawing ==========

    def draw_channel_row(self, context, layout, channel, root_ch, layer, mp):
        """Draw procedural layer channel row (simplified)."""
        box = layout.box()
        box.scale_y = UI_SCALE_Y

        # Header row
        header = box.row(align=True)
        header.scale_y = UI_HEADER_SCALE_Y

        # Expand toggle
        expand_blend = getattr(channel, 'expand_blend_settings', False)
        icon = Icons.EXPAND if expand_blend else Icons.COLLAPSE
        header.prop(channel, "expand_blend_settings", text="", icon=icon, emboss=False)

        # Enable toggle
        header.prop(channel, "enable", text="")

        # Channel name
        header.label(text=root_ch.name)

        # Expanded section: blend mode + opacity (uses base class method)
        if expand_blend:
            self._draw_blend_opacity(box, channel, root_ch)

    def draw_channel_extras(self, context, layout, channel, root_ch, layer):
        """No extras for procedural layers - all controlled by material."""
        pass
