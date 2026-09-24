# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Canvas frame operators.

Replaces the old group operators (``mixie.create_group`` and friends). Two
differences are the point of the rewrite:

* **Creating a frame asks nothing.** Ctrl+G makes the frame immediately with an
  auto name and the next palette pastel, then hands straight to the in-place
  rename so the user types over it. The old operator opened a props dialog
  with a name field and a colour picker -- a form for one word, in front of a
  gesture that should be instant.
* **A frame is a real object**, so it can be created empty, moved, re-fitted
  and re-coloured. Every one of those is an operator here rather than a side
  effect of what its members happen to be doing.

A frame is deliberately NOT hand-resizable. Its rect follows what it holds: it
grows to keep a member dragged outwards, and "Fit to Contents" wraps it back to
them. A drag-to-resize grip was a second, competing way to say where a frame's
edges go, and it fought that automatic grow on every drag.

Behaviour lives in ``core/frames.py``; these stay thin so the rules are
testable under the ``bpy`` mock.
"""

import bpy
from bpy.types import Operator
from bpy.props import BoolProperty, FloatProperty, IntProperty, StringProperty

from mixar.config.logging_config import get_logger
from mixar.modules.moodboard.constants import FRAME_PALETTE
from mixar.modules.moodboard.core import frames as frame_core

logger = get_logger(__name__)


def _redraw(context):
    if context.area:
        context.area.tag_redraw()


def _resolved_frame_id(context, frame_id: str) -> str:
    """The frame an operator should act on: the one it was given, else the one
    selected frame. Empty when that is ambiguous."""
    scene = context.scene
    if frame_id and frame_core.frame_by_id(scene, frame_id) is not None:
        return frame_id
    selected = frame_core.selected_frames(scene)
    return selected[0].frame_id if len(selected) == 1 else ""


class MIXIE_OT_moodboard_create_frame(Operator):
    """Frame the selection, or drop an empty frame on the canvas"""

    bl_idname = "mixie.moodboard_create_frame"
    bl_label = "Frame Selection"
    bl_description = (
        "Group the selected items in a new frame (Ctrl G). With nothing "
        "selected, place an empty frame to drop things into"
    )
    bl_options = {'REGISTER', 'UNDO'}

    # SKIP_SAVE on all three: this is a REGISTER operator, so a remembered
    # position from an earlier run would place every later frame at that same
    # stale point (the same reason the node-create operators skip-save their
    # drop coordinates).
    use_position: BoolProperty(default=False, options={'SKIP_SAVE'})
    position_x: FloatProperty(default=0.0, options={'SKIP_SAVE'})
    position_y: FloatProperty(default=0.0, options={'SKIP_SAVE'})
    rename: BoolProperty(
        name="Rename",
        description="Drop straight into renaming the new frame",
        default=True,
        options={'SKIP_SAVE'},
    )

    def invoke(self, context, event):
        """Record the cursor, so an EMPTY frame lands where the user is looking.

        Ctrl+G is a keypress and ``execute`` has no mouse position, so an empty
        frame would otherwise be placed at whatever the last right-click
        recorded -- or at the canvas origin, somewhere off screen.
        """
        if not frame_core.selected_items(context.scene):
            region = context.region
            if region is not None and getattr(region, "view2d", None):
                self.position_x, self.position_y = region.view2d.region_to_view(
                    event.mouse_region_x, event.mouse_region_y
                )
                self.use_position = True
        return self.execute(context)

    def execute(self, context):
        scene = context.scene
        items = frame_core.selected_items(scene)
        position = None
        if not items:
            if self.use_position:
                position = (self.position_x, self.position_y)
            else:
                # No cursor (a menu entry, an agent call): the right-click
                # menu's recorded point, else the viewport centre.
                from mixar.modules.moodboard.core.moodboard_utils import (
                    get_moodboard_viewport_center,
                )

                position = (
                    getattr(scene, "mixie_moodboard_context_x", 0.0),
                    getattr(scene, "mixie_moodboard_context_y", 0.0),
                )
                if position == (0.0, 0.0):
                    position = get_moodboard_viewport_center()

        frame = frame_core.create_frame(scene, from_items=items, position=position)
        if frame is None:
            self.report({'ERROR'}, "Could not create a frame")
            return {'CANCELLED'}

        # An empty frame also claims whatever already sits inside its rect --
        # the user framed that area, so refusing to adopt what is visibly in it
        # would be the wrong reading of the gesture.
        if not items:
            frame_core.resolve_membership(scene)

        frame_core.select_frame(scene, frame.frame_id)
        _redraw(context)

        if self.rename:
            # The field appears on the next redraw and takes focus itself; the
            # name above the frame IS the editor, so there is no dialog.
            try:
                bpy.ops.mixie.moodboard_rename_frame(frame_id=frame.frame_id)
            except (RuntimeError, AttributeError) as exc:
                # A build whose C++ half predates the inline rename keeps the
                # frame and its auto name rather than failing the create.
                logger.debug("Inline frame rename unavailable: %s", exc)
        return {'FINISHED'}


class MIXIE_OT_moodboard_ungroup(Operator):
    """Dissolve the selected frames and release what is inside them"""

    bl_idname = "mixie.moodboard_ungroup"
    bl_label = "Ungroup"
    bl_description = (
        "Dissolve the selected frames (Alt G). The items inside stay exactly "
        "where they are"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        scene = context.scene
        if not getattr(scene, "mixie_moodboard_frames", None):
            return False
        if frame_core.selected_frames(scene):
            return True
        return any(
            getattr(item, "frame_id", "")
            for item in frame_core.selected_items(scene)
        )

    def execute(self, context):
        dissolved = frame_core.ungroup_selection(context.scene)
        if not dissolved:
            self.report({'WARNING'}, "No frames to ungroup")
            return {'CANCELLED'}
        _redraw(context)
        self.report({'INFO'}, f"Dissolved {dissolved} frame(s)")
        return {'FINISHED'}


class MIXIE_OT_moodboard_delete_frame(Operator):
    """Delete a frame, optionally with everything inside it"""

    bl_idname = "mixie.moodboard_delete_frame"
    bl_label = "Delete Frame"
    bl_description = "Remove this frame. Its contents stay on the board"
    bl_options = {'REGISTER', 'UNDO'}

    frame_id: StringProperty(default="", options={'SKIP_SAVE'})
    with_contents: BoolProperty(
        name="With Contents",
        description="Also delete every item inside the frame",
        default=False,
        options={'SKIP_SAVE'},
    )

    def execute(self, context):
        scene = context.scene
        frame_id = _resolved_frame_id(context, self.frame_id)
        if not frame_id:
            self.report({'WARNING'}, "Select one frame to delete")
            return {'CANCELLED'}

        if self.with_contents:
            # Route the members through the board's OWN delete, which already
            # owns image lifecycle, link cleanup and cancelling the in-flight
            # job of a card that can no longer receive it.
            #
            # That operator deletes whatever is selected BOARD-WIDE, and
            # `select_frame_contents` only adds to the selection. Anything the
            # user had selected elsewhere -- shift-click and box-select-extend
            # both keep the previous selection -- would be destroyed too, well
            # past what this button's own "and N item(s)" label promises. So
            # the board is cleared first and the frame's own members are the
            # entire selection by the time the delete runs.
            frame_core.deselect_all_frames(scene)
            for _name, item in frame_core.board_items(scene):
                if item.selected:
                    item.selected = False
            frame_core.select_frame_contents(scene, frame_id)
            frame = frame_core.frame_by_id(scene, frame_id)
            if frame is not None:
                frame.selected = True
            try:
                bpy.ops.mixie.moodboard_delete()
            except RuntimeError as exc:
                self.report({'ERROR'}, f"Could not delete the frame's contents: {exc}")
                return {'CANCELLED'}
            _redraw(context)
            return {'FINISHED'}

        if not frame_core.delete_frame(scene, frame_id):
            self.report({'WARNING'}, "Frame not found")
            return {'CANCELLED'}
        _redraw(context)
        return {'FINISHED'}


class MIXIE_OT_moodboard_select_frame_contents(Operator):
    """Select every item inside this frame"""

    bl_idname = "mixie.moodboard_select_frame_contents"
    bl_label = "Select Contents"
    bl_description = "Select the items inside this frame instead of the frame itself"
    bl_options = {'REGISTER', 'UNDO'}

    frame_id: StringProperty(default="", options={'SKIP_SAVE'})

    def execute(self, context):
        frame_id = _resolved_frame_id(context, self.frame_id)
        if not frame_id:
            self.report({'WARNING'}, "Select one frame first")
            return {'CANCELLED'}
        count = frame_core.select_frame_contents(context.scene, frame_id)
        _redraw(context)
        if not count:
            self.report({'INFO'}, "This frame is empty")
        return {'FINISHED'}


class MIXIE_OT_moodboard_add_selection_to_frame(Operator):
    """Put the selected items into this frame, wherever they sit"""

    bl_idname = "mixie.moodboard_add_selection_to_frame"
    bl_label = "Add Selection to Frame"
    bl_description = (
        "Move the selected items into this frame and grow it to fit them"
    )
    bl_options = {'REGISTER', 'UNDO'}

    frame_id: StringProperty(default="", options={'SKIP_SAVE'})

    def execute(self, context):
        frame_id = _resolved_frame_id(context, self.frame_id)
        if not frame_id:
            self.report({'WARNING'}, "Select one frame first")
            return {'CANCELLED'}
        added = frame_core.add_selection_to_frame(context.scene, frame_id)
        if not added:
            self.report({'WARNING'}, "Nothing selected to add")
            return {'CANCELLED'}
        _redraw(context)
        self.report({'INFO'}, f"Added {added} item(s) to the frame")
        return {'FINISHED'}


class MIXIE_OT_moodboard_fit_frame(Operator):
    """Shrink or grow a frame to wrap what is inside it"""

    bl_idname = "mixie.moodboard_fit_frame"
    bl_label = "Fit to Contents"
    bl_description = "Resize this frame so it wraps its contents"
    bl_options = {'REGISTER', 'UNDO'}

    frame_id: StringProperty(default="", options={'SKIP_SAVE'})

    def execute(self, context):
        frame_id = _resolved_frame_id(context, self.frame_id)
        if not frame_id:
            self.report({'WARNING'}, "Select one frame first")
            return {'CANCELLED'}
        if not frame_core.fit_frame_to_members(context.scene, frame_id):
            self.report({'INFO'}, "This frame is empty")
            return {'CANCELLED'}
        _redraw(context)
        return {'FINISHED'}


class MIXIE_OT_moodboard_set_frame_color(Operator):
    """Give this frame one of the palette's pastels"""

    bl_idname = "mixie.moodboard_set_frame_color"
    bl_label = "Frame Colour"
    bl_description = "Change this frame's colour"
    bl_options = {'REGISTER', 'UNDO'}

    frame_id: StringProperty(default="", options={'SKIP_SAVE'})
    palette_index: IntProperty(
        default=0, min=0, max=max(len(FRAME_PALETTE) - 1, 0), options={'SKIP_SAVE'}
    )

    def execute(self, context):
        frame_id = _resolved_frame_id(context, self.frame_id)
        frame = frame_core.frame_by_id(context.scene, frame_id)
        if frame is None:
            self.report({'WARNING'}, "Select one frame first")
            return {'CANCELLED'}
        frame.palette_index = self.palette_index
        # Picking a pastel is also how a custom colour is abandoned; the custom
        # value itself is kept, so the flag can be turned back on.
        frame.use_custom_color = False
        _redraw(context)
        return {'FINISHED'}


