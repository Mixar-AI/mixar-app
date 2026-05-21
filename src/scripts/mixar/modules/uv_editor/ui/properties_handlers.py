# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Properties Handlers

Module-level handler functions, timers, and depsgraph callbacks for the
Mixar UV Properties space. Extracted from properties.py to stay under 500 lines.
"""

import logging

import bpy

from .base.panels import TOOL_PANEL_BY_TOOL

# Track last known tool to detect changes
_last_active_tool = None
_refresh_timer_running = False
_LOGGER = logging.getLogger(__name__)

# msgbus owner — any unique object reference works as the "owner key"
# that we later use to clear our subscriptions on unregister.
_MSGBUS_OWNER = object()


# Recency counter for the "last-clicked panel goes on top" ordering.
# Each click (header tab or tool change) decrements this and writes the
# new value into the clicked panel's `bl_order`, so the most recently
# touched panel has the smallest `bl_order` and Blender draws it first
# (== topmost in the sidebar). Defaults sit at 0 (tool panels) or 100
# (header panels) so initial layout is sensible before any clicks.
_panel_click_counter = 0

# active_panel enum value → header panel idname.
_HEADER_PANEL_BY_ACTIVE = {
    'UV_SET': 'MIXAR_UV_PT_uv_set',
    'UNWRAP': 'MIXAR_UV_PT_unwrap',
    'TEXEL_DENSITY': 'MIXAR_UV_PT_texel_density',
    'PACK_ISLANDS': 'MIXAR_UV_PT_pack_islands',
    'IMAGE': 'MIXAR_UV_PT_image',
    'MATERIAL_SLOT': 'MIXAR_UV_PT_material_slot',
    'TRANSFORM': 'MIXAR_UV_PT_transform',  # C++ registered panel
    'EXPORT': 'MIXAR_UV_PT_export',
}

def _bump_panel_to_top(panel_idname):
    """Assign a fresh-and-smallest `bl_order` to the named panel so it
    sorts above any panel that hasn't been bumped more recently.

    Blender re-reads `bl_order` on each region draw, so writing to the
    class attribute live (instead of re-registering the PanelType) is
    enough to re-sort the sidebar — no rebuild required.
    """
    global _panel_click_counter
    _panel_click_counter -= 1
    panel_cls = getattr(bpy.types, panel_idname, None)
    if panel_cls is not None:
        try:
            panel_cls.bl_order = _panel_click_counter
        except Exception:
            # C++ PanelTypes sometimes refuse Python attribute writes
            # under older Blender builds.
            _LOGGER.debug("Unable to bump panel order for %s",
                          panel_idname, exc_info=True)


def _iter_all_window_areas_of_type(area_type):
    """Iterate through all areas of given type with their owning window/screen.

    This is crucial for supporting areas created manually during a session,
    not just those in the startup file.
    """
    for wm in bpy.data.window_managers:
        for window in wm.windows:
            screen = getattr(window, "screen", None)
            if screen is None:
                continue
            for area in screen.areas:
                if area.type == area_type:
                    yield window, screen, area


def _iter_all_areas_of_type(area_type):
    """Iterate through all areas of given type across ALL windows and screens."""
    for _window, _screen, area in _iter_all_window_areas_of_type(area_type):
        yield area


def _get_active_uv_tool(context):
    """Get the active tool idname from IMAGE_EDITOR in MIXAR_UV mode.

    Searches ALL IMAGE_EDITOR areas across all windows, not just current context.
    """
    from bl_ui.space_toolsystem_common import ToolSelectPanelHelper

    # Search all IMAGE_EDITOR areas globally
    for window, screen, area in _iter_all_window_areas_of_type('IMAGE_EDITOR'):
        sima = area.spaces.active
        if sima and sima.mode == 'MIXAR_UV':
            try:
                with context.temp_override(window=window,
                                           screen=screen,
                                           area=area):
                    tool = ToolSelectPanelHelper.tool_active_from_context(context)
            except (ReferenceError, TypeError):
                _LOGGER.debug("Skipping stale Mixar UV image editor area",
                              exc_info=True)
                continue
            if tool:
                return tool.idname
    return None


def _force_ui_refresh():
    """Force immediate UI refresh for all relevant areas across ALL windows.

    This ensures areas created manually during session are also refreshed,
    not just those from the startup file.
    """
    global _refresh_timer_running

    context = bpy.context
    if not context:
        _refresh_timer_running = False
        return None

    # Force workspace update notification - triggers poll() re-evaluation
    workspace = context.workspace
    if workspace:
        # Accessing tools property triggers Blender's internal message bus
        _ = workspace.tools

    # Redraw ALL IMAGE_EDITOR areas globally (sidebar panels are now in IMAGE_EDITOR)
    for area in _iter_all_areas_of_type('IMAGE_EDITOR'):
        area.tag_redraw()
        for region in area.regions:
            region.tag_redraw()

    _refresh_timer_running = False
    return None  # Timer should return None to run once


def _check_tool_and_refresh():
    """Timer function to check tool changes and refresh UI across ALL windows."""
    global _last_active_tool, _refresh_timer_running

    context = bpy.context
    if not context:
        _refresh_timer_running = False
        return None

    # Get current active tool (searches all windows globally)
    current_tool = _get_active_uv_tool(context)

    # Check if tool changed
    if current_tool != _last_active_tool:
        _last_active_tool = current_tool

        # Tool-based panels (Selection, Tools, Functions, Transform)
        # appear based on active tool.
        # Set active_panel to NONE to hide enum-based panels when tool-based panels are active
        wm = getattr(context, 'window_manager', None)
        if wm and hasattr(wm, 'mixar_uv_ui'):
            # Mutually exclusive selection across the 6 toolbar tools
            # and 7 header tabs: switching workspace tool brings the
            # selector back to "tool mode" by setting active_panel to
            # 'NONE'. Header-tab panels then hide, and the panel that
            # matches the freshly-active tool takes over the sidebar.
            #
            # Two special cases for `builtin.uv_panel_mode` (the 7th
            # toolbar anchor that represents "header mode"):
            #   1. Activated FROM `_active_panel_update` — don't reset
            #      active_panel, that would un-select the tab the
            #      artist just clicked.
            #   2. Clicked DIRECTLY from the toolbar — if no header
            #      tab was already selected, default to UV_SET so the
            #      sidebar shows something instead of the empty state.
            if current_tool == 'builtin.uv_panel_mode':
                if wm.mixar_uv_ui.active_panel == 'NONE':
                    wm.mixar_uv_ui.active_panel = 'UV_SET'
            elif (current_tool in TOOL_PANEL_BY_TOOL
                  and wm.mixar_uv_ui.active_panel != 'NONE'):
                wm.mixar_uv_ui.active_panel = 'NONE'

        # Refresh UI when tool changes to update panel visibility globally
        _force_ui_refresh()

    # Continue checking every 0.05 seconds for responsive updates
    return 0.05


@bpy.app.handlers.persistent
def _check_uv_sculpt_tool_change(scene, depsgraph):
    """Handler to detect UV tool changes and refresh tool-based panels.

    Uses global tool detection to handle areas across all windows.
    Resets `wm.mixar_uv_ui.active_panel` to 'NONE' on every tool
    change so the selection across all 13 options (6 toolbar tools +
    7 header tabs) stays mutually exclusive — only the panel that
    matches the freshly-active tool shows.
    """
    global _last_active_tool

    context = bpy.context
    if not context:
        return

    # Get current active tool (searches globally across all windows)
    current_tool = _get_active_uv_tool(context)

    if current_tool != _last_active_tool:
        _last_active_tool = current_tool

        # Deselect any header tab so the matching tool panel shows
        # in isolation. Special case: when the new tool is the
        # header-mode anchor (`builtin.uv_panel_mode`), keep an
        # existing header tab if there is one, or default to UV_SET
        # so something is shown.
        wm = getattr(context, 'window_manager', None)
        if wm is not None and hasattr(wm, 'mixar_uv_ui'):
            if current_tool == 'builtin.uv_panel_mode':
                if wm.mixar_uv_ui.active_panel == 'NONE':
                    wm.mixar_uv_ui.active_panel = 'UV_SET'
            elif (current_tool in TOOL_PANEL_BY_TOOL
                  and wm.mixar_uv_ui.active_panel != 'NONE'):
                wm.mixar_uv_ui.active_panel = 'NONE'

        # Schedule immediate refresh using timer
        global _refresh_timer_running
        if not _refresh_timer_running:
            _refresh_timer_running = True
            bpy.app.timers.register(_force_ui_refresh, first_interval=0.0)


def _active_panel_update(self, context):
    """Show IMAGE_EDITOR sidebar when panel selector changes."""
    # When any header tab is selected, switch the workspace tool to
    # `builtin.uv_panel_mode` so every real toolbar button (Selection /
    # Transform / Sculpt / Tool / Functions / Annotate) appears
    # un-depressed — giving the artist exactly ONE visually-selected
    # option across the 13 (6 toolbar + 7 header) at any time.
    if self.active_panel != 'NONE':
        for area in context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                sima = area.spaces.active
                if sima and sima.mode == 'MIXAR_UV':
                    with context.temp_override(area=area):
                        try:
                            bpy.ops.wm.tool_set_by_id(
                                name="builtin.uv_panel_mode")
                        except Exception:
                            _LOGGER.debug(
                                "Unable to switch to builtin.uv_panel_mode",
                                exc_info=True)
                    break

    # Ensure the IMAGE_EDITOR sidebar is visible
    for area in context.screen.areas:
        if area.type == 'IMAGE_EDITOR':
            sima = area.spaces.active
            if sima and sima.mode == 'MIXAR_UV':
                # Check if CHANNELS region is hidden, and show it
                for region in area.regions:
                    if region.type == 'CHANNELS':
                        if region.width <= 1:
                            with context.temp_override(area=area, region=region):
                                try:
                                    bpy.ops.screen.region_toggle(
                                        region_type='CHANNELS')
                                except Exception:
                                    _LOGGER.debug(
                                        "Unable to show Mixar UV sidebar",
                                        exc_info=True)
                        break
                break

    _force_ui_refresh()


# Track which (window, area) pairs have already been auto-expanded so
# we don't keep toggling the toolbar against the user's wishes. Store
# object references instead of Python id() integers so a later area
# cannot be skipped if CPython reuses an id after an editor is closed.
_TOOLS_AUTO_EXPANDED = []


def _tools_auto_expanded_contains(window, area):
    stale = []
    for index, (seen_window, seen_area) in enumerate(_TOOLS_AUTO_EXPANDED):
        try:
            if seen_window == window and seen_area == area:
                return True
        except ReferenceError:
            stale.append(index)
    for index in reversed(stale):
        del _TOOLS_AUTO_EXPANDED[index]
    return False


def _ensure_mixar_uv_tools_visible():
    """Auto-expand the TOOLS region for IMAGE_EDITOR areas in MIXAR_UV mode.

    Workspaces other than UV Editing (Modeling, Texturing, etc.) typically
    save their IMAGE_EDITOR area with the toolbar collapsed (region width
    near 0). When the user opens such an area in MIXAR_UV mode, the
    workspace tools (Selection / Transform / Sculpt / Tool / Functions /
    Annotate) become invisible until they press `T`. Detect that and
    toggle the TOOLS region back on once per (window, area). The user
    can still hide it manually afterwards — we only force-expand when
    we haven't already.
    """
    context = bpy.context
    if context is None:
        return None  # one-shot timer

    for wm in bpy.data.window_managers:
        for window in wm.windows:
            for area in window.screen.areas:
                if area.type != 'IMAGE_EDITOR':
                    continue
                sima = area.spaces.active
                if sima is None or sima.mode != 'MIXAR_UV':
                    continue
                if _tools_auto_expanded_contains(window, area):
                    continue
                for region in area.regions:
                    if region.type != 'TOOLS':
                        continue
                    # `width <= 1` is Blender's signature for a region
                    # that's been closed via region_toggle.
                    if region.width <= 1:
                        with context.temp_override(window=window,
                                                   area=area,
                                                   region=region):
                            try:
                                bpy.ops.screen.region_toggle(
                                    region_type='TOOLS')
                            except Exception:
                                _LOGGER.debug(
                                    "Unable to auto-expand Mixar UV tools",
                                    exc_info=True)
                    _TOOLS_AUTO_EXPANDED.append((window, area))
                    break
    return None  # one-shot timer


@bpy.app.handlers.persistent
def _tools_auto_expand_load_post(_dummy):
    """Re-run the auto-expand pass after every file load so the toolbar
    shows up in non-UV-Editing workspaces saved with it collapsed."""
    _TOOLS_AUTO_EXPANDED.clear()
    # Defer to the next event-loop tick so the screen is fully built.
    bpy.app.timers.register(_ensure_mixar_uv_tools_visible,
                             first_interval=0.1)


def _on_active_udim_tile_change():
    """Tag IMAGE_EDITOR WINDOW regions for redraw whenever any image's
    active UDIM tile index changes.

    Blender's UIList row click writes through to `Image.active_tile_index`
    (exposed in Python as `image.tiles.active_index`), but the property
    has no built-in update notifier — the viewport keeps drawing the
    previous "active tile" highlight until something else triggers a
    redraw. We subscribe to the property class-wide via msgbus and tag
    the WINDOW region ourselves.
    """
    for area in _iter_all_areas_of_type('IMAGE_EDITOR'):
        for region in area.regions:
            if region.type == 'WINDOW':
                region.tag_redraw()


@bpy.app.handlers.persistent
def _msgbus_load_post(_dummy):
    """msgbus subscriptions are cleared on every file load — re-register
    them so the UDIM tile redraw notifier survives File > Open.
    """
    _register_msgbus()


def _on_mixar_uv_mode_change():
    """When any IMAGE_EDITOR's `mode` changes (e.g. user switches to
    MIXAR_UV in a non-Layout workspace), schedule the toolbar auto-
    expand pass to run on the next event-loop tick so the area
    finishes settling before we toggle its TOOLS region."""
    bpy.app.timers.register(_ensure_mixar_uv_tools_visible,
                             first_interval=0.1)


def _on_workspace_tool_change():
    """Fires synchronously whenever any `WorkSpaceTool.idname` is
    written — i.e. immediately when the artist clicks a toolbar
    button (or `wm.tool_set_by_id` is called from anywhere). Runs the
    tool-change detection right away instead of waiting up to 50 ms
    for the polling timer, so the header tab visually deselects in
    the same redraw pass as the toolbar update.
    """
    _check_uv_sculpt_tool_change(None, None)


def _register_msgbus():
    """Subscribe to active-UDIM-tile changes for ALL Image instances,
    SpaceImageEditor mode changes (for the auto-expand-toolbar pass),
    and WorkSpaceTool.idname changes (so the header tabs deselect the
    instant a toolbar tool is clicked)."""
    bpy.msgbus.clear_by_owner(_MSGBUS_OWNER)
    bpy.msgbus.subscribe_rna(
        key=(bpy.types.UDIMTiles, "active_index"),
        owner=_MSGBUS_OWNER,
        args=(),
        notify=_on_active_udim_tile_change,
    )
    bpy.msgbus.subscribe_rna(
        key=(bpy.types.SpaceImageEditor, "mode"),
        owner=_MSGBUS_OWNER,
        args=(),
        notify=_on_mixar_uv_mode_change,
    )
    bpy.msgbus.subscribe_rna(
        key=(bpy.types.WorkSpaceTool, "idname"),
        owner=_MSGBUS_OWNER,
        args=(),
        notify=_on_workspace_tool_change,
    )


def _unregister_msgbus():
    bpy.msgbus.clear_by_owner(_MSGBUS_OWNER)


def register_handlers():
    """Register depsgraph handler, tool-check timer, and msgbus subs."""
    global _refresh_timer_running
    if _check_uv_sculpt_tool_change not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_check_uv_sculpt_tool_change)
    if _msgbus_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_msgbus_load_post)
    if _tools_auto_expand_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_tools_auto_expand_load_post)
    if not _refresh_timer_running:
        _refresh_timer_running = True
        bpy.app.timers.register(_check_tool_and_refresh, first_interval=0.05)
    _register_msgbus()
    # First run on register so the toolbar shows up at session start too.
    bpy.app.timers.register(_ensure_mixar_uv_tools_visible,
                             first_interval=0.5)


def unregister_handlers():
    """Unregister depsgraph handler, tool-check timer, and msgbus subs."""
    global _refresh_timer_running
    _unregister_msgbus()
    if _msgbus_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_msgbus_load_post)
    if _tools_auto_expand_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_tools_auto_expand_load_post)
    if _check_uv_sculpt_tool_change in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_check_uv_sculpt_tool_change)
    try:
        if bpy.app.timers.is_registered(_check_tool_and_refresh):
            bpy.app.timers.unregister(_check_tool_and_refresh)
    except Exception:
        _LOGGER.debug("Unable to unregister Mixar UV refresh timer",
                      exc_info=True)
    _refresh_timer_running = False
    _TOOLS_AUTO_EXPANDED.clear()
