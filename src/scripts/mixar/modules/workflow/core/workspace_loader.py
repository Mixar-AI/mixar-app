# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Workspace activation helpers for the dual-mode UI system."""

from __future__ import annotations

import bpy

from mixar.config.config import UI_MODE_AI, UI_MODE_PRO
from mixar.config.logging_config import get_logger

from ..constants import (
    AI_WORKSPACE_NAME,
    BASIC_WORKSPACE_NAME,
    PRO_DEFAULT_WORKSPACE_NAME,
)

_logger = get_logger(__name__)


def activate_workspace(name: str) -> bool:
    """Activate an existing workspace by name. Returns True if successful.

    Always reassigns window.workspace, even when it already points at the
    target. Callers like the splash mode picker rely on the resulting screen
    rebuild to dismiss the popup; the startup timer (which would otherwise
    kill the splash too early) guards against a redundant call before
    invoking us.
    """
    workspace = bpy.data.workspaces.get(name)
    if workspace is None:
        return False
    window = bpy.context.window
    if window is None:
        return False
    window.workspace = workspace
    return True


def _pick_basic_template() -> "bpy.types.WorkSpace | None":
    """Pick a usable workspace to seed Zen Mode from.

    Preference order: the legacy "AI Mode" tab (matches the layout users
    expect), then the currently active workspace, then any workspace at all.
    Returns None only when bpy.data.workspaces is empty.
    """
    template = bpy.data.workspaces.get(AI_WORKSPACE_NAME)
    if template is not None:
        return template
    window = bpy.context.window
    if window is not None and window.workspace is not None:
        return window.workspace
    return next(iter(bpy.data.workspaces), None)


def ensure_basic_workspace() -> bool:
    """Materialize the Zen Mode workspace if missing. Returns True if it
    exists (or was just created) afterwards.

    Duplicates a template workspace via bpy.ops.workspace.duplicate so the
    new workspace is layout-independent — edits to it won't bleed into the
    AI Mode tab in Engine mode, and deleting AI Mode in Engine mode won't break
    Zen Mode. The duplicate operator switches the active workspace to the
    new one as a side effect; we restore the previous workspace afterwards
    so callers see the same active workspace as before.

    Called lazily from MIXAR_OT_set_ui_mode_ai (not from the startup timer)
    because the workspace bouncing required by the duplicate operator
    would tear down the startup splash popup.
    """
    if bpy.data.workspaces.get(BASIC_WORKSPACE_NAME) is not None:
        return True

    window = bpy.context.window
    if window is None:
        return False

    template = _pick_basic_template()
    if template is None:
        _logger.warning("No workspace available to seed Zen Mode from")
        return False

    original = window.workspace
    before = {ws.name for ws in bpy.data.workspaces}

    if window.workspace != template:
        window.workspace = template

    try:
        bpy.ops.workspace.duplicate()
    except Exception as e:  # noqa: BLE001 — operator can fail in odd contexts
        _logger.warning("workspace.duplicate failed: %s", e)
        if original is not None and bpy.data.workspaces.get(original.name):
            window.workspace = original
        return False

    new_workspaces = [
        ws for ws in bpy.data.workspaces if ws.name not in before
    ]
    if not new_workspaces:
        _logger.warning("workspace.duplicate produced no new workspace")
        if original is not None and bpy.data.workspaces.get(original.name):
            window.workspace = original
        return False

    new_workspaces[0].name = BASIC_WORKSPACE_NAME

    if original is not None and bpy.data.workspaces.get(original.name):
        window.workspace = original

    _logger.info(
        "Created Zen Mode workspace from template %r", template.name
    )
    return True


def activate_basic_workspace() -> bool:
    """Activate the Zen Mode workspace, creating it if missing."""
    if not ensure_basic_workspace():
        return False
    return activate_workspace(BASIC_WORKSPACE_NAME)


def activate_pro_default_workspace() -> bool:
    """Activate a Pro-mode workspace, preferring "Modeling".

    Falls back to any workspace that isn't Zen Mode if Modeling has been
    deleted. Without this fallback, flipping to Engine mode after the user
    deletes Modeling would silently fail and leave them on the Zen Mode
    workspace with Pro chrome — an inconsistent state.
    """
    if activate_workspace(PRO_DEFAULT_WORKSPACE_NAME):
        return True
    fallback = next(
        (
            ws
            for ws in bpy.data.workspaces
            if ws.name != BASIC_WORKSPACE_NAME
        ),
        None,
    )
    if fallback is None:
        return False
    return activate_workspace(fallback.name)


def configure_basic_workspace_chrome() -> None:
    """Force Zen Mode workspace's 3D viewports to keep all chrome regions
    visible at runtime.

    Counter-intuitive but deliberate: hiding regions via show_region_*
    creates Blender's collapsed-region expand arrow, which we do not want.
    Instead, view3d_header_filter empties the header/tool-header/T-panel
    contents while the regions stay visible. This function ensures the
    regions are visible to begin with, in case the workspace was saved
    with regions hidden from a previous session.

    Walks bpy.data.workspaces directly (not the active window's screen) so
    the configuration is independent of any in-flight workspace switch.
    Only the Zen Mode workspace viewports are touched.
    """
    for workspace in bpy.data.workspaces:
        if workspace.name != BASIC_WORKSPACE_NAME:
            continue
        for screen in workspace.screens:
            for area in screen.areas:
                if area.type != 'VIEW_3D':
                    continue
                for space in area.spaces:
                    if space.type != 'VIEW_3D':
                        continue
                    # Idempotent: only write when a flag is actually off.
                    # Unconditional writes trigger redraws that close the
                    # startup splash popup.
                    if not space.show_region_toolbar:
                        space.show_region_toolbar = True
                    if not space.show_region_header:
                        space.show_region_header = True
                    if not space.show_region_tool_header:
                        space.show_region_tool_header = True


def apply_ui_mode(mode: str) -> bool:
    """Activate the workspace appropriate for the given UI mode.

    Zen mode materializes (if needed) and activates the dedicated Basic
    Mode workspace; Engine mode lands on Modeling. Header/tool-header content
    is filtered by view3d_header_filter — that runs on every redraw and
    reads context.workspace, so it stays correct across mode flips without
    any explicit call here.

    Returns True if the target workspace was activated.
    """
    if mode == UI_MODE_AI:
        return activate_basic_workspace()
    if mode == UI_MODE_PRO:
        return activate_pro_default_workspace()
    _logger.warning("Unknown ui_mode %r; not activating any workspace", mode)
    return False
