# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fill layer (COLOR type) handler.

Implements channel setup and UI behavior for Fill layers.
Fill layers use:
- Solid color or image override for Color channel
- Slider override for Metallic/Roughness
- Image input for AO and Normal channels
"""

from typing import Set
from .base_handler import LayerTypeHandler
from ...utils.channel_detection import is_ao_channel, is_emission_channel
from ...utils.ui_constants import (
    UI_SCALE_Y,
    UI_HEADER_SCALE_Y,
    LABEL_SPLIT_FACTOR,
    NAME_SPLIT_FACTOR,
    SECTION_SEPARATOR_FACTOR,
    IMAGE_BTN_SCALE_X,
    Icons,
    OverrideDefaults,
)


class FillLayerHandler(LayerTypeHandler):
    """Handler for Fill layers (type='COLOR').

    Fill layer characteristics:
    - Color channel uses layer source (solid color)
    - Metallic/Roughness use OVERRIDE with sliders
    - AO uses IMAGE mode (baked AO texture)
    - Normal uses IMAGE mode (baked normal map)
    """

    LAYER_TYPE = 'COLOR'

    # ========== Channel Setup ==========

    # Channels always enabled for fill layers
    _CORE_CHANNELS = {"Color", "Metallic", "Roughness", "Normal"}

    def get_default_enabled_channels(self, mp) -> Set[str]:
        """Enable all existing channels for fill layers.

        Core four (Color, Metallic, Roughness, Normal) are always enabled.
        Any additional channels that exist in mp.channels are also enabled,
        giving fill layers full PBR control by default.
        """
        channels = set(self._CORE_CHANNELS)
        if mp:
            for ch in mp.channels:
                channels.add(ch.name)
        return channels

    def get_channel_override_default(self, root_ch) -> str:
        """Get default override type based on channel type.

        - RGB (Color): LAYER (uses solid color source)
        - RGB (AO): IMAGE (expects baked AO texture)
        - RGB (Emission): OVERRIDE (color picker)
        - NORMAL: OVERRIDE (custom color, user can toggle to IMAGE for baked normal map)
        - VALUE (Metallic/Roughness): OVERRIDE (slider control)
        """
        if root_ch.type == 'RGB':
            # AO channel uses IMAGE mode (for baked AO textures)
            if is_ao_channel(root_ch):
                return 'IMAGE'
            # Emission defaults to OVERRIDE (color picker)
            if is_emission_channel(root_ch):
                return 'OVERRIDE'
            return 'LAYER'
        elif root_ch.type == 'NORMAL':
            # Normal channel defaults to OVERRIDE (custom color picker)
            return 'OVERRIDE'
        elif root_ch.type == 'VALUE':
            # VALUE channels (Metallic, Roughness) use OVERRIDE
            return 'OVERRIDE'
        return 'LAYER'

    def setup_channel_defaults(self, ch, root_ch, solid_color=(1, 1, 1)):
        """Set up default values for fill layer channel."""
        ch.override_type = self.get_channel_override_default(root_ch)

        # Set sensible default override values for VALUE channels
        if root_ch.type == 'VALUE':
            name_lower = root_ch.name.lower()
            if 'metallic' in name_lower:
                ch.override_value = OverrideDefaults.METALLIC
            elif 'roughness' in name_lower:
                ch.override_value = OverrideDefaults.ROUGHNESS
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

        # Set default override color for RGB channels in OVERRIDE mode
        if root_ch.type == 'RGB' and ch.override_type == 'OVERRIDE':
            if is_emission_channel(root_ch):
                ch.override_color = OverrideDefaults.EMISSION_COLOR
            elif 'sheen' in root_ch.name.lower() and 'tint' in root_ch.name.lower():
                ch.override_color = OverrideDefaults.SHEEN_TINT_COLOR

        # Set up Normal channel defaults (custom color mode)
        if root_ch.type == 'NORMAL':
            # Enable override for bump source with default color
            if hasattr(ch, 'override'):
                ch.override = True
            # Set default bump color (middle gray for neutral bump)
            if hasattr(ch, 'override_color'):
                ch.override_color = (0.5, 0.5, 0.5)
            # Initialize dual-source for BUMP_NORMAL_MAP mode
            if hasattr(ch, 'override_1'):
                ch.override_1 = False
            if hasattr(ch, 'override_1_color'):
                ch.override_1_color = (0.5, 0.5, 1.0)  # Flat normal map color
            if hasattr(ch, 'override_1_type'):
                ch.override_1_type = 'DEFAULT'

    # ========== UI Drawing ==========

    def draw_channel_row(self, context, layout, channel, root_ch, layer, mp):
        """Draw fill layer channel row with appropriate controls."""
        from ..node.get_nodes import get_layer_source, get_tree

        # Determine current state
        override_type = getattr(channel, 'override_type', 'LAYER')
        is_custom = override_type == 'OVERRIDE'
        is_image = override_type == 'IMAGE'
        is_ao = is_ao_channel(root_ch)

        box = layout.box()
        box.scale_y = UI_SCALE_Y

        # Header row: expand toggle, enable toggle, channel name + controls
        header = box.row(align=True)
        header.scale_y = UI_HEADER_SCALE_Y

        # Expand toggle (triangle icon)
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

        # Get indices for operator properties
        layer_index = self._get_layer_index(layer)
        channel_index = self._get_channel_index(layer, channel)

        # Image button - hide for AO, Normal, and Emission
        if not is_ao and root_ch.type not in {'NORMAL'} and not is_emission_channel(root_ch):
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
            else:
                # Metallic/Roughness: show slider
                ctrl_row.prop(channel, "override_value", text="", slider=True)
        elif root_ch.type == 'NORMAL':
            # Normal channel: show inline controls based on type and override state
            self._draw_normal_inline(ctrl_row, channel, layer, channel_index)
        elif root_ch.type == 'RGB':
            if is_ao:
                # AO (RGB type): always show image selector inline for baked AO
                self._draw_image_inline(ctrl_row, channel, layer)
            elif is_image:
                # IMAGE mode: show image selector inline
                self._draw_image_inline(ctrl_row, channel, layer)
            elif is_emission_channel(root_ch):
                # Emission: show palette toggle + color picker when active
                self._draw_emission_controls(ctrl_row, channel, layer, channel_index)
            else:
                # Color channel: show color picker (like Metallic shows slider)
                source_node = get_layer_source(layer)
                if source_node and source_node.bl_idname == 'ShaderNodeRGB':
                    ctrl_row.prop(source_node.outputs[0], 'default_value', text="")
                else:
                    ctrl_row.prop(channel, "override_color", text="")

        if expand_blend:
            self._draw_blend_opacity(box, channel, root_ch, layer_index, channel_index, layer)
            # Normal channel extras
            if channel.enable and root_ch.type == 'NORMAL':
                self._draw_normal_extras(box, channel, layer, root_ch, context)
            # Image properties inside expanded section (skip for Normal - handled in normal panel)
            elif channel.enable and channel.override_type == 'IMAGE':
                self._draw_image_properties_if_exists(box, channel, layer)

        layout.separator(factor=SECTION_SEPARATOR_FACTOR)

    def draw_channel_extras(self, context, layout, channel, root_ch, layer):
        """Draw extra controls - now handled in expanded section."""
        # Image properties and normal extras are now drawn inside the expanded blend section
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

    def _draw_color_with_image_buttons(self, layout, channel, layer):
        """Draw fill layer color picker with small image buttons.

        Shows the layer's source RGB node color directly (no override needed),
        with small buttons to select/open an image if user wants to use a texture.
        If an image has been loaded (override_type == 'IMAGE'), shows the image selector instead.
        """
        from ..node.get_nodes import get_layer_source, get_tree

        tree = get_tree(layer)
        override_type = getattr(channel, 'override_type', 'LAYER')

        # Check if image mode is active (user loaded an image)
        if override_type == 'IMAGE' and channel.source:
            ch_source = tree.nodes.get(channel.source) if tree else None
            if ch_source and ch_source.bl_idname == 'ShaderNodeTexImage':
                # Show image selector with template_ID
                layout.template_ID(ch_source, "image", open="image.open")
                return

        # Small image buttons (placed first for consistency with other channels)
        btn_row = layout.row(align=True)
        btn_row.scale_x = IMAGE_BTN_SCALE_X
        btn_row.context_pointer_set('layer', layer)
        btn_row.context_pointer_set('channel', channel)
        # Button to select existing image
        btn_row.operator(
            'wm.m_select_existing_image_for_channel',
            text="",
            icon="DOWNARROW_HLT"
        )
        # Button to open new image
        btn_row.operator(
            'wm.m_open_image_to_override_layer_channel',
            text="",
            icon=Icons.FILE_BROWSER
        )

        # Show layer's fill color
        source_node = get_layer_source(layer)
        if source_node and source_node.bl_idname == 'ShaderNodeRGB':
            layout.prop(source_node.outputs[0], 'default_value', text="")
        else:
            # Fallback to channel override color if source not available
            layout.prop(channel, "override_color", text="")

    def _draw_emission_controls(self, layout, channel, layer, channel_index):
        """Draw emission channel controls with color picker.

        Shows color picker directly (override is ON by default).
        Also shows image buttons for loading emissive textures.
        """
        from ..node.get_nodes import get_tree

        override_type = getattr(channel, 'override_type', 'LAYER')
        is_image = override_type == 'IMAGE'
        tree = get_tree(layer)

        # Check if image mode is active
        if is_image and channel.source:
            ch_source = tree.nodes.get(channel.source) if tree else None
            if ch_source and ch_source.bl_idname == 'ShaderNodeTexImage':
                layout.template_ID(ch_source, "image", open="image.open")
                return

        # Always show color picker (override is default for Emission)
        layout.prop(channel, "override_color", text="")

        # Image buttons for loading emissive textures
        btn_row = layout.row(align=True)
        btn_row.scale_x = IMAGE_BTN_SCALE_X
        btn_row.context_pointer_set('layer', layer)
        btn_row.context_pointer_set('channel', channel)
        btn_row.operator(
            'wm.m_select_existing_image_for_channel',
            text="",
            icon="DOWNARROW_HLT"
        )
        btn_row.operator(
            'wm.m_open_image_to_override_layer_channel',
            text="",
            icon=Icons.FILE_BROWSER
        )

    def _draw_image_selector(self, layout, channel, root_ch, layer):
        """Draw image selector row for IMAGE override mode."""
        from ..node.get_nodes import get_tree

        tree = get_tree(layer)
        source = None
        if channel.source:
            source = tree.nodes.get(channel.source) if tree else None

        img_row = layout.row(align=True)
        img_row.scale_y = UI_SCALE_Y

        if source and source.bl_idname == 'ShaderNodeTexImage':
            split = img_row.split(factor=LABEL_SPLIT_FACTOR, align=True)
            split.label(text="Image")
            split.template_ID(source, "image", open="image.open")

            # Draw image properties when an image is attached
            if source.image:
                self._draw_image_properties_boxed(layout, source)
        else:
            split = img_row.split(factor=LABEL_SPLIT_FACTOR, align=True)
            split.label(text="Image")
            op_row = split.row(align=True)
            op_row.context_pointer_set('layer', layer)
            op_row.context_pointer_set('channel', channel)
            op_row.operator(
                'wm.m_select_existing_image_for_channel',
                text="",
                icon="DOWNARROW_HLT"
            )
            op_row.operator(
                'wm.m_open_image_to_override_layer_channel',
                text="Open Image",
                icon=Icons.FILE_BROWSER
            )

    def _draw_image_properties_if_exists(self, layout, channel, layer):
        """Draw image properties section if an image is loaded for the channel.

        Args:
            layout: UI layout to draw into
            channel: YLayerChannel
            layer: Backend YLayer
        """
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

        self._draw_image_properties_content(content, source)

    def _draw_image_properties_boxed(self, layout, source):
        """Draw image properties in a boxed section.

        Args:
            layout: UI layout to draw into
            source: ShaderNodeTexImage node with the image
        """
        if not source or source.bl_idname != 'ShaderNodeTexImage' or not source.image:
            return

        # Section box with header
        props_box = layout.box()
        header = props_box.row(align=True)
        header.scale_y = 1.1
        header.label(text="Image Properties", icon='IMAGE_DATA')

        content = props_box.column(align=True)
        content.scale_y = 1.1

        self._draw_image_properties_content(content, source)

    def _draw_image_properties_content(self, layout, source):
        """Draw image properties content (Projection, Source, Color Space, Alpha Mode, Interpolation, Extension).

        Args:
            layout: UI layout to draw into
            source: ShaderNodeTexImage node with the image
        """
        if not source or source.bl_idname != 'ShaderNodeTexImage' or not source.image:
            return

        image = source.image

        # Projection (on the node)
        proj_row = layout.row(align=True)
        split = proj_row.split(factor=0.35, align=True)
        split.label(text="Projection")
        proj_right = split.row(align=True)
        proj_right.prop(source, "projection", text="")
        # Show projection blend slider when projection is BOX
        if source.projection == 'BOX':
            proj_right.prop(source, "projection_blend", text="Blend", slider=True)

        # Color Space
        cs_row = layout.row(align=True)
        split = cs_row.split(factor=0.35, align=True)
        split.label(text="Color Space")
        split.prop(image.colorspace_settings, "name", text="")

        # Alpha Mode
        alpha_row = layout.row(align=True)
        split = alpha_row.split(factor=0.35, align=True)
        split.label(text="Alpha Mode")
        split.prop(image, "alpha_mode", text="")

        # Interpolation (on the node, not the image)
        interp_row = layout.row(align=True)
        split = interp_row.split(factor=0.35, align=True)
        split.label(text="Interpolation")
        split.prop(source, "interpolation", text="")

        # Extension (on the node, not the image)
        ext_row = layout.row(align=True)
        split = ext_row.split(factor=0.35, align=True)
        split.label(text="Extension")
        split.prop(source, "extension", text="")

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
