# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Remove a camera from the scene together with the shots that direct it.

The "My Cameras" card lists the scene's cameras, so its delete affordance has
to mean what it says: the CAMERA goes, not just Director's record of it. A
delete that left the object behind would leave a row that reappears the moment
the card is redrawn.

Order matters. The shots go first (each through `remove_shot`, so the take's
own bookkeeping — preview range, active index, animation release — runs
exactly as it does from the strip menu), then the object. Doing it the other
way round leaves shots holding a pointer Blender has already cleared, and the
reconcile would have to guess whether the camera was deleted or never set.
"""

from __future__ import annotations

import bpy

from .shot_api import active_shot, remove_shot
from .tracking import clear_tracking


def shots_directing(state, camera) -> list[int]:
    """Indices of every shot (any state, any take) directing *camera*."""
    if state is None or camera is None:
        return []
    return [index for index, shot in enumerate(state.shots) if shot.camera == camera]


def _next_scene_camera(scene, removed):
    """Another camera for `scene.camera`, or ``None`` when that was the last."""
    for obj in scene.objects:
        if obj is not removed and getattr(obj, "type", None) == 'CAMERA':
            return obj
    return None


def delete_camera(scene, camera) -> int:
    """Delete *camera* and every shot directing it. Returns shots removed.

    The scene's active camera is re-pointed BEFORE the object goes, so the
    viewport never spends a redraw with `scene.camera` dangling. When the
    deleted camera was the last one, the scene simply has none — Director's
    empty state ("No cameras yet") is the honest answer, not a camera minted
    behind the user's back.
    """
    # The tracking constraint owns an aim helper parented to the target; it
    # exists only to be aimed at, so it goes with the camera that aimed.
    clear_tracking(camera)

    state = getattr(scene, "mixar_director", None)
    doomed = shots_directing(state, camera)
    # Highest index first: `state.shots.remove(i)` shifts everything after i.
    for index in sorted(doomed, reverse=True):
        remove_shot(scene, index)

    if scene.camera is camera:
        scene.camera = _next_scene_camera(scene, camera)

    bpy.data.objects.remove(camera, do_unlink=True)

    # The surviving shots decide the session's state; an index left past the
    # end of a shortened collection is what `active_shot` clamps.
    active_shot(scene)
    return len(doomed)
