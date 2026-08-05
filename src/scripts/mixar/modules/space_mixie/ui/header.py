# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixie Space Header

Header definition for the Mixie space.

NOTE: the animated per-generation loading indicator that used to live
here ("Generating Image [□■□□□]" + a 100ms redraw timer) was removed —
the Queue panel is the single place generation progress is shown.
"""

import bpy
from bpy.types import Header, Menu


def _has_moodboard_content(context):
    """Check if there is any content in the moodboard."""
    scene = context.scene
    has_content = False
    if hasattr(scene, 'mixie_moodboard_images') and len(scene.mixie_moodboard_images) > 0:
        has_content = True
    if hasattr(scene, 'mixie_moodboard_textboxes') and len(scene.mixie_moodboard_textboxes) > 0:
        has_content = True
    return has_content


class MIXIE_MT_view(Menu):
    bl_label = "View"

    def draw(self, context):
        layout = self.layout

        # Toggle toolbar visibility
        layout.operator(
            "screen.region_toggle",
            text="Toolbar",
            icon='CHECKBOX_HLT' if MIXIE_HT_header._is_toolbar_visible(context) else 'CHECKBOX_DEHLT'
        ).region_type = 'TOOLS'

        # Toggle sidebar visibility
        layout.operator(
            "screen.region_toggle",
            text="Sidebar",
            icon='CHECKBOX_HLT' if MIXIE_HT_header._is_sidebar_visible(context) else 'CHECKBOX_DEHLT'
        ).region_type = 'UI'


class MIXIE_HT_header(Header):
    bl_space_type = 'MIXIE'

    @staticmethod
    def _is_toolbar_visible(context):
        for region in context.area.regions:
            if region.type == 'TOOLS':
                # Region is visible if it has non-zero width
                return region.width > 0
        return False

    @staticmethod
    def _is_sidebar_visible(context):
        for region in context.area.regions:
            if region.type == 'UI':
                # Region is visible if it has non-zero width
                return region.width > 0
        return False

    def draw(self, context):
        layout = self.layout
        layout.template_header()

        layout.label(text="Moodboard")

        # Add View menu (commented out)
        # layout.menu("MIXIE_MT_view")

        # Show "Clear Moodboard" button when there is content in moodboard
        if _has_moodboard_content(context):
            layout.separator_spacer()
            row = layout.row(align=True)
            row.operator(
                "mixie.clear_moodboard",
                text="Clear Moodboard",
                icon='X'
            )


classes = (
    MIXIE_MT_view,
    MIXIE_HT_header,
)
