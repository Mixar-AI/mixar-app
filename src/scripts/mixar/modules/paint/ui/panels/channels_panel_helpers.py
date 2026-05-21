# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Helper functions for channels panel UI drawing."""


def draw_channels_content(layout, mp):
    """Draw the channels list content.

    Currently a placeholder for future channel management functionality.

    Args:
        layout: Blender layout object
        mp: MPaint root property group
    """
    # Top toolbar with add/remove buttons
    # toolbar = layout.row(align=True)
    # toolbar.operator("channels.add_channel", text="Add Channel", icon='ADD')

    # Remove button (only enabled if channel is selected)
    # remove_row = toolbar.row(align=True)
    # remove_row.operator("channels.remove_channel", text="Remove", icon='REMOVE')
    # remove_row.enabled = mp.active_channel_index >= 0 and mp.active_channel_index < len(mp.channels)

    # layout.separator()

    # Channels list
    # if len(mp.channels) == 0:
    #     box = layout.box()
    #     box.label(text="No channels", icon='INFO')
    # else:
    #     for i, channel in enumerate(mp.channels):
    #         draw_channel_item(layout, channel, i, mp)
    pass


def draw_channel_item(layout, channel, index, mp):
    """Draw a single channel item.

    Args:
        layout: Blender layout object
        channel: Channel object
        index: Channel index
        mp: MPaint root property group
    """
    is_active = index == mp.active_channel_index

    # Channel row
    box = layout.box()
    row = box.row(align=True)

    # Active indicator
    if is_active:
        row.label(text="", icon='LAYER_ACTIVE')
    else:
        row.label(text="", icon='LAYER_USED')

    # Channel name and type
    row.label(text=f"{channel.name} ({channel.type})")

    # Spacer to push buttons to the right
    row.separator()

    # Move buttons
    move_col = row.column(align=True)
    move_col.scale_x = 0.8
    move_col.scale_y = 0.6

    # Up button
    up_row = move_col.row(align=True)
    up_op = up_row.operator("channels.move_channel", text="", icon='TRIA_UP', emboss=False)
    up_op.direction = 'UP'
    up_op.channel_index = index
    up_row.enabled = index > 0

    # Down button
    down_row = move_col.row(align=True)
    down_op = down_row.operator("channels.move_channel", text="", icon='TRIA_DOWN', emboss=False)
    down_op.direction = 'DOWN'
    down_op.channel_index = index
    down_row.enabled = index < len(mp.channels) - 1
