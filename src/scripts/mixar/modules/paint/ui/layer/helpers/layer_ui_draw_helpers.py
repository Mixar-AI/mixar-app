# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer UI draw helpers: menu drawing functions for layer operations."""

from ....core.layer.get_entities import any_single_user_ondisk_image_inside_group


def draw_move_up_in_layer_group(self, context):
    """Draw UI menu for moving layer up within or into a group.

    Args:
        self: UI menu context.
        context: Blender context.
    """
    col = self.layout.column()

    c = col.operator("wm.m_move_layer", text="Move Up (Skip Group)", icon="TRIA_UP")
    c.direction = "UP"

    c = col.operator(
        "wm.m_move_in_out_layer_group", text="Move Inside Group", icon="TRIA_UP"
    )
    c.direction = "UP"


def draw_move_down_in_layer_group(self, context):
    """Draw UI menu for moving layer down within or into a group.

    Args:
        self: UI menu context.
        context: Blender context.
    """
    col = self.layout.column()

    c = col.operator("wm.m_move_layer", text="Move Down (Skip Group)", icon="TRIA_DOWN")
    c.direction = "DOWN"

    c = col.operator(
        "wm.m_move_in_out_layer_group", text="Move Inside Group", icon="TRIA_DOWN"
    )
    c.direction = "DOWN"


def draw_remove_group(self, context):
    """Draw UI menu for removing a layer group with various options.

    Args:
        self: UI menu context.
        context: Blender context.
    """
    col = self.layout.column()

    c = col.operator("wm.m_remove_layer", text="Remove parent only", icon="PANEL_CLOSE")
    c.remove_children = False
    c.remove_on_disk = False

    c = col.operator(
        "wm.m_remove_layer",
        text="Remove parent with all of its children",
        icon="PANEL_CLOSE",
    )
    c.remove_children = True
    c.remove_on_disk = False

    if hasattr(context, "layer") and any_single_user_ondisk_image_inside_group(
        context.layer
    ):
        col.separator()
        col.alert = True
        col.label(text="Danger Zone", icon="ERROR")
        c = col.operator(
            "wm.m_remove_layer",
            text="Remove parent with all of its children and files on disk (WARNING: NO PROMPT & NO UNDO!)",
            icon="PANEL_CLOSE",
        )
        c.remove_children = True
        c.remove_on_disk = True
