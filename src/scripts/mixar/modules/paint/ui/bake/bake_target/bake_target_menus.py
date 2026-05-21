# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Special menu for bake target list operations (copy/paste)."""

import bpy
from bpy.types import Menu

from ....core.node.node_utils import get_active_mpaint_node


class BAKE_MT_bake_target_special_menu(Menu):
    """Special menu for bake target list with copy/paste options.

    Provides:
    - Copy Bake Target
    - Paste Bake Target As New
    - Paste Bake Target Values (overwrites active)
    """

    bl_label = "Bake Target"
    bl_idname = "BAKE_MT_bake_target_special_menu"

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node()

    def draw(self, context):
        """Draw the bake target special menu.

        Args:
            context: Blender context.
        """
        layout = self.layout

        # Copy
        layout.operator(
            "wm.m_copy_bake_target",
            text="Copy Bake Target",
            icon='COPYDOWN'
        )

        layout.separator()

        # Paste as new
        op = layout.operator(
            "wm.m_paste_bake_target",
            text="Paste Bake Target As New",
            icon='PASTEDOWN'
        )
        op.paste_as_new = True

        # Paste values (overwrite active)
        op = layout.operator(
            "wm.m_paste_bake_target",
            text="Paste Bake Target Values",
            icon='PASTEDOWN'
        )
        op.paste_as_new = False


# Classes for registration (auto-discovered by bootstrap)
classes = (
    BAKE_MT_bake_target_special_menu,
)
