# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Paint layer (IMAGE type) handler.

Implements channel setup and UI behavior for Paint layers.
Paint layers use brush-based painting with:
- Brush color for Color channel
- Brush luminance for VALUE channels
- Custom override toggle for per-channel overrides
- Image override toggle for per-channel image textures
"""

from typing import Set
from .base_handler import LayerTypeHandler
from ...utils.ui_constants import (
    UI_SCALE_Y,
    UI_HEADER_SCALE_Y,
    LABEL_SPLIT_FACTOR,
    NAME_SPLIT_FACTOR,
    Icons,
    OverrideDefaults,
    BUMP_NORMAL_TYPES,
)


class PaintLayerHandler(LayerTypeHandler):
    """Handler for Paint layers (type='IMAGE').

    Paint layer characteristics:
    - Color channel uses LAYER mode by default (uses brush color)
    - Non-color channels use OVERRIDE mode by default (custom values)
    - Custom toggle to switch between brush-based and per-channel override values
    - Image toggle to use image textures instead of brush/override values
    """

    LAYER_TYPE = 'IMAGE'

    # ========== Channel Setup ==========

    # Channels always enabled for paint layers
    _CORE_CHANNELS = {"Color", "Metallic", "Roughness", "Normal"}

    def get_default_enabled_channels(self, mp) -> Set[str]:
        """Enable all existing channels for paint layers.

        Core four (Color, Metallic, Roughness, Normal) are always enabled.
        Any additional channels that exist in mp.channels are also enabled,
        giving paint layers full PBR control by default.
        """
        channels = set(self._CORE_CHANNELS)
        if mp:
            for ch in mp.channels:
                channels.add(ch.name)
        return channels

    def get_channel_override_default(self, root_ch) -> str:
        """Color channel uses LAYER (brush), others use OVERRIDE (custom value)."""
        # Color channel uses brush mode
        if root_ch.type == 'RGB' and root_ch.name.lower() == 'color':
            return 'LAYER'
        # All other channels use custom override by default
        return 'OVERRIDE'

    def setup_channel_defaults(self, ch, root_ch, solid_color=(1, 1, 1)):
        """Set up default values for paint layer channel."""
        ch.override_type = self.get_channel_override_default(root_ch)

        # Set sensible default override values when override is enabled
        if ch.override_type == 'OVERRIDE':
            if root_ch.type == 'VALUE':
                # Use channel-specific defaults
                name_lower = root_ch.name.lower()
                if 'metallic' in name_lower:
                    ch.override_value = OverrideDefaults.METALLIC
                elif 'roughness' in name_lower:
                    ch.override_value = OverrideDefaults.ROUGHNESS
                elif 'ao' in name_lower or 'occlusion' in name_lower:
                    ch.override_value = OverrideDefaults.AO
                elif 'clearcoat' in name_lower or 'coat' in name_lower:
                    if 'roughness' in name_lower:
                        ch.override_value = OverrideDefaults.CLEARCOAT_ROUGHNESS
                    elif 'ior' in name_lower:
                        ch.override_value = OverrideDefaults.COAT_IOR
                    else:
                        ch.override_value = OverrideDefaults.CLEARCOAT
                elif 'subsurface' in name_lower or 'sss' in name_lower:
                    if 'scale' in name_lower:
                        ch.override_value = OverrideDefaults.SUBSURFACE_SCALE
                    elif 'anisotropy' in name_lower:
                        ch.override_value = OverrideDefaults.SUBSURFACE_ANISOTROPY
                    else:
                        ch.override_value = OverrideDefaults.SUBSURFACE
                elif 'sheen' in name_lower:
                    if 'roughness' in name_lower:
                        ch.override_value = OverrideDefaults.SHEEN_ROUGHNESS
                    else:
                        ch.override_value = OverrideDefaults.SHEEN
                elif 'specular' in name_lower or 'spec' in name_lower:
                    if 'tint' in name_lower:
                        ch.override_value = OverrideDefaults.SPECULAR_TINT
                    else:
                        ch.override_value = OverrideDefaults.SPECULAR
                elif 'transmission' in name_lower:
                    ch.override_value = OverrideDefaults.TRANSMISSION
                elif 'ior' in name_lower:
                    ch.override_value = OverrideDefaults.IOR
                elif 'anisotropic' in name_lower or 'aniso' in name_lower:
                    if 'rotation' in name_lower:
                        ch.override_value = OverrideDefaults.ANISOTROPIC_ROTATION
                    else:
                        ch.override_value = OverrideDefaults.ANISOTROPIC
                else:
                    ch.override_value = OverrideDefaults.GENERIC_VALUE
            elif root_ch.type == 'RGB':
                # Emission defaults to black (no emission)
                if 'emission' in root_ch.name.lower() or 'emissive' in root_ch.name.lower():
                    ch.override_color = OverrideDefaults.EMISSION_COLOR
                elif 'sheen' in root_ch.name.lower() and 'tint' in root_ch.name.lower():
                    ch.override_color = OverrideDefaults.SHEEN_TINT_COLOR
            elif root_ch.type == 'NORMAL':
                # Initialize Normal channel dual-source for BUMP_NORMAL_MAP mode
                if hasattr(ch, 'override'):
                    ch.override = True
                if hasattr(ch, 'override_color'):
                    ch.override_color = (0.5, 0.5, 0.5)  # Mid-gray for neutral bump
                if hasattr(ch, 'override_1'):
                    ch.override_1 = False
                if hasattr(ch, 'override_1_color'):
                    ch.override_1_color = (0.5, 0.5, 1.0)  # Flat normal map color
                if hasattr(ch, 'override_1_type'):
                    ch.override_1_type = 'DEFAULT'

    # ========== UI Drawing ==========

    def draw_channel_row(self, context, layout, channel, root_ch, layer, mp):
        """Draw paint layer channel row with brush-based controls."""
        # Determine current state
        override_type = getattr(channel, 'override_type', 'LAYER')
        is_custom = override_type == 'OVERRIDE'
        is_image = override_type == 'IMAGE'
        is_ao = root_ch.name.upper() in ['AO', 'AMBIENT OCCLUSION']

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

        # Channel name (15% width)
        split = header.split(factor=NAME_SPLIT_FACTOR, align=True)
        name_col = split.row(align=True)
        name_col.enabled = channel.enable
        name_col.label(text=root_ch.name)

        # Controls area
        ctrl_row = split.row(align=True)
        ctrl_row.enabled = channel.enable

        channel_index = self._get_channel_index(layer, channel)

        # Custom toggle button (pencil icon)
        custom_btn = ctrl_row.row(align=True)
        custom_btn.scale_x = 1.0
        if is_custom:
            custom_btn.alert = True
        custom_btn.operator(
            "channel.toggle_custom_override",
            text="",
            icon=Icons.CUSTOM_OVERRIDE,
            depress=is_custom
        ).channel_index = channel_index

        # Image override button - hide for AO and Normal
        if not is_ao and root_ch.type != 'NORMAL':
            image_btn = ctrl_row.row(align=True)
            image_btn.scale_x = 1.0
            if is_image:
                image_btn.alert = True
            op = image_btn.operator(
                "channel.toggle_image_override",
                text="",
                icon=Icons.IMAGE,
                depress=is_image
            )
            op.channel_index = channel_index

        # Channel-specific controls
        if root_ch.type == 'VALUE':
            if is_image:
                # IMAGE mode: show image selector inline
                self._draw_image_inline(ctrl_row, channel, layer)
            elif is_custom:
                # Custom override active: show override slider
                ctrl_row.prop(channel, "override_value", text="", slider=True)
            else:
                # Default: show disabled luminance from brush color
                self._draw_brush_luminance(context, ctrl_row)
        elif root_ch.type == 'NORMAL':
            # Normal channel: show inline controls based on type and override state
            self._draw_normal_inline(ctrl_row, channel, layer, channel_index)
        elif root_ch.type == 'RGB':
            if is_ao:
                # AO (RGB type): show override color for baked AO
                ctrl_row.prop(channel, "override_color", text="")
            elif is_image:
                # IMAGE mode: show image selector inline
                self._draw_image_inline(ctrl_row, channel, layer)
            elif is_custom:
                # Custom override: show channel's override_color
                ctrl_row.prop(channel, "override_color", text="")
            else:
                # Default (LAYER mode): show enabled brush color picker
                # User can modify brush color which is used for painting
                self._draw_brush_color(context, ctrl_row, enabled=True)
        elif is_custom:
            # Custom override for other types
            ctrl_row.prop(channel, "override_color", text="")

        # Expanded section
        layer_index = self._get_layer_index(layer)
        if expand_blend:
            self._draw_blend_opacity(box, channel, root_ch, layer_index, channel_index, layer)
            if channel.enable and root_ch.type == 'NORMAL':
                self._draw_normal_extras(box, channel, layer, root_ch, context)
            # Image properties inside expanded section (skip for Normal - handled in normal panel)
            elif channel.enable and channel.override_type == 'IMAGE':
                self._draw_image_properties_if_exists(box, channel, layer)

    def draw_channel_extras(self, context, layout, channel, root_ch, layer):
        """Draw extra controls - now handled in expanded section."""
        # Image properties are now drawn inside the expanded blend section
        pass

    # ========== Private Helper Methods ==========

    def _draw_image_inline(self, layout, channel, layer):
        """Draw inline image selector for channels in IMAGE mode."""
        from ..node.get_nodes import get_tree

        tree = get_tree(layer)
        source = None
        if channel.source:
            source = tree.nodes.get(channel.source) if tree else None

        row = layout.row(align=True)
        row.context_pointer_set('layer', layer)
        row.context_pointer_set('channel', channel)

        if source and source.bl_idname == 'ShaderNodeTexImage' and source.image:
            # Show image name as label + clear button
            row.label(text=source.image.name)
            row.operator(
                'wm.m_clear_channel_image',
                text="",
                icon=Icons.REMOVE
            )
        else:
            # No image loaded - show open button + browse existing dropdown
            row.operator(
                'wm.m_open_image_to_override_layer_channel',
                text="Open Image",
                icon=Icons.FILE_BROWSER
            )
            row.operator(
                'wm.m_select_existing_image_for_channel',
                text="",
                icon="DOWNARROW_HLT"
            )

    def _draw_image_properties_if_exists(self, layout, channel, layer):
        """Draw image properties section when image exists."""
        from ..node.get_nodes import get_tree

        tree = get_tree(layer)
        source = None
        if channel.source:
            source = tree.nodes.get(channel.source) if tree else None

        if not source or source.bl_idname != 'ShaderNodeTexImage' or not source.image:
            return

        # Section box with header
        props_box = layout.box()
        header = props_box.row(align=True)
        header.scale_y = 1.1
        header.label(text="Image Properties", icon='IMAGE_DATA')

        content = props_box.column(align=True)
        content.scale_y = 1.1

        image = source.image

        # Projection (on the node)
        proj_row = content.row(align=True)
        split = proj_row.split(factor=0.35, align=True)
        split.label(text="Projection")
        proj_right = split.row(align=True)
        proj_right.prop(source, "projection", text="")
        # Show projection blend slider when projection is BOX
        if source.projection == 'BOX':
            proj_right.prop(source, "projection_blend", text="Blend", slider=True)

        # Color Space
        cs_row = content.row(align=True)
        split = cs_row.split(factor=0.35, align=True)
        split.label(text="Color Space")
        split.prop(image.colorspace_settings, "name", text="")

        # Alpha Mode
        alpha_row = content.row(align=True)
        split = alpha_row.split(factor=0.35, align=True)
        split.label(text="Alpha Mode")
        split.prop(image, "alpha_mode", text="")

        # Interpolation (on the node)
        interp_row = content.row(align=True)
        split = interp_row.split(factor=0.35, align=True)
        split.label(text="Interpolation")
        split.prop(source, "interpolation", text="")

        # Extension (on the node)
        ext_row = content.row(align=True)
        split = ext_row.split(factor=0.35, align=True)
        split.label(text="Extension")
        split.prop(source, "extension", text="")

    def _draw_brush_luminance(self, context, layout):
        """Draw disabled brush luminance slider."""
        wm = context.window_manager
        if hasattr(wm, 'mixar_ui'):
            lum_row = layout.row(align=True)
            lum_row.enabled = False
            lum_row.prop(wm.mixar_ui, "brush_luminance", text="", slider=True)

    def _draw_brush_color(self, context, layout, enabled=True):
        """Draw brush color picker.

        Args:
            context: Blender context
            layout: UI layout
            enabled: Whether the color picker should be enabled (default True)
        """
        if not context or not context.tool_settings:
            return

        brush = context.tool_settings.image_paint.brush
        if brush:
            color_row = layout.row(align=True)
            color_row.enabled = enabled
            ups = context.tool_settings.image_paint.unified_paint_settings
            if ups.use_unified_color:
                color_row.prop(ups, "color", text="")
            else:
                color_row.prop(brush, "color", text="")

    def _draw_normal_inline(self, layout, channel, layer, channel_index):
        """Draw Normal channel inline controls in header.

        Shows image override toggle and image upload buttons or color picker based on:
        - normal_map_type: BUMP_MAP, NORMAL_MAP, or BUMP_NORMAL_MAP
        - override/override_1: whether image override is enabled
        - override_type/override_1_type: IMAGE or DEFAULT

        Args:
            layout: UI layout to draw into
            channel: YLayerChannel (Normal channel)
            layer: YLayer
            channel_index: Index of the channel for operator properties
        """
        from ..node.get_nodes import get_tree

        normal_map_type = getattr(channel, 'normal_map_type', 'BUMP_MAP')
        tree = get_tree(layer)

        # Determine what to show based on normal_map_type
        show_bump = normal_map_type in {'BUMP_MAP', 'BUMP_NORMAL_MAP'}
        show_normal = normal_map_type in {'NORMAL_MAP', 'BUMP_NORMAL_MAP'}

        # Get override states
        bump_override = getattr(channel, 'override', False)
        bump_override_type = getattr(channel, 'override_type', 'DEFAULT')
        normal_override = getattr(channel, 'override_1', False)
        normal_override_type = getattr(channel, 'override_1_type', 'DEFAULT')

        # --- BUMP SOURCE (for BUMP_MAP and BUMP_NORMAL_MAP) ---
        if show_bump:
            # Image toggle button for bump
            bump_btn = layout.row(align=True)
            bump_btn.scale_x = 1.0
            is_bump_image = bump_override and bump_override_type == 'IMAGE'
            if is_bump_image:
                bump_btn.alert = True
            op = bump_btn.operator(
                "channel.toggle_image_override",
                text="",
                icon=Icons.IMAGE,
                depress=is_bump_image
            )
            op.channel_index = channel_index

            if is_bump_image:
                # Show bump image inline
                self._draw_bump_image_inline(layout, channel, layer, tree)
            else:
                # Show color picker for bump (default mode)
                layout.prop(channel, "override_color", text="")

        # --- NORMAL SOURCE (for NORMAL_MAP and BUMP_NORMAL_MAP) ---
        if show_normal:
            # Image toggle button for normal map
            normal_btn = layout.row(align=True)
            normal_btn.scale_x = 1.0
            is_normal_image = normal_override and normal_override_type == 'IMAGE'
            if is_normal_image:
                normal_btn.alert = True
            op = normal_btn.operator(
                "channel.toggle_normal_image_override",
                text="",
                icon='NORMALS_FACE',
                depress=is_normal_image
            )
            op.channel_index = channel_index

            if is_normal_image:
                # Show normal map image inline
                self._draw_normal_image_inline(layout, channel, layer, tree)
            else:
                # Show color picker for normal (default mode)
                layout.prop(channel, "override_1_color", text="")

    def _draw_bump_image_inline(self, layout, channel, layer, tree):
        """Draw inline bump image selector."""
        source = None
        if channel.source:
            source = tree.nodes.get(channel.source) if tree else None

        row = layout.row(align=True)
        row.context_pointer_set('layer', layer)
        row.context_pointer_set('channel', channel)

        if source and source.bl_idname == 'ShaderNodeTexImage' and source.image:
            # Show image name + open/clear buttons
            row.label(text=source.image.name)
            row.operator(
                'wm.m_open_image_to_override_layer_channel',
                text="",
                icon=Icons.FILE_BROWSER
            )
            row.operator(
                'wm.m_clear_channel_image',
                text="",
                icon=Icons.REMOVE
            )
        else:
            # No image - show open button + browse existing dropdown
            row.operator(
                'wm.m_open_image_to_override_layer_channel',
                text="Open",
                icon=Icons.FILE_BROWSER
            )
            row.operator(
                'wm.m_select_existing_image_for_channel',
                text="",
                icon="DOWNARROW_HLT"
            )

    def _draw_normal_image_inline(self, layout, channel, layer, tree):
        """Draw inline normal map image selector."""
        source = None
        if channel.source_1:
            source = tree.nodes.get(channel.source_1) if tree else None

        row = layout.row(align=True)
        row.context_pointer_set('layer', layer)
        row.context_pointer_set('channel', channel)

        if source and source.bl_idname == 'ShaderNodeTexImage' and source.image:
            # Show image name + open/clear buttons
            row.label(text=source.image.name)
            row.operator(
                'wm.m_open_image_to_override_1_layer_channel',
                text="",
                icon=Icons.FILE_BROWSER
            )
            row.operator(
                'wm.m_clear_normal_channel_image',
                text="",
                icon=Icons.REMOVE
            )
        else:
            # No image - show open + browse existing buttons
            row.operator(
                'wm.m_open_image_to_override_1_layer_channel',
                text="Open",
                icon=Icons.FILE_BROWSER
            )
            row.operator(
                'wm.m_select_existing_normal_image_for_channel',
                text="",
                icon="DOWNARROW_HLT"
            )

    def _draw_normal_extras(self, layout, channel, layer=None, root_ch=None, context=None):
        """Draw extra controls for Normal channel.

        Uses the comprehensive Normal panel from base class.
        Write Height is now included in the panel.
        """
        # Call base class implementation which uses the new comprehensive panel
        super()._draw_normal_extras(layout, channel, layer, root_ch, context)
