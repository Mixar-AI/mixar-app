# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Reconcile temporary Scene World overrides with saved, undoable snapshots."""

from uuid import uuid4

import bpy
from bpy.app.handlers import persistent

from .zen_scene import sky_enabled


def _shadings():
    # Include inactive editors/workspaces: OFF may be clicked in another area.
    for screen in bpy.data.screens:
        for area in screen.areas:
            for space in area.spaces:
                if space.type == "VIEW_3D":
                    yield space.shading


def _owner(state):
    # Keep ID pointers on the Screen ID, whose properties Blender remaps.
    # View3DShading's system properties are saved but their ID links are not.
    owner = state.id_data.mixar_zen_sky_owners.get(state.key)
    return owner.scene if owner else None


def _restore(shading):
    state = shading.mixar_zen_sky
    if not state.applied:
        return
    # Undoing ON can remove its scene snapshot or restore an older cycle's
    # snapshot. Release the override that is actually applied to this UI.
    shading.use_scene_world = state.previous_preview
    shading.use_scene_world_render = state.previous_render
    state.applied = False


def _apply(shading, snapshot, *, force=False):
    state = shading.mixar_zen_sky
    state.previous_preview = snapshot.use_scene_world
    state.previous_render = snapshot.use_scene_world_render
    if force or not state.applied:
        shading.use_scene_world = True
        shading.use_scene_world_render = True
        state.applied = True


def set_sky_viewports(scene, enabled, screen, *, restart=False):
    """Capture each affected viewport once, restoring only owned overrides.

    The scene collection follows undo history; the viewport keeps its stable
    lookup key and the currently applied state across undo and file saves.
    """
    if restart or not enabled:
        for shading in _shadings():
            state = shading.mixar_zen_sky
            if _owner(state) == scene:
                _restore(shading)
    if restart:
        scene.mixar_zen_sky.viewports.clear()
    if not enabled or screen is None:
        return

    keys = set()
    for area in screen.areas:
        if area.type != "VIEW_3D":
            continue
        shading = area.spaces.active.shading
        state = shading.mixar_zen_sky
        if not state.key or state.key in keys:
            # Splitting an area copies its settings, including our key.
            state.key = uuid4().hex
        keys.add(state.key)
        snapshot = scene.mixar_zen_sky.viewports.get(state.key)
        if _owner(state) != scene or not state.applied or snapshot is None:
            _restore(shading)
            if snapshot is None:
                snapshot = scene.mixar_zen_sky.viewports.add()
                snapshot.name = state.key
            snapshot.use_scene_world = shading.use_scene_world
            snapshot.use_scene_world_render = shading.use_scene_world_render
            owners = state.id_data.mixar_zen_sky_owners
            owner = owners.get(state.key)
            if owner is None:
                owner = owners.add()
                owner.name = state.key
            owner.scene = scene
        _apply(shading, snapshot, force=True)


@persistent
def sync_sky_viewports(_unused=None):
    """World undo/redo must also restore UI state, which Blender does not undo."""
    for shading in _shadings():
        state = shading.mixar_zen_sky
        scene = _owner(state)
        snapshot = scene.mixar_zen_sky.viewports.get(state.key) if scene else None
        if snapshot is not None and sky_enabled(scene):
            _apply(shading, snapshot)
        else:
            _restore(shading)
