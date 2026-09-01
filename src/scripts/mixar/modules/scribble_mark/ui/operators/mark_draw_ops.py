# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The mark modal — freeze the viewport, capture strokes, resolve each mark.

Arming runs this operator. It captures the viewport to a still, bakes a
camera matching the view, and then owns the region until the user disarms:
every pointer event inside it is consumed, so an accidental orbit cannot
leave marks describing a view that no longer exists.

**Strokes group by pause, not by declaration.** Everything drawn within
``MARK_COMMIT_IDLE_S`` of the last pen-up becomes one mark, so an arrow's
shaft and head — or an X's two lines — arrive as a single gesture without the
user having to say so. It is the same idle-commit shape the handwriting
canvas uses, so it is a rhythm people meet twice rather than a new rule.

Resolution runs at commit time, here on the main thread, not at send time.
By the time the user presses Send the payload is already built, so pointing
at something never adds latency to sending a message.
"""

from __future__ import annotations

import time

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.scribble_mark.constants import (
    MARK_COMMIT_IDLE_S,
    MARK_TIMER_STEP_S,
    MAX_MARKS_PER_TURN,
    MAX_POINTS_PER_STROKE,
    MAX_STROKES_PER_MARK,
    MIN_SAMPLE_DIST_PX,
)
from mixar.modules.scribble_mark.core import (
    freeze,
    gesture,
    marks as mark_store,
    overlay,
    resolve,
    view_bake,
)

logger = get_logger(__name__)

#: Module-level guard. Modal operators do not survive a .blend load, but this
#: flag does — the same trap agent_viewport_lock documents — so the disarm
#: path and the load handler both clear it.
_running = False


def is_running():
    return _running


def reset_running_guard():
    """Clear the stale guard after a file load tore the modal down."""
    global _running
    _running = False


class MIXAR_OT_scribble_mark_draw(Operator):
    """Freeze the viewport and draw marks on it for the agent"""

    bl_idname = "mixar.scribble_mark_draw"
    bl_label = "Mark the Viewport"
    bl_options = {"REGISTER", "INTERNAL"}

    _timer = None
    _area_ptr = 0
    _region_ptr = 0
    _strokes = None
    _current = None
    _last_up = 0.0
    _view_name = ""
    _view_data = None
    _view_used = False
    _frame_name = ""
    _region_size = (0, 0)

    # -- lifecycle -------------------------------------------------------

    def invoke(self, context, event):
        global _running
        if _running:
            return {"CANCELLED"}

        window, area, region = _find_view3d(context)
        if area is None or region is None:
            self.report({"WARNING"}, "No 3D viewport to mark")
            return {"CANCELLED"}

        space = area.spaces.active
        rv3d = getattr(space, "region_3d", None)
        if getattr(rv3d, "view_perspective", "") == "CAMERA":
            # In camera view the region shows the camera frame letterboxed
            # inside it, and render.opengl captures only that frame — so a
            # mark's region coordinates would not correspond to any position
            # in the still, and every raycast would land somewhere the user
            # did not point. Refusing is the honest option; silently marking
            # the wrong place is not.
            self.report({"WARNING"},
                        "Leave camera view (Numpad 0) before marking")
            return {"CANCELLED"}

        serial = mark_store.next_serial(context.scene)
        frame_name = freeze.frame_name(serial)
        frame = freeze.capture_region_still(context, window, area, region,
                                            frame_name)
        if frame is None:
            # Refusing to arm is deliberate: with nothing frozen the user
            # would be drawing on a live viewport that can move under them,
            # and every mark would describe a view that no longer exists.
            self.report({"ERROR"}, "Could not freeze the viewport")
            return {"CANCELLED"}

        self._view_name, self._view_data = view_bake.bake_view(
            context, area, region, serial
        )
        self._view_used = False

        context.scene.mixar_mark_frame_name = frame
        self._frame_name = frame
        self._area_ptr = area.as_pointer()
        self._region_ptr = region.as_pointer()
        # The region can be resized while the freeze is up (dragging an editor
        # border, resizing the window). The still and the baked camera are
        # fixed at this size, so marks must be normalized against it too — not
        # against whatever the region has become by commit time, which would
        # shear the payload against its own picture.
        self._region_size = (region.width, region.height)
        self._strokes = []
        self._current = None
        self._last_up = 0.0

        overlay.reset()
        overlay.set_target(self._area_ptr, self._region_ptr)
        overlay.install()
        context.window_manager.mixar_mark_armed = True

        wm = context.window_manager
        # Bound to the window that OWNS the frozen viewport, not to whichever
        # window the button was clicked in — see _find_view3d.
        with context.temp_override(window=window, area=area, region=region):
            self._timer = wm.event_timer_add(MARK_TIMER_STEP_S, window=window)
            wm.modal_handler_add(self)
        _running = True
        overlay.tag_redraw()
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        wm = context.window_manager

        # The toggle button, ESC, and any other disarm all work by clearing
        # this one flag — there is no second way to stop the modal to keep in
        # sync with it.
        if not getattr(wm, "mixar_mark_armed", False):
            self._commit_pending(context)
            self._finish(context)
            return {"FINISHED"}

        region = self._region(context)
        if region is None:
            # The viewport we froze is gone (area split, workspace change).
            # Marks already committed are safe in the scene; stop cleanly.
            self._commit_pending(context)
            self._disarm(context)
            self._finish(context)
            return {"FINISHED"}

        if event.type == "TIMER":
            self._maybe_commit(context, region)
            return {"RUNNING_MODAL"}

        # Undo, reachable from inside the freeze. Drawing a mark you did not
        # mean and having no way back short of leaving the mode is exactly the
        # brittleness users report of ink tools; the freeze owns every event
        # over this region, so the binding lives here rather than in a keymap
        # (which a GUI keyconfig reload would wipe).
        if (event.value == "PRESS"
                and (event.type in ("BACK_SPACE", "DEL")
                     or (event.type == "Z" and (event.ctrl or event.oskey)))):
            self._undo_last(context)
            return {"RUNNING_MODAL"}

        if event.type == "ESC" and event.value == "PRESS":
            self._commit_pending(context)
            self._disarm(context)
            self._finish(context)
            return {"FINISHED"}

        inside = _point_in_region(region, event.mouse_x, event.mouse_y)
        if not inside:
            # Outside the frozen viewport the app is entirely normal — the
            # chat, the sidebar and every other editor keep working, which is
            # how the user types the prompt that goes with their marks.
            return {"PASS_THROUGH"}

        point = (float(event.mouse_x - region.x), float(event.mouse_y - region.y))

        if event.type == "LEFTMOUSE":
            if event.value == "PRESS":
                self._begin_stroke(point)
            elif event.value == "RELEASE":
                self._end_stroke(context)
            return {"RUNNING_MODAL"}

        if event.type == "MOUSEMOVE" and self._current is not None:
            self._extend_stroke(point)
            return {"RUNNING_MODAL"}

        # Everything else over the frozen frame is swallowed. That is the
        # freeze: a stray middle-drag or scroll here would move the view out
        # from under marks that are already anchored to this frame.
        return {"RUNNING_MODAL"}

    def cancel(self, context):
        # Every exit path leaves the same state. A cancel that tears the modal
        # down but leaves the armed flag set gives the header a depressed
        # toggle with nothing behind it, and the next click merely clears the
        # flag instead of arming.
        self._disarm(context)
        self._finish(context)

    # -- strokes ---------------------------------------------------------

    def _begin_stroke(self, point):
        if len(self._strokes) >= MAX_STROKES_PER_MARK:
            return
        self._current = [point]
        self._strokes.append(self._current)
        overlay.set_live_strokes(self._strokes)
        overlay.tag_redraw()

    def _extend_stroke(self, point):
        stroke = self._current
        if stroke is None or len(stroke) >= MAX_POINTS_PER_STROKE:
            return
        last = stroke[-1]
        threshold = MIN_SAMPLE_DIST_PX * _ui_scale()
        if abs(point[0] - last[0]) < threshold and abs(point[1] - last[1]) < threshold:
            return
        stroke.append(point)
        overlay.tag_redraw()

    def _end_stroke(self, context):
        self._current = None
        self._last_up = time.monotonic()
        overlay.tag_redraw()

    def _maybe_commit(self, context, region):
        """Commit once the pen has been up long enough."""
        if self._current is not None or not self._strokes:
            return
        if time.monotonic() - self._last_up < MARK_COMMIT_IDLE_S:
            return
        self._commit(context, region)

    def _undo_last(self, context):
        """Drop the most recent mark and the ink drawn for it.

        Prefers the half-drawn strokes: if the pen is mid-gesture, the thing
        the user means to take back is what is under it, not the mark they
        already finished.
        """
        if self._strokes:
            self._strokes = []
            self._current = None
            overlay.set_live_strokes([])
            overlay.tag_redraw()
            return

        if mark_store.remove_last(context.scene):
            overlay.pop_settled()
            self.report({"INFO"}, "Mark removed")
        overlay.tag_redraw()

    def _commit_pending(self, context):
        region = self._region(context)
        if region is not None and self._strokes and self._current is None:
            self._commit(context, region)

    def _commit(self, context, region):
        """Read the strokes as one mark, resolve it, and store it."""
        strokes = self._strokes
        self._strokes = []
        self._current = None
        overlay.set_live_strokes([])

        reading = gesture.classify(strokes, scale=_ui_scale())
        if reading is None:
            overlay.tag_redraw()
            return

        if mark_store.count(context.scene, drafts_only=True) >= MAX_MARKS_PER_TURN:
            self.report({"WARNING"},
                        f"Only {MAX_MARKS_PER_TURN} marks per message")
            overlay.tag_redraw()
            return

        rv3d = self._rv3d(context)
        serial = mark_store.next_serial(context.scene)

        wm = context.window_manager
        wm.mixar_mark_busy = True
        try:
            resolved = None
            if rv3d is not None:
                resolved = resolve.resolve_mark(
                    context, region, rv3d, reading, serial
                )
            width, height = self._region_size
            stored = mark_store.add_mark(
                context.scene, serial, self._view_name, self._view_data,
                reading, width, height, resolved,
            )
        except Exception as exc:  # noqa: BLE001 — a bad mark is not a bad session
            logger.warning("Scribble mark: could not commit mark %d: %s",
                           serial, exc, exc_info=True)
            stored = None
        finally:
            wm.mixar_mark_busy = False

        if stored is not None:
            self._view_used = True
            overlay.push_settled(strokes)
            self.report({"INFO"}, _commit_message(resolved))
        overlay.tag_redraw()

    # -- context ---------------------------------------------------------

    def _region(self, context):
        """Re-find the frozen region by pointer, or None if it is gone.

        Re-found rather than held: a stored RNA reference outlives the area
        it points at when the user splits or closes an editor, and touching
        it then is a crash rather than an error.
        """
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.as_pointer() != self._area_ptr:
                    continue
                for region in area.regions:
                    if region.as_pointer() == self._region_ptr:
                        return region
        return None

    def _rv3d(self, context):
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.as_pointer() == self._area_ptr:
                    space = area.spaces.active
                    return getattr(space, "region_3d", None)
        return None

    def _disarm(self, context):
        try:
            context.window_manager.mixar_mark_armed = False
        except Exception:  # noqa: BLE001
            pass

    def _finish(self, context):
        global _running
        # A freeze that committed no mark owns a camera nothing references.
        # Left behind, every arm/disarm cycle adds one to the .blend.
        if self._view_name and not self._view_used:
            view_bake.release(self._view_name)
            self._view_name = ""
        if self._timer is not None:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except Exception:  # noqa: BLE001
                pass
            self._timer = None
        overlay.remove()
        overlay.tag_redraw()
        _running = False


# =============================================================================
# Helpers
# =============================================================================

def _ui_scale():
    try:
        return float(bpy.context.preferences.system.ui_scale)
    except Exception:  # noqa: BLE001
        return 1.0


def _point_in_region(region, x, y):
    return (region.x <= x < region.x + region.width
            and region.y <= y < region.y + region.height)


def _find_view3d(context):
    """``(window, area, region)`` of the 3D viewport to freeze, or three Nones.

    The WINDOW is returned, not just the area, and every caller needs it. The
    Agent Bubble is its own ``wmWindow`` holding a single AGENT_BUBBLE area,
    so arming from the bubble's header finds a viewport in a DIFFERENT window
    — and Blender binds a modal handler to ``CTX_wm_window(C)`` and dispatches
    each window's events only against that window's own handlers. Registered
    on the wrong window the modal receives nothing from the viewport it froze:
    no stroke is captured, Esc over the viewport does nothing, and the freeze
    blocks no input at all. Worse, ``event.mouse_x/y`` would then be relative
    to the bubble while ``region.x/y`` are relative to the main window, so
    bubble-local positions land "inside" the viewport rect and record phantom
    strokes.
    """
    best = (None, None, None, 0)
    windows = [context.window] + [
        w for w in context.window_manager.windows if w is not context.window
    ]
    for window in windows:
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            for region in area.regions:
                if region.type != "WINDOW":
                    continue
                size = region.width * region.height
                if size > best[3]:
                    best = (window, area, region, size)
        if best[0] is not None:
            break
    return best[0], best[1], best[2]


def _commit_message(resolved):
    if not resolved or not resolved.get("hit"):
        return "Mark added — nothing under it"
    objects = resolved.get("objects") or []
    if not objects:
        return "Mark added"
    name = objects[0].get("name")
    if objects[0].get("vertex_group"):
        return f"Mark added on {name} (part of it)"
    return f"Mark added on {name}"


classes = (MIXAR_OT_scribble_mark_draw,)
