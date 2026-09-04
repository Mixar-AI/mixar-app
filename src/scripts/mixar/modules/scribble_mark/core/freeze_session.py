# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""One freeze: the still, the camera baked from it, and the size they share.

Split out of the modal operator because it is not UI — it is the bookkeeping
that keeps a mark's three pieces consistent with each other:

* the **still** the user draws on,
* the **camera** a lane renders from to see that same frame,
* the **region size** every normalized coordinate is relative to.

They must be taken together, and a mark is only meaningful against the set it
was drawn on. When the region resizes they stop agreeing — a resized viewport
shows a different extent of the scene, so a raycast through the live region no
longer hits what the old still depicts — and neither size can rescue it:
normalizing against the arm-time size mismaps the mark onto the stretched
still the user actually drew on, while normalizing against the live size pairs
it with a raycast through a view the still no longer shows.

So a resize takes a NEW freeze. Marks already committed keep the view they
were drawn on, which is exactly what the payload's ``views`` map is for.

Finding the viewport lives here too, and returns the owning **window**. The
Agent Bubble is its own ``wmWindow``, so the button that arms this is often
clicked in a window that holds no viewport at all — and Blender binds a modal
handler to ``CTX_wm_window(C)`` and dispatches each window's events only
against that window's own handlers.
"""

from __future__ import annotations

from mixar.config.logging_config import get_logger

from . import freeze, marks as mark_store, overlay, view_bake

logger = get_logger(__name__)


class FreezeSession:
    """The live freeze. Mutated in place by the modal operator."""

    def __init__(self):
        self.frame_name = ""
        self.view_name = ""
        self.view_data = None
        self.region_size = (0, 0)
        #: True once a committed mark references this freeze's view. Until
        #: then the still and camera are unreferenced and can be released.
        self.view_used = False

    # -- taking a freeze -------------------------------------------------

    def take(self, context, window, area, region):
        """Capture the still and bake the camera. Returns the frame name."""
        serial = mark_store.next_serial(context.scene)
        frame = freeze.capture_region_still(
            context, window, area, region, freeze.frame_name(serial)
        )
        if frame is None:
            return None

        # Release the outgoing freeze only when nothing committed still needs
        # it — a mark drawn before a resize is still going to be sent, and its
        # still and camera must survive until then.
        if not self.view_used:
            if self.frame_name and self.frame_name != frame:
                freeze.release(self.frame_name)
            if self.view_name:
                view_bake.release(self.view_name)

        self.view_name, self.view_data = view_bake.bake_view(
            context, area, region, serial
        )
        self.view_used = False
        self.frame_name = frame
        self.region_size = (region.width, region.height)
        context.scene.mixar_mark_frame_name = frame
        overlay.reset_ink()
        return frame

    def matches(self, region):
        """Whether *region* is still the size this freeze was taken at."""
        return (region.width, region.height) == tuple(self.region_size)

    def release_if_unused(self):
        """Give back a freeze no committed mark references."""
        if self.view_used:
            return
        if self.view_name:
            view_bake.release(self.view_name)
            self.view_name = ""
        if self.frame_name:
            freeze.release(self.frame_name)
            self.frame_name = ""


# =============================================================================
# Finding the viewport
# =============================================================================

def find_view3d(context):
    """``(window, area, region)`` of the 3D viewport to freeze, or three Nones.

    The WINDOW is returned, not just the area, and every caller needs it. The
    Agent Bubble is its own ``wmWindow`` holding a single AGENT_BUBBLE area,
    so arming from the bubble's header finds a viewport in a DIFFERENT window
    — and Blender binds a modal handler to ``CTX_wm_window(C)`` and dispatches
    each window's events only against that window's own handlers. Registered
    on the wrong window the modal receives nothing from the viewport it froze:
    no stroke captured, Esc over the viewport dead, and the freeze blocking no
    input at all. Worse, ``event.mouse_x/y`` would then be relative to the
    bubble while ``region.x/y`` are relative to the main window, so
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


def resolve(context, area_ptr, region_ptr):
    """``(window, area, region)`` for stored pointers, or three Nones.

    Re-found by pointer on every use rather than held: a stored RNA reference
    outlives the area it points at when the user splits or closes an editor,
    and touching it then is a crash rather than an error.
    """
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.as_pointer() != area_ptr:
                continue
            for region in area.regions:
                if region.as_pointer() == region_ptr:
                    return window, area, region
            return window, area, None
    return None, None, None
