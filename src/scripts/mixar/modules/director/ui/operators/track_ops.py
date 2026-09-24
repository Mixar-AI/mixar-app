# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Top-strip controls: keyframe interpolation and the object eyedropper.

One eyedropper serves both things a director points at an object — what
the camera tracks and what it focuses on. Everything up to the click is
the same, so ``purpose`` decides only what the picked object becomes.
"""

from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator

from ...constants import BEAT_INTERPOLATION_ITEMS
from ...constants import BEAT_INTERPOLATION_DEFAULT
from ...core.dof import clear_focus_object, set_focus_object
from ...core.interpolation import apply_interpolation
from ...core.selection import parse_indices
from ...core.shot_api import active_shot
from ...core.tracking import pick_object_under_cursor
from ...core.viewport import find_view3d_context
from ..track_pick_overlay import disable as disable_hover
from ..track_pick_overlay import enable as enable_hover
from ..track_pick_overlay import set_hover


def _editable_shot(context):
    shot = active_shot(context.scene)
    if shot is None or shot.state != 'DRAFT' or shot.camera is None:
        return None
    return shot


class MIXAR_OT_director_set_interpolation(Operator):
    """Choose how the camera eases out of the selected keyframes"""

    bl_idname = "mixar.director_set_interpolation"
    bl_label = "Interpolation"
    bl_options = {'REGISTER', 'UNDO'}

    # The shot's own enum is a subset of this one: `SHOT` is only meaningful
    # with a selection, where it hands a keyframe back to the shot's default.
    interpolation: EnumProperty(
        name="Interpolation",
        items=BEAT_INTERPOLATION_ITEMS,
        default="BEZIER",
    )
    # The timeline's selected keyframes, as the dock passes them. Empty means
    # "no selection", which sets the shot's default rather than nothing —
    # picking a type with nothing selected has to do something.
    indices: StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return _editable_shot(context) is not None

    def execute(self, context):
        shot = _editable_shot(context)
        if shot is None:
            return {'CANCELLED'}
        selected = [
            index
            for index in parse_indices(self.indices)
            if 0 <= index < len(shot.beats)
        ]
        if not selected:
            if self.interpolation == BEAT_INTERPOLATION_DEFAULT:
                # There is nothing above a shot to inherit from.
                self.report({'ERROR'}, "Select keyframes to hand back to the shot")
                return {'CANCELLED'}
            # The property's update callback re-interpolates the existing keys.
            shot.interpolation = self.interpolation
            return {'FINISHED'}
        for index in selected:
            shot.beats[index].interpolation = self.interpolation
        # Each write above re-applied on its own; one more is cheap and makes
        # the whole pass land even if a single beat's update failed closed.
        apply_interpolation(shot)
        self.report({'INFO'}, f"Interpolation set on {len(selected)} keyframe(s)")
        return {'FINISHED'}


class MIXAR_OT_director_pick_track_target(Operator):
    """Pick an object in the viewport for the shot camera to keep pointing at"""

    bl_idname = "mixar.director_pick_track_target"
    bl_label = "Track Object"
    bl_description = (
        "Eyedropper: click an object and the shot camera keeps pointing at it "
        "while you move; click again to stop tracking"
    )
    bl_options = {'REGISTER', 'UNDO'}

    clear: BoolProperty(
        name="Clear",
        description="Stop tracking instead of picking",
        default=False,
        options={'SKIP_SAVE'},
    )
    # One eyedropper, two things a director points it at. Everything up to
    # the click is identical — the cursor, the hover outline, the ray cast,
    # the camera never being a valid answer — so the purpose only decides
    # what the picked object becomes.
    purpose: EnumProperty(
        name="Purpose",
        items=(
            ('TRACK', "Track", "Keep the camera pointing at the object"),
            ('FOCUS', "Focus", "Keep the object in focus"),
        ),
        default='TRACK',
        options={'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        return _editable_shot(context) is not None

    def invoke(self, context, _event):
        shot = _editable_shot(context)
        if shot is None:
            return {'CANCELLED'}
        if self.clear:
            if self.purpose == 'FOCUS':
                clear_focus_object(shot.camera)
                self.report({'INFO'}, "Focus released at its last distance")
                return {'FINISHED'}
            shot.track_target = None
            self.report({'INFO'}, "Camera tracking cleared")
            return {'FINISHED'}
        area, region = self._viewport(context)
        if region is None:
            self.report({'ERROR'}, "Start the eyedropper from the 3D viewport")
            return {'CANCELLED'}
        context.window.cursor_modal_set('EYEDROPPER')
        # A cursor alone said nothing: the director clicked and found out
        # afterwards what had been picked, and a miss looked like a hit on the
        # wrong object. The hover outlines and names what is under the pointer.
        enable_hover(region)
        self._area = area
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    @staticmethod
    def _viewport(context):
        """``(area, region)`` of the viewport to hover in, or ``(None, None)``.

        The top strip's chip lives in the viewport already. The focus
        eyedropper is reached from a popup, whose own temporary region is
        what `context` then names — scoping the hover to THAT would paint
        nothing, so the real viewport is resolved instead. `modal()` still
        reads the region under the pointer, which is what the pick needs.
        """
        area = getattr(context, "area", None)
        region = getattr(context, "region", None)
        if (
            region is not None
            and region.type == 'WINDOW'
            and area is not None
            and area.type == 'VIEW_3D'
        ):
            return area, region
        target = find_view3d_context(context)
        if target is None:
            return None, None
        _window, area, region, _space = target
        return area, region

    def cancel(self, context):
        # The window-level modal handler can be torn down without `modal()`
        # running again (File > New / Load Factory Settings, an agent script
        # calling `bpy.ops.wm.read_homefile()`), and those paths do not go
        # through the `WM_cursor_wait` bracket that incidentally restores the
        # cursor. Without this the eyedropper cursor — and now its hover
        # overlay — sticks permanently.
        context.window.cursor_modal_restore()
        self._end()

    def _end(self) -> None:
        disable_hover()
        try:
            self._area.tag_redraw()
        except (AttributeError, ReferenceError):
            pass

    def _hover(self, context, event) -> None:
        """Outline and name whatever is under the pointer right now."""
        space = getattr(context, "space_data", None)
        region_3d = getattr(space, "region_3d", None)
        region = context.region
        target = None
        if region is not None and region_3d is not None:
            try:
                target = pick_object_under_cursor(
                    context,
                    region,
                    region_3d,
                    (event.mouse_region_x, event.mouse_region_y),
                )
            except Exception:  # noqa: BLE001 — a hover must never end the pick
                target = None
        shot = _editable_shot(context)
        if shot is not None and target is not None and target == shot.camera:
            # The camera is not a target it can track; do not offer it.
            target = None
        if set_hover(target, (event.mouse_region_x, event.mouse_region_y)) or target is not None:
            self._end_redraw(context)

    def _end_redraw(self, context) -> None:
        area = getattr(context, "area", None)
        if area is not None:
            area.tag_redraw()

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            self._hover(context, event)
            return {'RUNNING_MODAL'}
        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            context.window.cursor_modal_restore()
            self._end()
            return {'CANCELLED'}
        if event.type != 'LEFTMOUSE' or event.value != 'PRESS':
            return {'RUNNING_MODAL'}
        shot = _editable_shot(context)
        region = context.region
        space = getattr(context, "space_data", None)
        region_3d = getattr(space, "region_3d", None)
        if shot is None or region is None or region_3d is None:
            context.window.cursor_modal_restore()
            self._end()
            return {'CANCELLED'}
        coord = (event.mouse_region_x, event.mouse_region_y)
        try:
            target = pick_object_under_cursor(context, region, region_3d, coord)
        except Exception as exc:  # noqa: BLE001 — surfaced, never swallowed
            context.window.cursor_modal_restore()
            self._end()
            self.report({'ERROR'}, f"Could not pick: {exc}")
            return {'CANCELLED'}
        if target is None or target == shot.camera:
            # Keep the eyedropper alive: a miss is not a decision.
            self.report({'WARNING'}, "No object under the cursor")
            return {'RUNNING_MODAL'}
        context.window.cursor_modal_restore()
        self._end()
        if self.purpose == 'FOCUS':
            # Focus alone: the framing and the angle the director chose are
            # not this pick's business, and an object already in shot is
            # usually exactly what they want sharp.
            if not set_focus_object(shot.camera, target):
                self.report({'ERROR'}, "This camera cannot hold a focus object")
                return {'CANCELLED'}
            self.report({'INFO'}, f"Focused on {target.name}")
            return {'FINISHED'}
        # Tracking only AIMS: the constraint turns the camera to the target.
        # Where the camera stands and how much of the frame the subject fills
        # stay the director's — the pick never moves the camera or its lens.
        shot.track_target = target
        self.report({'INFO'}, f"Camera tracks {target.name}")
        return {'FINISHED'}


classes = (
    MIXAR_OT_director_set_interpolation,
    MIXAR_OT_director_pick_track_target,
)
