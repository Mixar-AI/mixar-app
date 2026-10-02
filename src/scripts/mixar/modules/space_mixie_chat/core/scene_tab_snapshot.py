# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene-card thumbnails are SNAPSHOTS of the drawer's viewport, never renders.

``view3d.scenes_drawer_snapshot`` (C++, ``view3d_scenes_drawer_thumbs.cc``)
copies the host View3D's last drawn frame as the shown tab's card picture. The
host is the window's main 3D View — Zen's, or the largest one of an Engine
workspace (``Area.mixar_scenes_drawer_hosts``). The
tab switch calls it BEFORE any window moves to another scene, so a card shows
the tab as the user last saw it; the drawer tick refreshes only the shown
card. Nothing here can render a scene, evaluate a background depsgraph or
compile a shader, which is what the previous per-tab offscreen render did on
every edit-mode toggle next to a Cycles viewport.

Every entry point here is best-effort: a snapshot that cannot be taken (no 3D
viewport, a window resize in flight, snapshots disabled for the session) is
skipped and the card keeps its last picture. A tab switch never fails because
of its thumbnail.
"""

from __future__ import annotations

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def hosts_scenes_drawer(area, workspace=None) -> bool:
    """True when ``area`` is the 3D View that shows the window's Scenes drawer.

    The native region poll decides (the window's largest 3D View, in Zen and
    Engine alike); ``workspace`` is only the fallback for a build without
    ``Area.mixar_scenes_drawer_hosts``, which hosted the drawer in Zen only.
    """
    if area is None or getattr(area, 'type', None) != 'VIEW_3D':
        return False
    hosts = getattr(area, 'mixar_scenes_drawer_hosts', None)
    if hosts is not None:
        try:
            return bool(hosts())
        except Exception:  # noqa: BLE001 — a stale area never breaks a draw or a tick
            return False
    return getattr(workspace, 'name', None) == 'Zen Mode'


def drawer_view3d_override() -> dict | None:
    """The Scenes drawer's 3D viewport as a ``temp_override`` mapping, or None."""
    window_manager = getattr(bpy.context, 'window_manager', None)
    if window_manager is None:
        return None
    for window in window_manager.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if not hosts_scenes_drawer(area, window.workspace):
                continue
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            if region is None:
                continue
            return {'window': window, 'screen': screen, 'area': area, 'region': region,
                    'space_data': area.spaces.active}
    return None


def snapshot_shown_tab() -> bool:
    """Keep the viewport's last frame as the shown tab's card. Never raises."""
    override = drawer_view3d_override()
    if override is None:
        return False
    try:
        with bpy.context.temp_override(**override):
            return bpy.ops.view3d.scenes_drawer_snapshot() == {'FINISHED'}
    except Exception as error:  # noqa: BLE001 — a card picture never blocks a tab switch
        logger.debug("scene tab snapshot skipped: %s", error)
        return False
