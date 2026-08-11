# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Tour Driver

Runs the side effects of stepping into a tour state. With the
custom GPU card replacing ``invoke_props_dialog``, the driver's
work is small:

* Switch the moodboard sidebar to the relevant category tab so the
  user can see the feature being described (the card itself sits
  beside the sidebar, not over it).
* For the three sidebar tool steps (Image Gen / Image to 3D /
  Retopology), force the matching panel open via the bl_idname-
  rename trick (see ``_force_panel_open_via_rename`` below).
* Invoke the single ``mixar.onboarding_card`` modal operator with
  the new ``step_id``. The card operator computes its own host area,
  position, and content from the step id.
"""

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.onboarding.constants import (
    CATEGORY_IMAGE_GEN,
    CATEGORY_IMAGE_TO_3D,
    CATEGORY_RETOPOLOGY,
    OP_CARD_MODAL,
    STEP_INFO_IMAGE_TO_3D,
    STEP_INFO_IMAGEGEN,
    STEP_INFO_MOODBOARD,
    STEP_INFO_RETOPOLOGY,
)
from mixar.modules.onboarding.core.steps import (
    KIND_MODAL,
    KIND_TERMINAL,
    get_step,
)
from mixar.modules.onboarding.core.overlay import overlay_renderer

logger = get_logger(__name__)

# Remaining topbar redraw ticks for the self-retrying timer.
_topbar_redraw_remaining = 0


# ---------------------------------------------------------------------------
# Per-step force-open table — the three sidebar tool panels that
# need to be expanded (not just selected) when their step is active.
# ---------------------------------------------------------------------------

_SIDEBAR_PANELS_TO_OPEN = (
    "MIXIE_PT_gen_imagegen",
    "MIXIE_PT_gen_image_to_3d",
    "MIXIE_PT_gen_retopology",
)


# Suffix appended to a panel's bl_idname when we re-register it
# without ``DEFAULT_CLOSED``. We need a *new* idname (not just a
# mutated bl_options) because Blender stores per-region collapse
# state on the Panel instance and matches existing instances back
# to a re-registered class by bl_idname (see
# ``UI_panel_find_by_type`` in ``interface_panel.cc``). Reusing the
# original name causes Blender to find the orphan instance with
# its old ``PNL_CLOSED`` flag still set; renaming forces a fresh
# instance whose flag honours the cleared ``DEFAULT_CLOSED``.
_TOUR_OPEN_SUFFIX = "_tour_open"

# Track which panel classes we've already converted so this stays
# idempotent across re-entries to the tour.
_panels_forced_open: set = set()


# ---------------------------------------------------------------------------
# Public entry point — called from state.transition_to().
# ---------------------------------------------------------------------------

def apply_step(step_id: str, context=None) -> None:
    """Run the side effects associated with entering ``step_id``."""
    step = get_step(step_id)
    if step is None:
        logger.warning("Onboarding tour_driver: unknown step %r", step_id)
        overlay_renderer.tag_redraw_all()
        return

    if step.kind == KIND_TERMINAL:
        overlay_renderer.tag_redraw_all()
        return

    if step.kind != KIND_MODAL:
        logger.warning(
            "Onboarding tour_driver: step %s has unexpected kind %r",
            step.id, step.kind,
        )
        overlay_renderer.tag_redraw_all()
        return

    # Pre-flight: the FIRST time the user reaches a step that touches
    # the moodboard sidebar, force-open all three sidebar panels.
    # Doing it here (one step before Image Gen, the first sidebar
    # step) means by the time the user clicks Next, the rename has
    # propagated and the panel renders fresh and open.
    if step_id in (
        STEP_INFO_MOODBOARD, STEP_INFO_IMAGEGEN,
        STEP_INFO_IMAGE_TO_3D, STEP_INFO_RETOPOLOGY,
    ):
        _ensure_sidebar_panels_open()

    # Sidebar tab switch — done synchronously so the right tab is
    # active by the time the card is rendered.
    if step.category:
        switch_sidebar_category(step.category)

    overlay_renderer.tag_redraw_all()
    _invoke_card(step_id)

    # Force the topbar to actually redraw on step transition.
    #
    # Blender's main loop is event-driven: ``tag_redraw`` only
    # flags ``region.do_draw`` and the flag is honoured during a
    # *draw cycle*, but draw cycles only run after an event. Global
    # areas like the TOPBAR don't auto-receive events (the cursor
    # is in the viewport when the step transitions), so the
    # flagged tag sits unhonoured until the user hovers the topbar.
    #
    # A single self-retrying timer fires up to 4 times at 0.15 s
    # intervals to cover any race with the modal invoke / workspace
    # settle.
    _arm_topbar_redraw(4)


def _iter_all_areas(window):
    """Yield every area in ``window``, including the global areas
    (topbar, statusbar) that aren't exposed through
    ``window.screen.areas``.

    Mixar's RNA overlay (see ``rna_wm_mixar.cc``) adds the
    ``Window.global_areas`` collection. If it's missing — older
    build, source not rebuilt — we silently fall back to just
    ``screen.areas`` so the rest of the code keeps working.
    """
    if window.screen is not None:
        for area in window.screen.areas:
            yield area
    globals_coll = getattr(window, "global_areas", None)
    if globals_coll is not None:
        for area in globals_coll:
            yield area


def _arm_topbar_redraw(count: int) -> None:
    """Schedule ``count`` topbar redraw ticks via a single timer.

    Note: rapid step transitions will reset the counter while the timer
    is mid-flight, which is fine — the last transition's count wins.
    """
    global _topbar_redraw_remaining
    _topbar_redraw_remaining = count
    if not bpy.app.timers.is_registered(_force_topbar_redraw):
        bpy.app.timers.register(_force_topbar_redraw, first_interval=0.0)


def _force_topbar_redraw():
    """Force the topbar to repaint NOW.

    The topbar is a *global area*: it lives in ``win->global_areas``,
    NOT in ``screen->areabase``, so default Python iteration
    (``window.screen.areas``) doesn't include it. Mixar's RNA
    overlay adds ``Window.global_areas`` to fix this — see
    ``_iter_all_areas``.

    With the global areas now visible, we tag them for redraw and
    also fire the explicit redraw helpers (workspace.update_tag,
    wm.redraw_timer) so the next draw cycle picks up the tag and
    repaints the topbar — making the highlight appear on step
    entry instead of waiting for the cursor to hover.
    """
    from mixar.modules.onboarding.core import state
    current = state.get_step_id()
    logger.debug(
        "Onboarding _force_topbar_redraw: fire (current step=%s)",
        current,
    )

    # 1. Tag every TOPBAR area + region for redraw — now using
    # the Mixar-exposed ``Window.global_areas`` so the topbar is
    # actually found.
    tagged = 0
    try:
        windows = bpy.data.window_managers[0].windows
        for window in windows:
            for area in _iter_all_areas(window):
                if area.type != "TOPBAR":
                    continue
                try:
                    area.tag_redraw()
                    tagged += 1
                except Exception:
                    pass
                for region in area.regions:
                    try:
                        region.tag_redraw()
                    except Exception:
                        pass
    except Exception as exc:
        logger.debug("Onboarding topbar tag_redraw failed: %s", exc)
    logger.debug(
        "Onboarding _force_topbar_redraw: tagged %d topbar areas",
        tagged,
    )

    # 2. Workspace update_tag → NC_WORKSPACE notifier (topbar
    # header listener explicitly responds to this category).
    try:
        ws = bpy.context.workspace
        if ws is not None:
            ws.update_tag()
            logger.debug(
                "Onboarding _force_topbar_redraw: workspace.update_tag OK",
            )
    except Exception as exc:
        logger.debug(
            "Onboarding _force_topbar_redraw: update_tag failed: %s", exc,
        )

    # 3. Synthetic MOUSEMOVE event — wakes Blender's event loop
    # and triggers a draw cycle without actually moving the
    # cursor. This is the most reliable way to get the topbar
    # to repaint outside of real user input, since the redraw
    # gate is event-driven for global areas.
    try:
        window = bpy.context.window
        if window is not None:
            window.event_simulate(type='MOUSEMOVE', value='NOTHING')
            logger.debug(
                "Onboarding _force_topbar_redraw: event_simulate OK",
            )
    except Exception as exc:
        logger.debug(
            "Onboarding _force_topbar_redraw: event_simulate failed: %s",
            exc,
        )

    # 4. Final hammer — wm.redraw_timer forces wm_draw_update.
    try:
        result = bpy.ops.wm.redraw_timer(
            type='DRAW_WIN_SWAP', iterations=1,
        )
        logger.debug(
            "Onboarding _force_topbar_redraw: redraw_timer returned %s",
            result,
        )
    except Exception as exc:
        logger.debug(
            "Onboarding _force_topbar_redraw: redraw_timer failed: %s",
            exc,
        )

    global _topbar_redraw_remaining
    _topbar_redraw_remaining -= 1
    if _topbar_redraw_remaining > 0:
        return 0.15
    return None


def _ensure_sidebar_panels_open() -> None:
    """Force-open every sidebar tool panel that's still collapsed
    by re-registering it under a fresh bl_idname (see comment on
    ``_TOUR_OPEN_SUFFIX``).

    Idempotent: each panel is only converted once per session.
    """
    for cls_name in _SIDEBAR_PANELS_TO_OPEN:
        if cls_name in _panels_forced_open:
            continue
        if _force_panel_open_via_rename(cls_name):
            _panels_forced_open.add(cls_name)


def _force_panel_open_via_rename(original_cls_name: str) -> bool:
    """Re-register the panel with a *new* bl_idname so Blender
    can't reuse the old (collapsed) Panel instance.

    Returns True if the panel was successfully re-registered, False
    if it didn't need conversion (already open) or couldn't be
    found / mutated.
    """
    cls = getattr(bpy.types, original_cls_name, None)
    if cls is None:
        logger.debug(
            "Onboarding force-open: %s not registered yet, skipping",
            original_cls_name,
        )
        return False

    current_options = set(getattr(cls, "bl_options", set()) or set())
    if "DEFAULT_CLOSED" not in current_options:
        # Already opens by default — no work needed.
        return False

    new_idname = original_cls_name + _TOUR_OPEN_SUFFIX

    try:
        bpy.utils.unregister_class(cls)
    except RuntimeError as exc:
        logger.debug(
            "Onboarding force-open: unregister %s failed: %s",
            original_cls_name, exc,
        )
        return False

    cls.bl_options = current_options - {"DEFAULT_CLOSED"}
    cls.bl_idname = new_idname

    try:
        bpy.utils.register_class(cls)
    except Exception as exc:
        logger.warning(
            "Onboarding force-open: re-register %s as %s failed: %s",
            original_cls_name, new_idname, exc,
        )
        return False

    logger.info(
        "Onboarding force-open: %s → %s (DEFAULT_CLOSED stripped)",
        original_cls_name, new_idname,
    )
    return True


def cancel_active_pollers() -> None:
    """Compatibility shim — the info flow has no pollers."""
    return


def redraw_moodboard_regions() -> None:
    """Compatibility shim used by state.reset() and a handful of
    historic call sites."""
    overlay_renderer.tag_redraw_all()


# ---------------------------------------------------------------------------
# Sidebar category switching.
# ---------------------------------------------------------------------------

# StepDef.category holds the offline fallback label; the live tab
# category is catalog-driven, so map the fallback back to its capability
# key and resolve the current label before switching.
_CATEGORY_CAPABILITIES = {
    CATEGORY_IMAGE_GEN: "image_gen",
    CATEGORY_IMAGE_TO_3D: "model_gen",
    CATEGORY_RETOPOLOGY: "retopology",
}


def _resolve_category(category_name: str) -> str:
    """Current catalog-driven category for a fallback label. Never raises."""
    capability_key = _CATEGORY_CAPABILITIES.get(category_name)
    if not capability_key:
        return category_name
    try:
        from mixar.modules.moodboard.ui.moodboard_sidebar_panels import (
            get_tab_category,
        )
        return get_tab_category(capability_key, category_name)
    except Exception:
        return category_name


def switch_sidebar_category(category_name: str) -> None:
    """Open the moodboard's N-panel sidebar (if collapsed) and
    switch its active category to ``category_name`` (a fallback label
    from ``constants``, resolved to the tab's current catalog label).

    Restricted to MIXIE areas so we don't barge into a regular 3D
    viewport whose sidebar the user had collapsed. Falls back to
    VIEW_3D only if no MIXIE area is currently visible (Mixar
    panels register there if MIXIE_SPACE_AVAILABLE is False).
    """
    category_name = _resolve_category(category_name)
    targets = _find_target_areas()
    for area in targets:
        _ensure_sidebar_open(area)
        ui_region = _find_ui_region(area)
        if ui_region is None:
            continue
        try:
            if hasattr(ui_region, "active_panel_category"):
                ui_region.active_panel_category = category_name
        except Exception as exc:
            logger.debug(
                "Onboarding: could not switch %s region to %r: %s",
                area.type, category_name, exc,
            )
        area.tag_redraw()


def _find_target_areas():
    mixie_areas = []
    view3d_areas = []
    try:
        windows = bpy.data.window_managers[0].windows
    except Exception:
        return []
    for window in windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type == "MIXIE":
                mixie_areas.append(area)
            elif area.type == "VIEW_3D":
                view3d_areas.append(area)
    return mixie_areas if mixie_areas else view3d_areas


def _ensure_sidebar_open(area) -> None:
    space = area.spaces.active
    if space is None:
        return
    if hasattr(space, "show_region_ui") and not space.show_region_ui:
        try:
            space.show_region_ui = True
        except Exception as exc:
            logger.debug("Onboarding: could not open sidebar: %s", exc)


def _find_ui_region(area):
    for region in area.regions:
        if region.type == "UI":
            return region
    return None


# ---------------------------------------------------------------------------
# Card invocation.
# ---------------------------------------------------------------------------

def _invoke_card(step_id: str) -> None:
    """Open the onboarding card modal for ``step_id``."""
    namespace, op_name = OP_CARD_MODAL.split(".", 1)
    try:
        op = getattr(getattr(bpy.ops, namespace), op_name)
    except AttributeError:
        logger.warning(
            "Onboarding card op %s not registered yet; step %s will not show.",
            OP_CARD_MODAL, step_id,
        )
        return
    try:
        op("INVOKE_DEFAULT", step_id=step_id)
    except Exception as exc:
        logger.warning(
            "Onboarding tour_driver: failed to invoke card for %s: %s",
            step_id, exc,
        )

