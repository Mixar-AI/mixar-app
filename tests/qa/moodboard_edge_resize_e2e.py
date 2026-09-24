#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit edge resize/cursor regression, idle and under the real agent lock.

Run on an isolated QA app with QA_HARNESS, MIXAR_QA_PORT and
QA_SCENARIO_OUT set, like moodboard_agent_lock_e2e.py. Native cursor state
is exported on the edge QA target; screenshots verify the resulting layout.
The final case reloads the isolated startup file mid-drag with Load UI off
to verify cursor cleanup on the retained native window.
"""

from moodboard_agent_lock_e2e import OUT, busy, move, snap
from moodboard_drawer_e2e import (
    SCENE, drop, geometry, png, point, require, run_scenario, settle, target, toggle,
)

WIDTH = "bpy.context.window_manager.mixar_moodboard_drawer_width"


def width(qa):
    return qa.eval(f"result = {WIDTH}")


def edge(qa, index=0):
    return target(qa, "moodboard_drawer_edge", index=index)


def hover(qa, index=0):
    pos = point(edge(qa, index))
    move(qa, **pos)
    qa.wait("any(w.get('value') == 'RESIZE_X' for w in "
            "drv.find(surface='moodboard_drawer_edge'))", timeout=3)
    return pos


def resize(qa, dx, index=0):
    start = hover(qa, index)
    before = width(qa)
    qa.cmd("drag", **{"from": {"surface": "moodboard_drawer_edge", "index": index},
                      "to": {"x": start["x"] + dx, "y": start["y"]}, "steps": 16})
    settle(qa, 1)
    after = width(qa)
    require(after > before if dx < 0 else after < before,
            f"Edge drag did not resize: {before} -> {after}")
    return after


def edge_click_keeps_open(qa):
    hover(qa)
    before = width(qa)
    qa.click(surface="moodboard_drawer_edge", index=0)
    settle(qa, 1)
    require(width(qa) == before, "Clicking the edge changed width")
    require(qa.eval("result = bpy.context.window_manager.mixar_moodboard_drawer_target") == 1,
            "Clicking the edge toggled the board")
    return True


def escape_restores(qa):
    start = hover(qa)
    before = width(qa)
    qa.eval(f"drv._sim(drv.main_window(), type='LEFTMOUSE', value='PRESS', "
            f"x={start['x']}, y={start['y']})\nresult = True")
    move(qa, start["x"] - 100, start["y"])
    qa.wait(f"{WIDTH} > {before + 10}", timeout=3)
    require(edge(qa)["value"] == "RESIZE_X", "Drag lost horizontal resize cursor")
    qa.press("ESC")
    qa.eval("drv._sim(drv.main_window(), type='LEFTMOUSE', value='RELEASE')\nresult = True")
    qa.wait(f"abs({WIDTH} - {before}) < 0.01", timeout=3)
    return True


def cursor_resets(qa):
    pos = point(target(qa, "moodboard_drawer_panel"), 0.55, 0.35)
    move(qa, **pos)
    qa.wait("all(w.get('value') == 'OTHER' for w in "
            "drv.find(surface='moodboard_drawer_edge'))", timeout=3)
    return True


def minimum_stays_open(qa):
    start = hover(qa)
    view = geometry(qa)["viewport"]
    qa.cmd("drag", **{"from": {"surface": "moodboard_drawer_edge", "index": 0},
                      "to": {"x": view[2] - 5, "y": start["y"]}, "steps": 20})
    settle(qa, 1)
    require(abs(width(qa) - 120) < 0.1, "Edge did not stop at minimum width")
    return True


def external_teardown_restores_cursor(qa):
    busy(qa, "IDLE")
    if geometry(qa)["amount"] < 0.98:
        toggle(qa, 1)
    start = hover(qa)
    window = qa.eval("result = drv.main_window().as_pointer()")
    drag = "drv.main_window().modal_operators.get('VIEW3D_OT_moodboard_drawer_grip')"
    before = width(qa)
    qa.eval("drv._sim(drv.main_window(), type='LEFTMOUSE', value='PRESS')\nresult = True")
    move(qa, start["x"] - 80, start["y"])
    qa.wait(f"{drag} is not None and {WIDTH} > {before + 10}", timeout=3)
    # Keep the native window: replacing it would hide a leaked modal cursor.
    qa.eval("with bpy.context.temp_override(window=drv.main_window()):\n"
            " result = list(bpy.ops.wm.read_homefile(load_ui=False))")
    qa.wait(f"{drag} is None", timeout=5)
    require(qa.eval("result = drv.main_window().as_pointer()") == window,
            "File reload replaced the window, masking cursor cleanup")
    qa.eval("drv._sim(drv.main_window(), type='LEFTMOUSE', value='RELEASE')\nresult = True")
    qa.dismiss_splash()
    if geometry(qa)["amount"] < 0.98:
        toggle(qa, 1)
    cursor_resets(qa)
    require(edge(qa)["value"] == "OTHER", "Teardown left the horizontal cursor active")
    return True


def resize_past_clipped_content(qa):
    # Selected reference controls extend across the sash when the board is
    # narrow. They must not intercept the edge press before its keymap.
    pos = point(edge(qa))
    fixture = png(OUT / "edge-reference.png", (80, 170, 110), width=160, height=120)
    drop(qa, fixture, x=pos["x"] + 35, y=pos["y"])
    # Import rebuilds the canvas UI after the RNA item appears. Paint that
    # layout before approaching the sash; a queued rebuild resets hover.
    snap(qa, "minimum_width_with_clipped_content")
    return resize(qa, -440)


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.dismiss_splash()
    require(geometry(qa)["workspace"] == "Zen Mode", "Start in Zen Mode")
    qa.eval(f"{SCENE}.mixie_moodboard_images.clear()\nresult = True")
    try:
        for state in ("IDLE", "BUSY"):
            # Each mode is a separate case. Do not inherit the previous
            # case's clipped images, canvas zoom, hover or drawer width.
            busy(qa, "IDLE")
            qa.cmd("reset_state")
            qa.cmd("wait_login", timeout=30)
            qa.dismiss_splash()
            busy(qa, state)
            if geometry(qa)["amount"] < 0.98:
                toggle(qa, 1)
            qa.step(f"{state}_edge_cursor", hover, qa)
            qa.step(f"{state}_edge_click_keeps_open", edge_click_keeps_open, qa)
            qa.step(f"{state}_upper_edge_widens", resize, qa, -160)
            qa.step(f"{state}_lower_edge_narrows", resize, qa, 80, 1)
            qa.step(f"{state}_escape_restores_width", escape_restores, qa)
            qa.step(f"{state}_cursor_resets_on_canvas", cursor_resets, qa)
            qa.step(f"{state}_minimum_stays_open", minimum_stays_open, qa)
            qa.step(f"{state}_resize_from_minimum_with_clipped_content",
                    resize_past_clipped_content, qa)
            qa.step(f"{state}_screenshot", snap, qa, f"edge_resize_{state.lower()}")
            toggle(qa, 0)
            require(not qa.find(surface="moodboard_drawer_edge")["widgets"],
                    "Closed drawer still exports a resize edge")
        qa.step("external_teardown_restores_cursor", external_teardown_restores_cursor, qa)
        qa.step("teardown_screenshot", snap, qa, "edge_resize_after_teardown")
        return {"screenshots": str(OUT), "fixture": "IDLE and BUSY/AGENT; no backend turn"}
    finally:
        busy(qa, "IDLE")


if __name__ == "__main__":
    run_scenario("moodboard_edge_resize_e2e", run)
