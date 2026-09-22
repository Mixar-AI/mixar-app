#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit regression for a drag released outside the board under the halo.

Use QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT like the other drawer
scenarios. Cover both handler orders: agent already running, and agent
starting after the user has pressed on a reference or empty canvas.
"""

from moodboard_agent_lock_e2e import OUT, busy, move, protected_viewport, snap, LOCK
from moodboard_drawer_e2e import (
    SCENE, drop, geometry, png, point, require, run_scenario, target, toggle,
)


def drag_release(qa, lock_first, box_select=False):
    operator = "MIXIE_OT_moodboard_box_select" if box_select else "MIXIE_OT_moodboard_select_image"
    drag = f"drv.main_window().modal_operators.get({operator!r})"
    busy(qa, "IDLE")
    qa.eval(f"{SCENE}.mixie_moodboard_images.clear()\nresult = True")
    if geometry(qa)["amount"] < 0.98:
        toggle(qa, 1)
    pos = point(target(qa, "moodboard_drawer_panel"), 0.6, 0.6)
    node_id = drop(qa, png(OUT / "drag-reference.png", (70, 160, 110)), **pos)
    start = (point(target(qa, "moodboard_drawer_panel"), 0.75, 0.3)
             if box_select else point(target(qa, "moodboard_media", text=node_id)))
    if lock_first:
        busy(qa, "BUSY")
    move(qa, **start)
    qa.eval("drv._sim(drv.main_window(), type='LEFTMOUSE', value='PRESS')\nresult = True")
    qa.wait(f"{drag} is not None", timeout=3)
    if not lock_first:
        busy(qa, "BUSY")
    rect = geometry(qa)["viewport"]
    x, y = int(rect[0] + (rect[2] - rect[0]) * 0.25), int(rect[1] + 200)
    require(qa.eval("a = next(a for a in drv.main_window().screen.areas if a.type == 'VIEW_3D')\n"
                    f"result = not a.mixar_moodboard_contains({x}, {y})"),
            "Release point must be on the protected viewport")
    move(qa, x, y)
    qa.eval("drv._sim(drv.main_window(), type='LEFTMOUSE', value='RELEASE')\nresult = True")
    qa.wait(f"{drag} is None", timeout=3)
    require(qa.eval(f"result = {LOCK}"), "Drag completion lifted the agent lock")
    protected_viewport(qa, x, y)
    return True


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.dismiss_splash()
    qa.eval("w = drv.main_window()\n"
            "cube = w.scene.objects['Cube']\n"
            "for o in w.scene.objects: o.select_set(o == cube)\n"
            "w.view_layer.objects.active = cube\nresult = True")
    try:
        qa.step("release_outside_when_lock_already_running", drag_release, qa, True)
        qa.step("release_outside_when_lock_starts_mid_drag", drag_release, qa, False)
        qa.step("box_release_when_lock_already_running", drag_release, qa, True, True)
        qa.step("box_release_when_lock_starts_mid_drag", drag_release, qa, False, True)
        qa.step("snap_lock_still_active", snap, qa, "drag_release_still_locked")
        return {"fixture": "BUSY/AGENT, no backend turn", "screenshots": str(OUT)}
    finally:
        qa.press("ESC")
        busy(qa, "IDLE")


if __name__ == "__main__":
    run_scenario("moodboard_drag_release_e2e", run)
