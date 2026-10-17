# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Moodboard Add Text operator: a sample box follows the cursor until placed."""

import bpy
from bpy.types import Operator
from bpy.props import StringProperty

from mixar.modules.common.i18n import tip_
from ...core.moodboard_utils import get_moodboard_viewport_center
from ...core.canvas_context import (
    find_moodboard_canvas_region,
    redraw_moodboard_canvases,
)
from ...core.canvas_mark_mode import exit_canvas_mark_mode
from ...core.first_use import begin_preview, end_preview, mark_started
from ....common.utils.platform_utils import format_shortcut
from ...constants import (
    TEXTBOX_NAVIGATION_EVENTS,
    TEXTBOX_TEXT_DEFAULT,
    TEXTBOX_WIDTH_DEFAULT,
    TEXTBOX_HEIGHT_DEFAULT,
    TEXTBOX_FONT_SIZE_DEFAULT,
)


def _tag_moodboard_redraw():
    redraw_moodboard_canvases()


class MIXIE_OT_moodboard_add_textbox(Operator):
    bl_idname = "mixie.moodboard_add_textbox"
    bl_label = "Add Text"
    bl_description = f"Add a text box to the moodboard ({format_shortcut('T')})"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def description(cls, context, properties):
        return tip_("Add a text box to the moodboard ({shortcut})").format(
            shortcut=format_shortcut('T'))

    text: StringProperty(
        name="",
        description="Content of the text box",
        default="",
        options={'SKIP_SAVE'}
    )

    # Index of the sample text box being placed during the modal, and the
    # scene it was added to (pinned: a timer-driven scene switch must not make
    # ESC remove a box from another scene's list).
    _tb_index: int = -1
    _region = None
    _scene_uid = None

    def _preview_scene(self):
        """The scene the preview box lives in (by ``session_uid``, which
        survives renames), or None once it is gone."""
        if self._scene_uid is None:
            return None
        for scene in bpy.data.scenes:
            if getattr(scene, "session_uid", None) == self._scene_uid:
                return scene
        return None

    def _discard_preview(self):
        scene = self._preview_scene()
        if scene is None:
            return
        boxes = scene.mixie_moodboard_textboxes
        if 0 <= self._tb_index < len(boxes):
            boxes.remove(self._tb_index)
        end_preview(scene, "mixie_moodboard_textboxes")
        self._scene_uid = None
        _tag_moodboard_redraw()

    def _cursor_view_coords(self, event):
        """Mouse position (window coords) in the moodboard's canvas space."""
        region = self._region
        rx = event.mouse_x - region.x
        ry = event.mouse_y - region.y
        return region.view2d.region_to_view(rx, ry)

    def _move_to(self, scene, vx, vy):
        boxes = scene.mixie_moodboard_textboxes
        if 0 <= self._tb_index < len(boxes):
            tb = boxes[self._tb_index]
            tb.position_x = vx
            tb.position_y = vy

    def invoke(self, context, event):
        scene = context.scene
        # The Text tool takes over the canvas: a still-armed pencil would
        # otherwise draw a stroke on the first click after the box is placed.
        exit_canvas_mark_mode(context)

        # Explicit text (e.g. agent/programmatic call) → place immediately.
        if self.text.strip():
            return self.execute(context)

        region = find_moodboard_canvas_region(context)
        if region is None:
            # No visible moodboard to place into: drop a sample box at 0,0.
            self.text = TEXTBOX_TEXT_DEFAULT
            return self.execute(context)

        self._region = region

        # Create a sample text box and follow the cursor until the user clicks.
        self._scene_uid = scene.session_uid
        begin_preview(scene, "mixie_moodboard_textboxes")
        item = scene.mixie_moodboard_textboxes.add()
        item.text = TEXTBOX_TEXT_DEFAULT
        item.width = TEXTBOX_WIDTH_DEFAULT
        item.height = TEXTBOX_HEIGHT_DEFAULT
        item.font_size = TEXTBOX_FONT_SIZE_DEFAULT
        item.z_order = len(scene.mixie_moodboard_textboxes) + len(scene.mixie_moodboard_images)
        self._tb_index = len(scene.mixie_moodboard_textboxes) - 1

        # Select only the new box so it can be grabbed/edited/deleted right away.
        for tb in scene.mixie_moodboard_textboxes:
            tb.selected = False
        for img in scene.mixie_moodboard_images:
            img.selected = False
        item.selected = True

        vx, vy = self._cursor_view_coords(event)
        self._move_to(scene, vx, vy)
        _tag_moodboard_redraw()

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type in TEXTBOX_NAVIGATION_EVENTS:
            return {'PASS_THROUGH'}
        scene = self._preview_scene()
        if scene is None:
            return {'CANCELLED'}
        if event.type == 'WINDOW_DEACTIVATE':
            self.cancel(context)
            return {'CANCELLED'}

        if event.type == 'MOUSEMOVE':
            vx, vy = self._cursor_view_coords(event)
            self._move_to(scene, vx, vy)
            _tag_moodboard_redraw()
            return {'RUNNING_MODAL'}

        if event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            end_preview(scene, "mixie_moodboard_textboxes", committed=True)
            self._scene_uid = None
            _tag_moodboard_redraw()
            self.report({'INFO'}, "Added text box (double-click to edit)")
            return {'FINISHED'}

        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            self._discard_preview()
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def cancel(self, context):
        # Window close, area teardown or file load: drop the unplaced box and
        # balance begin_preview so the board's first-use state stays exact.
        self._discard_preview()

    def execute(self, context):
        scene = context.scene
        exit_canvas_mark_mode(context)

        text = self.text.strip() or TEXTBOX_TEXT_DEFAULT
        viewport_cx, viewport_cy = get_moodboard_viewport_center()
        item = scene.mixie_moodboard_textboxes.add()
        item.text = text
        item.position_x = viewport_cx
        item.position_y = viewport_cy
        item.width = TEXTBOX_WIDTH_DEFAULT
        item.height = TEXTBOX_HEIGHT_DEFAULT
        item.font_size = TEXTBOX_FONT_SIZE_DEFAULT
        item.z_order = len(scene.mixie_moodboard_textboxes) + len(scene.mixie_moodboard_images)

        _tag_moodboard_redraw()

        mark_started(scene)
        self.report({'INFO'}, "Added text box to moodboard")
        return {'FINISHED'}


classes = (
    MIXIE_OT_moodboard_add_textbox,
)
