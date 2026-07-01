# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Scene Grid Header

Header for the Scene Grid editor: editor-type switcher, tile shading
toggle, and a scene/agent summary.
"""

import bpy
from bpy.types import Header


class SCENEGRID_HT_header(Header):
    bl_space_type = 'SCENE_GRID'

    def draw(self, context):
        layout = self.layout
        layout.template_header()

        layout.label(text="Scene Grid")

        space = context.space_data
        row = layout.row(align=True)
        row.prop(space, "shading_type", text="", expand=True)

        layout.separator_spacer()

        scenes = bpy.data.scenes
        busy_count = sum(
            1 for scene in scenes if getattr(scene, 'mixie_chat_is_busy', False)
        )
        if busy_count:
            layout.label(
                text=f"{len(scenes)} scenes · {busy_count} agent(s) working",
                icon='SORTTIME',
            )
        else:
            layout.label(text=f"{len(scenes)} scenes")


classes = (
    SCENEGRID_HT_header,
)