class MIXIE_OT_moodboard_toggle_frame_flag(Operator):
    """Lock or collapse a frame"""

    bl_idname = "mixie.moodboard_toggle_frame_flag"
    bl_label = "Frame Option"
    bl_description = "Toggle this frame's lock or collapsed state"
    bl_options = {'REGISTER', 'UNDO'}

    frame_id: StringProperty(default="", options={'SKIP_SAVE'})
    flag: StringProperty(default="locked", options={'SKIP_SAVE'})

    # Exactly the two presentation flags a frame carries. An allowlist rather
    # than a bare setattr: `flag` arrives from a menu and must never be able to
    # name an arbitrary RNA property.
    _FLAGS = ("locked", "collapsed")

    def execute(self, context):
        if self.flag not in self._FLAGS:
            self.report({'ERROR'}, "Unknown frame option")
            return {'CANCELLED'}
        frame_id = _resolved_frame_id(context, self.frame_id)
        frame = frame_core.frame_by_id(context.scene, frame_id)
        if frame is None:
            self.report({'WARNING'}, "Select one frame first")
            return {'CANCELLED'}
        setattr(frame, self.flag, not getattr(frame, self.flag))
        _redraw(context)
        return {'FINISHED'}


class MIXIE_OT_moodboard_reframe(Operator):
    """Re-resolve which frame each board item belongs to"""

    bl_idname = "mixie.moodboard_reframe"
    bl_label = "Resolve Frame Membership"
    bl_description = (
        "Work out which frame each item now sits inside, after something moved"
    )
    # No UNDO: this runs at the END of a drag whose own operator already pushed
    # a step, and an extra one there would make Ctrl+Z undo the membership
    # without undoing the move that caused it.
    bl_options = {'REGISTER', 'INTERNAL'}

    def execute(self, context):
        # Always sticky, always grows: a member nudged past its frame's edge
        # stays a member and the frame stretches to cover it. There is no
        # opt-out because nothing needs one -- a frame has no manual resize,
        # and shrinking its rect past a member was the only gesture that ever
        # meant "release this one".
        changed = frame_core.resolve_membership(context.scene)
        if changed:
            _redraw(context)
        return {'FINISHED'}


classes = (
    MIXIE_OT_moodboard_create_frame,
    MIXIE_OT_moodboard_ungroup,
    MIXIE_OT_moodboard_delete_frame,
    MIXIE_OT_moodboard_select_frame_contents,
    MIXIE_OT_moodboard_add_selection_to_frame,
    MIXIE_OT_moodboard_fit_frame,
    MIXIE_OT_moodboard_set_frame_color,
    MIXIE_OT_moodboard_toggle_frame_flag,
    MIXIE_OT_moodboard_reframe,
)
