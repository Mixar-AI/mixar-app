# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Base layer type handler abstract class.

Defines the interface for layer-type-specific behavior handlers.
"""

from abc import ABC, abstractmethod
from typing import Set, Optional


class LayerTypeHandler(ABC):
    """Abstract base class for layer type handlers.

    Each layer type (Fill, Paint, Procedural) has its own handler class
    that implements type-specific behavior for:
    - Channel setup and defaults
    - UI drawing
    - Node connection logic
    """

    # ========== Channel Setup Methods ==========

    @abstractmethod
    def get_default_enabled_channels(self, mp) -> Set[str]:
        """Get set of channel names to enable by default.

        Args:
            mp: MPaint root property group.

        Returns:
            Set of channel names to enable (e.g., {"Color", "Metallic"}).
        """
        pass

    @abstractmethod
    def get_channel_override_default(self, root_ch) -> str:
        """Get default override_type for a channel.

        Args:
            root_ch: Root channel (MPaintChannel) with name and type info.

        Returns:
            Override type string: 'LAYER', 'OVERRIDE', 'IMAGE', or 'PASSTHROUGH'.
        """
        pass

    @abstractmethod
    def setup_channel_defaults(self, ch, root_ch, solid_color=(1, 1, 1)):
        """Set up default values for a channel.

        Args:
            ch: Layer channel (YLayerChannel).
            root_ch: Root channel (MPaintChannel).
            solid_color: Default solid color tuple (R, G, B).
        """
        pass

    # ========== UI Drawing Methods ==========

    @abstractmethod
    def draw_channel_row(self, context, layout, channel, root_ch, layer, mp):
        """Draw the collapsed channel row in the UI.

        Args:
            context: Blender context.
            layout: UI layout.
            channel: YLayerChannel.
            root_ch: MPaintChannel (root channel).
            layer: YLayer (parent layer).
            mp: MPaint root property group.
        """
        pass

    @abstractmethod
    def draw_channel_extras(self, context, layout, channel, root_ch, layer):
        """Draw extra controls in expanded channel section.

        Args:
            context: Blender context.
            layout: Box layout to draw into.
            channel: YLayerChannel.
            root_ch: MPaintChannel (root channel).
            layer: YLayer (parent layer).
        """
        pass

    # ========== Common Index Helpers ==========

    def _get_layer_index(self, layer) -> int:
        """Get the index of a layer within mp.layers.

        Args:
            layer: YLayer to find index for.

        Returns:
            Index of layer in mp.layers, or -1 if not found.
        """
        mp = layer.id_data.mp
        for i, l in enumerate(mp.layers):
            if l == layer:
                return i
        return -1

    def _get_channel_index(self, layer, channel) -> int:
        """Get the index of a channel within its layer.

        Args:
            layer: YLayer containing the channel.
            channel: YLayerChannel to find index for.

        Returns:
            Index of channel in layer.channels, or -1 if not found.
        """
        for i, ch in enumerate(layer.channels):
            if ch == channel:
                return i
        return -1

    # ========== Common UI Drawing Helpers ==========

    def _draw_blend_opacity(self, layout, channel, root_ch, layer_index=-1, channel_index=-1, layer=None):
        """Draw blend mode and opacity controls with modifier button and modifiers section.

        Draws blend mode dropdown, opacity slider, modifier button on a single row,
        and a collapsible modifiers section below.
        Used by all layer handlers in the expanded section.

        Args:
            layout: UI layout to draw into.
            channel: YLayerChannel.
            root_ch: MPaintChannel (root channel).
            layer_index: Index of the layer (for modifier popup).
            channel_index: Index of the channel (for modifier popup).
            layer: YLayer instance (for context pointers).
        """
        from ...utils.ui_constants import Icons, UI_SCALE_Y, SEPARATOR_FACTOR

        blend_col = layout.column(align=True)
        blend_col.scale_y = UI_SCALE_Y
        blend_col.separator(factor=SEPARATOR_FACTOR)

        # Single row with Blend (left), Opacity (middle), and Modifier button (right)
        row = blend_col.row(align=True)

        # Left half: Blend
        left_split = row.split(factor=0.35, align=True)
        blend_sub = left_split.row(align=True)
        blend_sub.label(text="Blend")
        if root_ch.type == "NORMAL":
            blend_sub.prop(channel, "normal_blend_type", text="")
        else:
            blend_sub.prop(channel, "blend_type", text="")

        # Right half: Opacity
        opacity_sub = left_split.row(align=True)
        opacity_sub.label(text="Opacity")
        opacity_sub.prop(channel, "intensity_value", text="", slider=True)

        # Modifier toggle button on the extreme right
        if layer_index >= 0 and channel_index >= 0:
            mod_count = len(channel.modifiers)
            mod_btn = opacity_sub.row(align=True)
            mod_btn.scale_x = 1.0
            # Red when expanded or has modifiers
            if channel.expand_modifiers or mod_count > 0:
                mod_btn.alert = True
            mod_btn.prop(
                channel, "expand_modifiers",
                text=str(mod_count) if mod_count > 0 else "",
                icon=Icons.MODIFIER,
                toggle=True
            )

            # Draw modifiers dropdown section below blend row (only when expanded)
            if channel.expand_modifiers:
                self._draw_channel_modifiers_section(layout, channel, layer, root_ch)

    def _draw_channel_modifiers_section(self, layout, channel, layer, root_ch):
        """Draw modifiers section for channel (shown when expand_modifiers is True).

        Args:
            layout: UI layout to draw into.
            channel: YLayerChannel with modifiers.
            layer: YLayer instance.
            root_ch: MPaintChannel (root channel).
        """
        from ...core.modifier.modifier import can_be_expanded, draw_modifier_properties
        from ...core.subtree.get_subtree import get_mod_tree
        from ...utils.ui_constants import Icons

        section_box = layout.box()

        # Header with title and add button
        header = section_box.row(align=True)
        header.scale_y = 1.2
        header.label(text="Modifiers", icon=Icons.MODIFIER)

        # Spacer to push add button to right
        header.separator()

        # Context pointers for add menu
        header.context_pointer_set('parent', channel)
        header.context_pointer_set('layer', layer)
        header.menu("CHANNEL_MODIFIERS_MT_add_menu", text="", icon='ADD')

        # Content
        content = section_box.column(align=True)
        content.separator(factor=0.3)

        if len(channel.modifiers) == 0:
            info_row = content.row(align=True)
            info_row.scale_y = 1.0
            info_row.label(text="No modifiers", icon='INFO')
        else:
            mod_tree = get_mod_tree(channel)
            nodes = mod_tree.nodes if mod_tree else []
            channel_type = root_ch.type

            for modifier in channel.modifiers:
                self._draw_single_channel_modifier(content, modifier, channel, layer, nodes, channel_type)

    def _draw_single_channel_modifier(self, layout, modifier, channel, layer, nodes, channel_type):
        """Draw a single channel modifier in a sub-box.

        Args:
            layout: UI layout to draw into.
            modifier: The modifier to draw.
            channel: YLayerChannel containing the modifier.
            layer: YLayer instance.
            nodes: Node tree nodes for modifier properties.
            channel_type: Type of channel (RGB, VALUE, NORMAL).
        """
        from ...core.modifier.modifier import can_be_expanded, draw_modifier_properties

        mod_box = layout.box()
        mod_col = mod_box.column(align=True)

        # Modifier header row
        mod_row = mod_col.row(align=True)
        mod_row.scale_y = 1.1

        # Enable toggle
        mod_row.prop(modifier, "enable", text="")

        # Expand/collapse button and name
        can_expand = modifier.type in can_be_expanded
        if can_expand:
            icon = 'TRIA_DOWN' if modifier.expand_content else 'TRIA_RIGHT'
            mod_row.prop(modifier, "expand_content", text=modifier.name, icon=icon, emboss=False)
        else:
            mod_row.label(text=modifier.name)

        # Spacer
        mod_row.separator()

        # Context pointers for operators
        mod_row.context_pointer_set('parent', channel)
        mod_row.context_pointer_set('layer', layer)
        mod_row.context_pointer_set('modifier', modifier)

        # Move up/down buttons
        up_op = mod_row.operator("wm.m_move_mpaint_modifier", text="", icon='TRIA_UP', emboss=False)
        up_op.direction = 'UP'
        down_op = mod_row.operator("wm.m_move_mpaint_modifier", text="", icon='TRIA_DOWN', emboss=False)
        down_op.direction = 'DOWN'

        # Remove button
        mod_row.operator("wm.m_remove_mpaint_modifier", text="", icon='X', emboss=False)

        # Expanded content
        if can_expand and modifier.expand_content:
            content_col = mod_col.column(align=True)
            content_col.active = modifier.enable
            content_col.separator(factor=0.3)
            draw_modifier_properties(None, channel_type, nodes, modifier, channel, content_col)

        layout.separator(factor=0.2)

    def _draw_normal_extras(self, layout, channel, layer=None, root_ch=None, context=None):
        """Draw extra controls for Normal channel.

        Shows comprehensive Normal channel panel with type selector,
        image uploads for bump/normal maps, and parameter sliders.

        Args:
            layout: UI layout to draw into.
            channel: YLayerChannel with normal settings.
            layer: YLayer (optional, for image selectors).
            root_ch: MPaintChannel (optional).
            context: Blender context (optional).
        """
        # Use new comprehensive Normal panel if layer is available
        if layer is not None:
            from ...ui.utils.ui_helpers_normal_channel import draw_normal_channel_panel
            draw_normal_channel_panel(context, layout, channel, root_ch, layer)
            return

        # Fallback to simple controls if no layer context
        from ...utils.ui_constants import (
            UI_SCALE_Y,
            LABEL_SPLIT_FACTOR,
            BUMP_NORMAL_TYPES,
            NORMAL_STRENGTH_TYPES,
        )

        # Normal type selector
        type_row = layout.row(align=True)
        type_row.scale_y = UI_SCALE_Y
        split = type_row.split(factor=LABEL_SPLIT_FACTOR, align=True)
        split.label(text="Type")
        split.prop(channel, "normal_map_type", text="")

        # Bump settings (only for bump types)
        if channel.normal_map_type in BUMP_NORMAL_TYPES:
            height_row = layout.row(align=True)
            height_row.scale_y = UI_SCALE_Y
            split = height_row.split(factor=LABEL_SPLIT_FACTOR, align=True)
            split.label(text="Height")
            split.prop(channel, 'bump_distance', text="", slider=True)

            # Midlevel
            mid_row = layout.row(align=True)
            mid_row.scale_y = UI_SCALE_Y
            split = mid_row.split(factor=LABEL_SPLIT_FACTOR, align=True)
            split.label(text="Midlevel")
            split.prop(channel, 'bump_midlevel', text="", slider=True)

        # Normal map strength
        if channel.normal_map_type in NORMAL_STRENGTH_TYPES:
            strength_row = layout.row(align=True)
            strength_row.scale_y = UI_SCALE_Y
            split = strength_row.split(factor=LABEL_SPLIT_FACTOR, align=True)
            split.label(text="Strength")
            split.prop(channel, 'normal_strength', text="", slider=True)

    # ========== Optional Methods with Default Implementations ==========

    def should_enable_channel(self, root_ch, channel_idx, target_channel_idx) -> bool:
        """Check if a channel should be enabled by default.

        Args:
            root_ch: Root channel.
            channel_idx: Current channel index.
            target_channel_idx: Target channel index (-1 for all).

        Returns:
            True if channel should be enabled.
        """
        default_channels = self.get_default_enabled_channels(None)
        return root_ch.name in default_channels

    def get_layer_type(self) -> str:
        """Get the layer type this handler manages.

        Returns:
            Layer type string (e.g., 'COLOR', 'IMAGE', 'PROCEDURAL').
        """
        return getattr(self, 'LAYER_TYPE', 'UNKNOWN')


class DefaultLayerHandler(LayerTypeHandler):
    """Default handler for unhandled layer types.

    Provides sensible defaults that work for most layer types.
    """

    LAYER_TYPE = 'DEFAULT'

    def get_default_enabled_channels(self, mp) -> Set[str]:
        return {"Color"}

    def get_channel_override_default(self, root_ch) -> str:
        return 'LAYER'

    def setup_channel_defaults(self, ch, root_ch, solid_color=(1, 1, 1)):
        ch.override_type = self.get_channel_override_default(root_ch)

    def draw_channel_row(self, context, layout, channel, root_ch, layer, mp):
        # Default: just show channel name
        row = layout.row(align=True)
        row.prop(channel, "enable", text="")
        row.label(text=root_ch.name)

    def draw_channel_extras(self, context, layout, channel, root_ch, layer):
        # Default: no extras
        pass
