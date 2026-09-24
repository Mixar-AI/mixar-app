# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Frame menus: the colour swatches and the frame's own More menu.

Their own file because ``moodboard_menus.py`` already sits at the 500-line
ceiling, and because these are reached from two places -- the right-click
context menu and the More button floating above a selected frame.
"""

import bpy
from bpy.types import Menu

from mixar.modules.moodboard.constants import FRAME_PALETTE
from mixar.modules.moodboard.core import frames as frame_core


def _menu_frame_id(context) -> str:
    """The frame these menus act on: the one selected frame, else empty.

    A menu cannot carry an id of its own (``WM_OT_call_menu`` builds its
    buttons in Python with no operator properties to inherit), so the SUBJECT
    is the selection -- which the button that opens the menu has already made,
    since clicking a frame's border selects it.
    """
    selected = frame_core.selected_frames(context.scene)
    return selected[0].frame_id if len(selected) == 1 else ""


class MIXIE_MT_moodboard_frame_color(Menu):
    """Choose this frame's colour"""

    bl_label = "Colour"
    bl_idname = "MIXIE_MT_moodboard_frame_color"

    def draw(self, context):
        layout = self.layout
        frame_id = _menu_frame_id(context)
        frame = frame_core.frame_by_id(context.scene, frame_id)
        current = frame.palette_index if frame is not None else -1
        for index, (name, _rgb) in enumerate(FRAME_PALETTE):
            row = layout.row()
            op = row.operator(
                "mixie.moodboard_set_frame_color",
                text=name,
                # A dot marks the one in use; the swatch itself is on the frame
                # and this menu has no colour-chip widget to offer.
                icon='RADIOBUT_ON' if index == current else 'RADIOBUT_OFF',
            )
            op.frame_id = frame_id
            op.palette_index = index


class MIXIE_MT_moodboard_frame(Menu):
    """Everything a frame can do that is not its name."""

    bl_label = "Frame"
    bl_idname = "MIXIE_MT_moodboard_frame"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        frame_id = _menu_frame_id(context)
        frame = frame_core.frame_by_id(scene, frame_id)
        if frame is None:
            layout.label(text="Select one frame", icon='INFO')
            return

        member_count = len(frame_core.frame_members(scene, frame_id))
        has_selection = bool(frame_core.selected_items(scene))

        row = layout.row()
        row.enabled = member_count > 0
        op = row.operator(
            "mixie.moodboard_select_frame_contents",
            text=f"Select Contents ({member_count})" if member_count else "Select Contents",
            icon='RESTRICT_SELECT_OFF',
        )
        op.frame_id = frame_id

        row = layout.row()
        row.enabled = has_selection
        op = row.operator(
            "mixie.moodboard_add_selection_to_frame",
            text="Add Selection to Frame",
            icon='ADD',
        )
        op.frame_id = frame_id

        row = layout.row()
        row.enabled = member_count > 0
        op = row.operator(
            "mixie.moodboard_fit_frame", text="Fit to Contents", icon='FULLSCREEN_EXIT'
        )
        op.frame_id = frame_id

        layout.separator()
        layout.menu(MIXIE_MT_moodboard_frame_color.bl_idname, icon='COLOR')

        op = layout.operator(
            "mixie.moodboard_toggle_frame_flag",
            text="Unlock Frame" if frame.locked else "Lock Frame",
            icon='UNLOCKED' if frame.locked else 'LOCKED',
        )
        op.frame_id = frame_id
        op.flag = "locked"

        op = layout.operator(
            "mixie.moodboard_toggle_frame_flag",
            text="Expand Frame" if frame.collapsed else "Collapse Frame",
            icon='TRIA_DOWN' if frame.collapsed else 'TRIA_RIGHT',
        )
        op.frame_id = frame_id
        op.flag = "collapsed"

        layout.separator()
        # F2 renames, and so does a double-click on the name. Listed because a
        # keymap item carrying properties is not matched when Blender looks for
        # a menu entry's shortcut, so the label has to say it (same reason
        # Frame Selected spells out "Numpad .").
        op = layout.operator(
            "mixie.moodboard_rename_frame", text="Rename (F2)", icon='GREASEPENCIL'
        )
        op.frame_id = frame_id

        layout.operator("mixie.moodboard_ungroup", text="Ungroup (Alt G)", icon='UGLYPACKAGE')

        layout.separator()
        op = layout.operator(
            "mixie.moodboard_delete_frame", text="Delete Frame", icon='X'
        )
        op.frame_id = frame_id
        op.with_contents = False
        # Destructive, and deliberately NOT what Delete/X does: a frame's
        # contents are the board's references, so removing them needs its own
        # entry rather than riding a key the user presses to tidy up.
        row = layout.row()
        row.enabled = member_count > 0
        op = row.operator(
            "mixie.moodboard_delete_frame",
            text=f"Delete Frame and {member_count} Item(s)",
            icon='TRASH',
        )
        op.frame_id = frame_id
        op.with_contents = True


classes = (
    MIXIE_MT_moodboard_frame_color,
    MIXIE_MT_moodboard_frame,
)
