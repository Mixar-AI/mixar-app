# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Move, resize, and fit the camera frame inside the Director viewport."""

import bpy
from bpy.types import Operator

from ...core.viewport import find_view3d_context

# Mirrors BKE_screen_view3d_zoom_to_fac: how much of the region one unit of
# camera offset spans at the current camera zoom.
_SQRT2 = 2.0 ** 0.5
_CAMZOOM_MIN = -30.0
_CAMZOOM_MAX = 600.0


def _zoom_to_fac(camera_zoom: float) -> float:
    return ((_SQRT2 + camera_zoom / 50.0) ** 2) / 4.0


def _scale_camera_zoom(region_3d, scale: float) -> None:
    fac = max(_zoom_to_fac(region_3d.view_camera_zoom) * scale, 1e-3)
    zoom = ((4.0 * fac) ** 0.5 - _SQRT2) * 50.0
    region_3d.view_camera_zoom = max(_CAMZOOM_MIN, min(_CAMZOOM_MAX, zoom))


def _camera_view_target(context):
    """The Director viewport while it is locked to the camera, or ``None``."""
    state = getattr(context.scene, "mixar_director", None)
    if state is None or not state.is_directing:
        return None
    target = find_view3d_context(context)
    if target is None:
        return None
    space = target[3]
    region_3d = getattr(space, "region_3d", None)
    if region_3d is None or region_3d.view_perspective != 'CAMERA':
        return None
    return target


# Per-region Full View round trip: what the framing was before the fill and
# what the fill produced, so a second click can shrink the frame back.
_view_memory: dict[int, dict] = {}


def _framing(region_3d) -> tuple:
    return (
        tuple(region_3d.view_camera_offset),
        float(region_3d.view_camera_zoom),
    )


def _same_framing(a: tuple, b: tuple) -> bool:
    return (
        abs(a[0][0] - b[0][0]) < 1e-4
        and abs(a[0][1] - b[0][1]) < 1e-4
        and abs(a[1] - b[1]) < 0.5
    )


class MIXAR_OT_director_fit_frame(Operator):
    """Toggle between a viewport-filling camera frame and the framing before"""

    bl_idname = "mixar.director_fit_frame"
    bl_label = "Full View"
    bl_description = (
        "Fill the viewport with the camera frame; click again to shrink it "
        "back"
    )

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, "mixar_director", None)
        return bool(state and state.is_directing)

    def execute(self, context):
        target = _camera_view_target(context)
        if target is None:
            return {'CANCELLED'}
        window, area, region, space = target
        region_3d = space.region_3d
        key = region.as_pointer()
        current = _framing(region_3d)
        memory = _view_memory.get(key)
        if memory is not None and _same_framing(current, memory["fitted"]):
            region_3d.view_camera_offset = memory["before"][0]
            region_3d.view_camera_zoom = memory["before"][1]
            del _view_memory[key]
            area.tag_redraw()
            return {'FINISHED'}
        with context.temp_override(
            window=window,
            area=area,
            region=region,
            space_data=space,
        ):
            result = bpy.ops.view3d.view_center_camera()
        if 'FINISHED' in result:
            fitted = _framing(region_3d)
            if _same_framing(current, fitted):
                # Already filled before the first click (file opened that
                # way): fall back to Blender's default padded camera view so
                # the toggle always has somewhere to shrink back to.
                current = ((0.0, 0.0), 0.0)
            _view_memory[key] = {"before": current, "fitted": fitted}
        area.tag_redraw()
        return result


class MIXAR_OT_director_drag_frame(Operator):
    """Reposition and resize the camera frame inside the viewport"""

    bl_idname = "mixar.director_drag_frame"
    bl_label = "Move Frame"
    bl_description = (
        "Move the camera frame with the mouse, scroll to resize, "
        "click to place, Esc to put it back"
    )

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, "mixar_director", None)
        return bool(state and state.is_directing)

    def invoke(self, context, event):
        target = _camera_view_target(context)
        if target is None:
            self.report({'WARNING'}, "The viewport is not in camera view")
            return {'CANCELLED'}
        window, area, region, space = target
        if window != context.window:
            return {'CANCELLED'}
        self._area = area
        self._region = region
        self._region_3d = space.region_3d
        self._start_offset = tuple(self._region_3d.view_camera_offset)
        self._start_zoom = float(self._region_3d.view_camera_zoom)
        self._anchor = (event.mouse_x, event.mouse_y)
        context.window.cursor_modal_set('HAND')
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            # Native camera-view pan: offset += (previous - current) pixels
            # over the region size scaled by twice the zoom factor, so the
            # frame follows the pointer exactly like Blender's own pan.
            fac = _zoom_to_fac(self._region_3d.view_camera_zoom) * 2.0
            delta_x = (self._anchor[0] - event.mouse_x) / (self._region.width * fac)
            delta_y = (self._anchor[1] - event.mouse_y) / (self._region.height * fac)
            self._region_3d.view_camera_offset = (
                max(-1.0, min(1.0, self._start_offset[0] + delta_x)),
                max(-1.0, min(1.0, self._start_offset[1] + delta_y)),
            )
            self._area.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            _scale_camera_zoom(
                self._region_3d,
                1.15 if event.type == 'WHEELUPMOUSE' else 1.0 / 1.15,
            )
            self._area.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type in {'LEFTMOUSE', 'RET', 'SPACE'} and event.value == 'PRESS':
            self._end(context)
            return {'FINISHED'}
        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            self._region_3d.view_camera_offset = self._start_offset
            self._region_3d.view_camera_zoom = self._start_zoom
            self._end(context)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        self._end(context)

    def _end(self, context):
        context.window.cursor_modal_restore()
        try:
            self._area.tag_redraw()
        except (AttributeError, ReferenceError):
            pass


classes = (
    MIXAR_OT_director_fit_frame,
    MIXAR_OT_director_drag_frame,
)
