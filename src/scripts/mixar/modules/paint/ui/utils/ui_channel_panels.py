# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Channel panel UI drawing functions.

Draws the paint layer channel interface with channel settings.
Uses layer type handlers for type-specific UI behavior.
"""

from ...core.layer_handlers import get_handler


def _update_brush_luminance(context):
    """Calculate and update brush luminance from current brush color.

    Uses standard luminance formula: L = 0.2126*R + 0.7152*G + 0.0722*B

    Args:
        context: Blender context
    """
    wm = context.window_manager
    if not hasattr(wm, 'mixar_ui'):
        return

    if not context.tool_settings or not context.tool_settings.image_paint:
        return

    settings = context.tool_settings.image_paint
    brush = settings.brush
    if not brush:
        return

    ups = settings.unified_paint_settings
    color = ups.color if ups.use_unified_color else brush.color

    # Standard luminance formula (ITU-R BT.709)
    luminance = 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]

    # Update the property (clamped to 0-1)
    wm.mixar_ui.brush_luminance = max(0.0, min(1.0, luminance))


def draw_channels_tab(context, layout, mixar_ui, mp, layer):
    """Draw the CHANNELS tab content using layer type handlers.

    Delegates to the appropriate handler based on layer type.

    Args:
        context: Blender context
        layout: UI layout
        mixar_ui: MixarUIState property group
        mp: MPaint root property group
        layer: Active backend layer (YLayer)
    """
    # Update brush luminance for paint layers
    _update_brush_luminance(context)

    # Channel header row
    ch_header = layout.row(align=True)
    ch_header.scale_y = 1.2
    ch_header.label(text="Channels", icon='NODE_TEXTURE')
    ch_header.menu("CHANNELS_MT_add_channel_menu", text="", icon='ADD')

    layout.separator(factor=0.3)

    # Get handler for this layer type
    handler = get_handler(layer.type)

    # Draw channels using handler
    for i, channel in enumerate(layer.channels):
        if i >= len(mp.channels):
            continue
        root_ch = mp.channels[i]
        handler.draw_channel_row(context, layout, channel, root_ch, layer, mp)


def _draw_paint_channel_settings(context, layout, channel, root_ch, layer):
    """Draw streamlined channel settings for paint layers.

    Behavior:
    - Default: Custom toggle off, channel uses brush values
    - Custom toggle on: Shows custom value input for override
    - VALUE channels show luminance slider from brush color

    Args:
        context: Blender context
        layout: UI layout
        channel: YLayerChannel (layer-specific channel data)
        root_ch: MPaintChannel (root channel with name and type info)
        layer: YLayer (parent layer)
    """
    # Update brush luminance for display
    _update_brush_luminance(context)

    # Determine current state from override_type
    # Valid values: 'LAYER', 'PASSTHROUGH', 'OVERRIDE', 'IMAGE'
    override_type = getattr(channel, 'override_type', 'LAYER')
    is_custom = override_type == 'OVERRIDE'

    box = layout.box()
    box.scale_y = 1.2

    # Header row: expand toggle, enable toggle, channel name + controls
    header = box.row(align=True)
    header.scale_y = 1.3

    # Expand toggle (triangle icon)
    expand_blend = getattr(channel, 'expand_blend_settings', False)
    icon = 'TRIA_DOWN' if expand_blend else 'TRIA_RIGHT'
    header.prop(channel, "expand_blend_settings", text="", icon=icon, emboss=False)

    # Enable toggle
    header.prop(channel, "enable", text="")

    # Channel name (15% width)
    split = header.split(factor=0.15, align=True)
    name_col = split.row(align=True)
    name_col.enabled = channel.enable
    name_col.label(text=root_ch.name)

    # Controls area
    ctrl_row = split.row(align=True)
    ctrl_row.enabled = channel.enable

    # Custom toggle button (small icon button with pencil icon)
    custom_btn = ctrl_row.row(align=True)
    custom_btn.scale_x = 1.0
    # Highlight if custom is active
    if is_custom:
        custom_btn.alert = True
    custom_btn.operator(
        "channel.toggle_custom_override",
        text="",
        icon='GREASEPENCIL',
        depress=is_custom
    ).channel_index = _get_channel_index(layer, channel)

    # Check if AO channel (name-based, works for both RGB and VALUE types)
    is_ao = root_ch.name.upper() in ['AO', 'AMBIENT OCCLUSION']

    # VALUE channel handling
    if root_ch.type == 'VALUE':
        if is_custom:
            # Custom override active: show override slider
            ctrl_row.prop(channel, "override_value", text="", slider=True)
        else:
            # Default: show disabled luminance from brush color
            wm = context.window_manager
            if hasattr(wm, 'mixar_ui'):
                lum_row = ctrl_row.row(align=True)
                lum_row.enabled = False
                lum_row.prop(wm.mixar_ui, "brush_luminance", text="", slider=True)
    elif root_ch.type == 'NORMAL':
        # Normal channel: show bump_midlevel slider only for bump types
        if channel.normal_map_type in {'BUMP_MAP', 'BUMP_NORMAL_MAP'}:
            ctrl_row.prop(channel, "bump_midlevel", text="", slider=True)
    elif root_ch.type == 'RGB':
        if is_ao:
            # AO channel (RGB type): show override color for baked AO
            ctrl_row.prop(channel, "override_color", text="")
        elif root_ch.name == 'Color':
            # Color channel: show brush color picker
            brush = context.tool_settings.image_paint.brush if context and context.tool_settings else None
            if brush:
                ups = context.tool_settings.image_paint.unified_paint_settings
                if ups.use_unified_color:
                    ctrl_row.prop(ups, "color", text="")
                else:
                    ctrl_row.prop(brush, "color", text="")
        elif is_custom:
            # Custom override for other RGB types (Emission, etc.)
            ctrl_row.prop(channel, "override_color", text="")
    elif is_custom:
        # Custom override for other types
        ctrl_row.prop(channel, "override_color", text="")

    # Modifier button - shows count badge if modifiers exist
    mod_count = len(channel.modifiers)
    mod_btn = ctrl_row.row(align=True)
    mod_btn.scale_x = 1.0
    if mod_count > 0:
        mod_btn.alert = True  # Highlight when modifiers exist
    op = mod_btn.operator(
        "channel.modifiers_popup",
        text=str(mod_count) if mod_count > 0 else "",
        icon='MODIFIER'
    )
    op.layer_index = _get_layer_index(layer)
    op.channel_index = _get_channel_index(layer, channel)

    # Expanded section: blend mode + opacity
    if expand_blend:
        blend_col = box.column(align=True)
        blend_col.scale_y = 1.2
        blend_col.separator(factor=0.3)

        # Blend mode row
        blend_row = blend_col.row(align=True)
        split = blend_row.split(factor=0.3, align=True)
        split.label(text="Blend")
        if root_ch.type == "NORMAL":
            split.prop(channel, "normal_blend_type", text="")
        else:
            split.prop(channel, "blend_type", text="")

        # Opacity row
        opacity_row = blend_col.row(align=True)
        split = opacity_row.split(factor=0.3, align=True)
        split.label(text="Opacity")
        split.prop(channel, "intensity_value", text="", slider=True)

        # Normal channel extras (inside expanded section)
        if channel.enable and root_ch.type == 'NORMAL':
            _draw_normal_channel_extras(box, channel)


def _get_channel_index(layer, channel):
    """Get the index of a channel within its layer."""
    for i, ch in enumerate(layer.channels):
        if ch == channel:
            return i
    return -1


def _get_layer_index(layer):
    """Get the index of a layer within mp.layers."""
    mp = layer.id_data.mp
    for i, l in enumerate(mp.layers):
        if l == layer:
            return i
    return -1


def _draw_normal_channel_extras(layout, channel):
    """Draw extra controls for Normal channel.

    Args:
        layout: Box layout to draw into
        channel: YLayerChannel
    """
    # Normal type row
    type_row = layout.row(align=True)
    type_row.scale_y = 1.2
    split = type_row.split(factor=0.3, align=True)
    split.label(text="Type")
    split.prop(channel, "normal_map_type", text="")

    # Bump settings (only for bump types)
    if hasattr(channel, 'normal_map_type'):
        if channel.normal_map_type in {'BUMP_MAP', 'BUMP_NORMAL_MAP'}:
            # Height range
            height_row = layout.row(align=True)
            height_row.scale_y = 1.2
            split = height_row.split(factor=0.3, align=True)
            split.label(text="Height")
            split.prop(channel, 'bump_distance', text="", slider=True)

            # Midlevel
            mid_row = layout.row(align=True)
            mid_row.scale_y = 1.2
            split = mid_row.split(factor=0.3, align=True)
            split.label(text="Midlevel")
            split.prop(channel, 'bump_midlevel', text="", slider=True)

        # Normal map strength
        if channel.normal_map_type in {'NORMAL_MAP', 'BUMP_NORMAL_MAP'}:
            strength_row = layout.row(align=True)
            strength_row.scale_y = 1.2
            split = strength_row.split(factor=0.3, align=True)
            split.label(text="Strength")
            split.prop(channel, 'normal_strength', text="", slider=True)

        # VDM settings
        if channel.normal_map_type == 'VECTOR_DISPLACEMENT_MAP':
            vdisp_row = layout.row(align=True)
            vdisp_row.scale_y = 1.2
            split = vdisp_row.split(factor=0.3, align=True)
            split.label(text="VDM Strength")
            split.prop(channel, 'vdisp_strength', text="", slider=True)

            flip_row = layout.row(align=True)
            flip_row.scale_y = 1.2
            flip_row.prop(channel, 'vdisp_enable_flip_yz', text="Flip Y/Z")

        # Write Height checkbox
        wh_row = layout.row(align=True)
        wh_row.scale_y = 1.2
        wh_row.prop(channel, 'write_height', text="Write Height")
