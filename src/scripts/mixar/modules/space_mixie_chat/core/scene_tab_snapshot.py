# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene-card thumbnails are SNAPSHOTS of the Zen viewport, never renders.

``view3d.scenes_drawer_snapshot`` (C++, ``view3d_scenes_drawer_thumbs.cc``)
copies the host View3D's last drawn frame as the shown tab's card picture. The
tab switch calls it BEFORE any window moves to another scene, so a card shows
the tab as the user last saw it; the drawer tick refreshes only the shown
card. Nothing here can render a scene, evaluate a background depsgraph or
compile a shader, which is what the previous per-tab offscreen render did on
every edit-mode toggle next to a Cycles viewport.

Every entry point here is best-effort: a snapshot that cannot be taken (no Zen
viewport, a window resize in flight, snapshots disabled for the session) is
skipped and the card keeps its last picture. A tab switch never fails because
of its thumbnail.
"""

from __future__ import annotations

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def zen_view3d_override() -> dict | None:
    """The Zen Mode 3D viewport as a ``temp_override`` mapping, or None."""
    window_manager = getattr(bpy.context, 'window_manager', None)
    if window_manager is None:
        return None
    for window in window_manager.windows:
        if window.workspace.name != 'Zen Mode':
            continue
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != 'VIEW_3D':
                continue
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            if region is None:
                continue
            return {'window': window, 'screen': screen, 'area': area, 'region': region,
                    'space_data': area.spaces.active}
    return None


def snapshot_shown_tab() -> bool:
    """Keep the viewport's last frame as the shown tab's card. Never raises."""
    override = zen_view3d_override()
    if override is None:
        return False
    try:
        with bpy.context.temp_override(**override):
            return bpy.ops.view3d.scenes_drawer_snapshot() == {'FINISHED'}
    except Exception as error:  # noqa: BLE001 — a card picture never blocks a tab switch
        logger.debug("scene tab snapshot skipped: %s", error)
        return False
