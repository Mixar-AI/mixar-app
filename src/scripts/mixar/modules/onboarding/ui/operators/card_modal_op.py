# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Onboarding Card Modal Operator

The single operator that drives every step of the onboarding tour.
Replaces the old ``invoke_props_dialog``-based welcome / info-step /
completion operators because Blender's built-in dialogs anchor at
the cursor with hidden offsets, which made precise centring and
proximity-positioning impossible.

How it works:

1. Driver invokes ``MIXAR_OT_onboarding_card`` with ``step_id``.
2. ``invoke()`` resolves the host area type for the step (MIXIE for
   every step in the new UI — the chat step's card sits in the
   MIXIE area because the Agent Bubble is a separate OS-level
   window), attaches a POST_PIXEL draw handler to that space type,
   computes the card layout, and adds itself to the modal handler
   stack.
3. ``modal()`` translates window-space mouse coords to region coords
   using the host region origin, runs hit-test, updates hover state,
   and dispatches Primary / Skip / Esc actions.
4. Cleanup removes the draw handler and asks the state machine to
   advance / skip / stay put.

The card's content (progress text, title, body, primary label) is
resolved per step via :func:`card_config.step_card_config`.
"""

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.onboarding.constants import (
    CARD_POS_NEAR_BUBBLE,
    CARD_POS_TOP_LEFT,
    CARD_POS_WINDOW_CENTER,
    CARD_SCALE_DEFAULT,
    OP_CARD_MODAL,
    STEP_ADVANCE_DEFER_SECONDS,
)
from mixar.modules.onboarding.core import card as card_pkg
from mixar.modules.onboarding.ui.operators.card_config import step_card_config
from mixar.modules.onboarding.ui.operators.host_resolver import (
    bubble_anchor_in_region,
    bubble_clearance_height,
    find_host,
    find_largest_window_region,
    fit_scale_for_region,
    reserved_space_for_position,
    space_type_for_area_type,
)

logger = get_logger(__name__)


# Session-scoped guard: True while a card modal is on screen. Multiple
# independent welcome triggers (auth-success hook + mode-pick nudge +
# dev-bypass fallback) can each try to open the welcome card; without this
# they stack two modals — one gets the click and advances, the other keeps
# drawing, leaving a "stuck" duplicate. The welcome operator checks this and
# skips when a card is already up. Transitions are safe: each step cleans up
# (clears this) before invoking the next card.
_card_active = False

# Monotonic token bumped by close_active_card(). Each card captures the
# current value in invoke(); its modal() self-terminates once the global
# has moved past it. This is how a mode-pick discards a card that fired
# behind the splash (bound to the old workspace's region) and replaces it
# with a fresh card in the newly chosen workspace — no orphaned modal.
_card_generation = 0
# The on-screen card's draw handle, so close_active_card() can stop it
# drawing IMMEDIATELY (before its modal next ticks).
_active_draw_handle = None
_active_space_cls = None


def is_card_active() -> bool:
    """True while an onboarding card modal is currently displayed."""
    return _card_active


def close_active_card() -> None:
    """Dismiss the current onboarding card immediately, if any.

    Removes its draw handler now and bumps the generation so the running
    modal self-terminates on its next event. Used by the splash mode-pick
    operators: a card pre-fired behind the splash is bound to the old
    workspace's region, so on a mode switch it must be closed and re-shown
    fresh in the chosen workspace.
    """
    global _card_generation, _active_draw_handle, _active_space_cls, _card_active
    _card_generation += 1
    if _active_draw_handle is not None and _active_space_cls is not None:
        try:
            _active_space_cls.draw_handler_remove(_active_draw_handle, "WINDOW")
        except Exception as exc:
            logger.debug("close_active_card: draw remove failed: %s", exc)
    _active_draw_handle = None
    _active_space_cls = None
    _card_active = False


# ---------------------------------------------------------------------------
# State machine helpers — defer the transition through a timer so the
# modal cleanly returns FINISHED before the next dialog opens.
# ---------------------------------------------------------------------------

def _advance_deferred():
    from mixar.modules.onboarding.core import state
    state.advance()
    return None


def _skip_deferred():
    from mixar.modules.onboarding.core import state
    state.skip_tour()
    return None


def _back_deferred():
    from mixar.modules.onboarding.core import state
    state.go_back()
    return None


# ---------------------------------------------------------------------------
# The modal operator.
# ---------------------------------------------------------------------------

class MIXAR_OT_onboarding_card(Operator):
    """Render and drive a single onboarding tour card.

    Spec:

    * Renders to the WINDOW region of the step's host area type
      (MIXIE for most steps, MIXIE_CHAT for the chat step).
    * Captures all mouse + key events while running so the user
      can't accidentally interact with the dim editor underneath
      until they make a choice (Next / Skip / Esc).
    """

    bl_idname = OP_CARD_MODAL
    bl_label = "Onboarding Card"
    bl_description = "Show the next onboarding card"
    bl_options = {"REGISTER", "INTERNAL"}

    step_id: StringProperty(default="")

    # Per-instance state — set in invoke, cleared in cancel/finish.
    _draw_handle = None
    _host_space_cls = None
    _host_region_id = None  # ARegion C-pointer for the *primary* host
    _host_region_origin = (0, 0)
    _window_size = (0, 0)
    _layout = None
    _hover = None
    _config = None
    _multi_handles = ()
    _generation = 0  # snapshot of _card_generation at invoke

    def invoke(self, context, event):
        self._config = step_card_config(self.step_id)
        if not self._config:
            logger.warning("Onboarding card: unknown step %r", self.step_id)
            return {"CANCELLED"}

        if self._config["position"] == CARD_POS_WINDOW_CENTER:
            window, area, region = find_largest_window_region()
            if window is None:
                logger.warning(
                    "Onboarding card: no WINDOW region available"
                )
                return {"CANCELLED"}
        else:
            host_area_type = self._config["host_area"]
            window, area, region = find_host(host_area_type)
            if window is None or area is None or region is None:
                logger.warning(
                    "Onboarding card: no host area found for %s",
                    host_area_type,
                )
                return {"CANCELLED"}

        from mixar.modules.onboarding.constants import (
            CARD_MIN_HEIGHT,
            CARD_WIDTH,
        )
        target_scale = self._config.get("scale", CARD_SCALE_DEFAULT)
        reserved_w, reserved_h = reserved_space_for_position(
            self._config["position"],
        )
        if self._config["position"] == CARD_POS_TOP_LEFT:
            # Top-left cards (welcome / completion) can collide with
            # the floating Agent Bubble window docked over the host
            # region's bottom-left — reserve vertical clearance so the
            # card scales down enough that its bottom clears the bubble.
            reserved_h = max(
                reserved_h,
                bubble_clearance_height((window.x, window.y), region),
            )
        self._config["scale"] = fit_scale_for_region(
            region, target_scale, CARD_WIDTH, CARD_MIN_HEIGHT,
            reserved_w=reserved_w, reserved_h=reserved_h,
        )

        space_cls = space_type_for_area_type(area.type)
        if space_cls is None or not hasattr(space_cls, "draw_handler_add"):
            space_cls = type(area.spaces.active)
            if space_cls is None or not hasattr(space_cls, "draw_handler_add"):
                logger.warning(
                    "Onboarding card: cannot attach draw handler to %s",
                    area.type,
                )
                return {"CANCELLED"}

        self._host_space_cls = space_cls
        self._host_region_id = region.as_pointer()
        self._host_region_origin = (region.x, region.y)
        self._window_size = (window.width, window.height)
        self._host_window_origin = (window.x, window.y)
        self._layout = self._build_layout(region.width, region.height)
        self._hover = None

        self._draw_handle = space_cls.draw_handler_add(
            self._draw_callback, (), "WINDOW", "POST_PIXEL",
        )
        self._multi_handles = ()

        if self._config["position"] == CARD_POS_WINDOW_CENTER:
            logger.info(
                "Onboarding welcome: window=%dx%d host=%s region=(%d,%d %dx%d) "
                "card-pos=(%d,%d) size=%dx%d",
                window.width, window.height, area.type,
                region.x, region.y, region.width, region.height,
                self._layout.x, self._layout.y,
                self._layout.w, self._layout.h,
            )

        area.tag_redraw()
        context.window_manager.modal_handler_add(self)
        global _card_active, _active_draw_handle, _active_space_cls
        self._generation = _card_generation
        _active_draw_handle = self._draw_handle
        _active_space_cls = self._host_space_cls
        _card_active = True
        return {"RUNNING_MODAL"}


    # -- drawing -----------------------------------------------------------

    def _build_layout(self, region_w: int, region_h: int):
        cfg = self._config
        win_w, win_h = self._window_size
        rx, ry = self._host_region_origin
        bubble_anchor = None
        if cfg["position"] == CARD_POS_NEAR_BUBBLE:
            bubble_anchor = bubble_anchor_in_region(
                self._host_window_origin, (rx, ry),
            )
        return card_pkg.compute_layout(
            title_text=cfg["title"],
            body_lines=cfg["body_lines"],
            primary_label=cfg["primary_label"],
            skip_label=cfg["skip_label"],
            pos_kind=cfg["position"],
            area_w=region_w,
            area_h=region_h,
            icon_id=cfg.get("icon_id", ""),
            dots_current=cfg.get("dots_current", 0),
            dots_total=cfg.get("dots_total", 0),
            skip_visible=cfg.get("skip_visible", True),
            scale=cfg.get("scale", CARD_SCALE_DEFAULT),
            window_w=win_w,
            window_h=win_h,
            region_x=rx,
            region_y=ry,
            bubble_anchor=bubble_anchor,
            back_visible=cfg.get("back_visible", False),
        )

    def _draw_callback(self):
        """Single-region POST_PIXEL draw — only fire on the host region."""
        try:
            region = bpy.context.region
            if region is None or region.as_pointer() != self._host_region_id:
                return
            self._layout = self._build_layout(region.width, region.height)
            card_pkg.draw_card(self._layout, self._hover)
            # Escape-hint on the dim film, below the card. Drawn here
            # (not in the card layout) so it never affects card size
            # or placement.
            card_pkg.draw_dismiss_hint(region.width, region.height)
        except Exception as exc:
            logger.warning(
                "Onboarding card draw failed: %s", exc, exc_info=True,
            )

    # -- modal -------------------------------------------------------------

    def modal(self, context, event):
        if self._layout is None:
            self._cleanup()
            return {"CANCELLED"}

        # A newer card (from a mode-pick) has superseded us — tear down so a
        # card pre-fired behind the splash doesn't linger in the modal stack
        # after the workspace changed.
        if self._generation != _card_generation:
            self._cleanup()
            return {"CANCELLED"}

        if event.type == "MOUSEMOVE":
            new_hover = self._hit_test_event(event)
            if new_hover != self._hover:
                self._hover = new_hover
                self._tag_host_redraw()
            return {"PASS_THROUGH"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            # While the splash is still on screen this click belongs to the
            # splash (the card can briefly render behind an idle-open popup) —
            # never treat it as an off-card dismiss, or the tour gets marked
            # 'seen' by a splash-directed click.
            try:
                from mixar.bootstrap import splash_menu
                if splash_menu.is_splash_visible():
                    return {"PASS_THROUGH"}
            except Exception:
                pass
            target = self._hit_test_event(event)
            if target == "primary":
                return self._on_primary(context)
            if target == "back":
                return self._on_back(context)
            if target == "skip":
                return self._on_skip(context)
            if target == "card":
                # Clicks on the card body itself do nothing (so users
                # don't dismiss the tour while reading) — swallow them.
                return {"RUNNING_MODAL"}
            # Click anywhere OUTSIDE the card dismisses the whole tour.
            # Previously this silently swallowed the click, which made
            # the dimmed screen feel frozen. Now an off-card click is
            # an explicit, immediate "skip" — the same path as the
            # Skip control — so the app is one click away from usable.
            return self._on_skip(context)

        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            return self._on_primary(context)

        if event.type == "ESC" and event.value == "PRESS":
            # Esc must go through the skip path, not just _cleanup():
            # the step highlight (green border) is gated on the tour's
            # step_id, so without transitioning to DONE it keeps
            # drawing after the card is gone.
            return self._on_skip(context)

        return {"PASS_THROUGH"}

    # -- event helpers -----------------------------------------------------

    def _hit_test_event(self, event):
        if self._layout is not None and self._layout.is_window_coords:
            return card_pkg.hit_test(
                self._layout, event.mouse_x, event.mouse_y,
            )
        ox, oy = self._host_region_origin
        return card_pkg.hit_test(
            self._layout,
            event.mouse_x - ox,
            event.mouse_y - oy,
        )

    def _tag_host_redraw(self):
        try:
            windows = bpy.data.window_managers[0].windows
            for window in windows:
                if window.screen is None:
                    continue
                if self._multi_handles:
                    for area in window.screen.areas:
                        area.tag_redraw()
                    return
                for area in window.screen.areas:
                    for region in area.regions:
                        if region.as_pointer() == self._host_region_id:
                            area.tag_redraw()
                            return
        except Exception:
            pass

    # -- actions -----------------------------------------------------------

    def _on_primary(self, context):
        self._cleanup()
        bpy.app.timers.register(
            _advance_deferred, first_interval=STEP_ADVANCE_DEFER_SECONDS,
        )
        return {"FINISHED"}

    def _on_back(self, context):
        self._cleanup()
        bpy.app.timers.register(
            _back_deferred, first_interval=STEP_ADVANCE_DEFER_SECONDS,
        )
        return {"FINISHED"}

    def _on_skip(self, context):
        self._cleanup()
        bpy.app.timers.register(
            _skip_deferred, first_interval=STEP_ADVANCE_DEFER_SECONDS,
        )
        return {"FINISHED"}

    # -- cleanup -----------------------------------------------------------

    def _cleanup(self):
        # Clear the module-level active refs only if they still point at THIS
        # card — a newer card (mode-pick replacement) may already own them.
        global _card_active, _active_draw_handle, _active_space_cls
        if _active_draw_handle is self._draw_handle:
            _active_draw_handle = None
            _active_space_cls = None
            _card_active = False
        if self._draw_handle is not None and self._host_space_cls is not None:
            try:
                self._host_space_cls.draw_handler_remove(
                    self._draw_handle, "WINDOW",
                )
            except Exception as exc:
                logger.debug(
                    "Onboarding card: draw handler remove failed: %s", exc,
                )
        self._draw_handle = None
        self._host_space_cls = None
        for cls, region_type, handle in self._multi_handles:
            try:
                cls.draw_handler_remove(handle, region_type)
            except Exception as exc:
                logger.debug(
                    "Onboarding card: multi-region remove failed: %s", exc,
                )
        self._multi_handles = ()
        try:
            windows = bpy.data.window_managers[0].windows
            for window in windows:
                if window.screen is None:
                    continue
                for area in window.screen.areas:
                    area.tag_redraw()
        except Exception:
            pass

    def cancel(self, context):
        self._cleanup()


classes = (MIXAR_OT_onboarding_card,)


def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)


def unregister():
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)
