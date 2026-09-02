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

Above the marks, the freeze's ink as a whole is READ as either pointing or a
sketch (``core/sketch.py``); the hint pill says which, and Tab flips it. The
grouping is the resolution unit, not the meaning: a road with cars and trees
is one drawing however many pauses it took.

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
    INTENT_SKETCH,
    MARK_COMMIT_IDLE_S,
    MARK_TIMER_STEP_S,
    MAX_MARKS_PER_TURN,
    MAX_POINTS_PER_STROKE,
    MAX_STROKES_PER_MARK,
    MIN_SAMPLE_DIST_PX,
)
from mixar.modules.scribble_mark.core import (
    gesture,
    marks as mark_store,
    overlay,
    resolve,
    scribble_mode,
)
from mixar.modules.scribble_mark.core.freeze_session import (
    FreezeSession,
    find_view3d,
    resolve as resolve_context,
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
    _session = None
    #: True when the chat handwriting canvas was up as this freeze started —
    #: the two halves of Scribble then leave together (see scribble_mode).
    _ink_linked = False

    # -- lifecycle -------------------------------------------------------

    def invoke(self, context, event):
        global _running
        if _running:
            return {"CANCELLED"}

        window, area, region = find_view3d(context)
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

        self._session = FreezeSession()
        frame = self._session.take(context, window, area, region)
        if frame is None:
            # Refusing to arm is deliberate: with nothing frozen the user
            # would be drawing on a live viewport that can move under them,
            # and every mark would describe a view that no longer exists.
            self.report({"ERROR"}, "Could not freeze the viewport")
            return {"CANCELLED"}

        self._area_ptr = area.as_pointer()
        self._region_ptr = region.as_pointer()
        self._strokes = []
        self._current = None
        self._last_up = 0.0

        overlay.reset()
        overlay.set_target(self._area_ptr, self._region_ptr)
        overlay.install()
        context.window_manager.mixar_mark_armed = True

        wm = context.window_manager
        # The toggle raises the chat canvas BEFORE starting this modal, so
        # "is it up right now" is exactly "are we one mode with it".
        self._ink_linked = scribble_mode.ink_open(wm)
        # Bound to the window that OWNS the frozen viewport, not to whichever
        # window the button was clicked in — see freeze_session.find_view3d.
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
            if not self._refreeze_if_resized(context, region):
                self._disarm(context)
                self._finish(context)
                return {"FINISHED"}
            # The chat half closed under us — Esc or the close X over the
            # chat canvas are C++ paths this modal never sees. One mode, one
            # exit: the freeze follows it down.
            if self._ink_linked and not scribble_mode.ink_open(wm):
                self._commit_pending(context)
                self._disarm(context)
                self._finish(context)
                return {"FINISHED"}
            self._maybe_commit(context, region)
            # PASS_THROUGH, not RUNNING_MODAL. A window-level modal that
            # swallows every TIMER starves every other timer in the window,
            # and the chat canvas's idle-commit timer is one of them: with a
            # docked chat in this window, handwriting would never convert
            # while the viewport was frozen.
            return {"PASS_THROUGH"}

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

        # Flip how the ink is read. The reading is on screen in the pill;
        # this is the way to disagree with it without leaving the freeze.
        if event.type == "TAB" and event.value == "PRESS":
            self._commit_pending(context)
            self._flip_reading(context)
            return {"RUNNING_MODAL"}

        inside = _point_in_region(region, event.mouse_x, event.mouse_y)
        if not inside:
            # Outside the frozen viewport the app is entirely normal — the
            # chat, the sidebar and every other editor keep working, which is
            # how the user types the prompt that goes with their marks.
            return {"PASS_THROUGH"}

        point = (float(event.mouse_x - region.x), float(event.mouse_y - region.y))

        if event.type == "LEFTMOUSE":
            if event.value == "PRESS":
                self._begin_stroke(context, region, point)
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

    def _begin_stroke(self, context, region, point):
        if len(self._strokes) >= MAX_STROKES_PER_MARK:
            # Commit the group and start another rather than drop ink: a
            # sketch drawn without pausing must not lose its later strokes.
            self._commit(context, region)
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
        mark_store.refresh_reading(context.scene, context.window_manager)
        overlay.tag_redraw()

    def _flip_reading(self, context):
        wm = context.window_manager
        current = mark_store.refresh_reading(context.scene, wm)
        # Setting the property re-reads the drafts and repaints (its update
        # callback), so the pill changes under the user's eyes.
        if current == INTENT_SKETCH:
            wm.mixar_mark_intent = "POINT"
            self.report({"INFO"}, "Reading the ink as separate marks")
        else:
            wm.mixar_mark_intent = "SKETCH"
            self.report({"INFO"}, "Reading the ink as one sketch")

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
                    context, region, rv3d, reading, serial, strokes=strokes
                )
            width, height = self._session.region_size
            stored = mark_store.add_mark(
                context.scene, serial, self._session.view_name,
                self._session.view_data,
                reading, width, height, resolved, strokes=strokes,
            )
        except Exception as exc:  # noqa: BLE001 — a bad mark is not a bad session
            logger.warning("Scribble mark: could not commit mark %d: %s",
                           serial, exc, exc_info=True)
            stored = None
        finally:
            wm.mixar_mark_busy = False

        if stored is not None:
            self._session.view_used = True
            overlay.push_settled(strokes)
            self.report({"INFO"}, _commit_message(resolved))
        mark_store.refresh_reading(context.scene, wm)
        overlay.tag_redraw()

    # -- context ---------------------------------------------------------

    def _refreeze_if_resized(self, context, region):
        """Take a new freeze when the region no longer matches the still.

        Neither size is right once they diverge, so the old freeze is not
        patched up — it is replaced, and marks already committed keep the view
        they were drawn on.
        """
        if self._session.matches(region):
            return True
        self._commit_pending(context)
        window, area, _region = resolve_context(
            context, self._area_ptr, self._region_ptr
        )
        if window is None or area is None:
            return False
        if self._session.take(context, window, area, region) is None:
            self.report({"WARNING"}, "Viewport resized — could not re-freeze")
            return False
        self.report({"INFO"}, "Viewport resized — frame re-captured")
        return True

    def _region(self, context):
        """Re-find the frozen region by pointer, or None if it is gone.

        Re-found rather than held: a stored RNA reference outlives the area
        it points at when the user splits or closes an editor, and touching
        it then is a crash rather than an error.
        """
        return resolve_context(context, self._area_ptr, self._region_ptr)[2]

    def _rv3d(self, context):
        _window, area, _region = resolve_context(
            context, self._area_ptr, self._region_ptr
        )
        if area is None:
            return None
        return getattr(area.spaces.active, "region_3d", None)

    def _disarm(self, context):
        try:
            context.window_manager.mixar_mark_armed = False
        except Exception:  # noqa: BLE001
            pass

    def _finish(self, context):
        global _running
        # A freeze that committed no mark owns a still and a camera nothing
        # references. Left behind, every arm/disarm cycle adds both to the
        # .blend.
        if self._session is not None:
            self._session.release_if_unused()
        if self._timer is not None:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except Exception:  # noqa: BLE001
                pass
            self._timer = None
        overlay.remove()
        overlay.tag_redraw()
        # The chat half leaves with the viewport half, whatever ended the
        # freeze — Esc over the viewport, a vanished region, or the send.
        # The canvas converts what is still on it before it lowers; a
        # canvas that is already down makes this a no-op.
        scribble_mode.close_ink(context.window_manager)
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
