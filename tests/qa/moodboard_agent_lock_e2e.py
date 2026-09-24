#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit regression: Moodboard stays usable under the agent halo.

Run on an isolated QA app:
  QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4797 \
    QA_SCENARIO_OUT=/tmp/moodboard-agent-lock \
    python3 tests/qa/moodboard_agent_lock_e2e.py

The fixture sets BUSY/AGENT; the real bootstrap starts the real lock and
halo. This tests UI routing, not a backend turn. Feature actions use native
events. Eval prepares fixtures, reads state, and moves the simulated pointer.
Inspect the saved screenshots in addition to the state verdict.
"""

import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).parent))
from moodboard_drawer_e2e import (  # noqa: E402
    SCENE, drop, geometry, png, point, require, select, settle, target, toggle,
)

sys.path.insert(0, str(Path(os.environ["QA_HARNESS"]) / "scenarios"))
from lib import run_scenario  # noqa: E402

OUT = Path(os.environ.get("QA_SCENARIO_OUT", "/tmp/moodboard-agent-lock"))
LOCK = "__import__('mixar.modules.agent_viewport_lock.ui.operators.viewport_block_op', fromlist=['is_running']).is_running()"


def move(qa, x, y):
    qa.eval(f"drv.move_to(drv.main_window(), {int(x)}, {int(y)})\nresult = True")


def snap(qa, name):
    # RNA changes before the next painted frame, especially on resize/popups.
    qa.eval("for a in drv.main_window().screen.areas: a.tag_redraw()\nresult = True")
    qa.wait(f"__import__('time').monotonic() >= {time.monotonic() + 0.4}", timeout=2)
    # SCREEN_OT_screenshot redraws windows and destroys hover/menu state.
    # The app's QA capture recomposes cached region buffers without doing so.
    path = str(OUT / f"{name}.png")
    saved = qa.eval("w = drv.main_window()\n"
                    "with bpy.context.temp_override(window=w):\n"
                    f" result = w.mixar_qa_capture_frame(filepath={path!r})")
    require(saved, f"Could not capture QA frame: {path}")
    return path


def busy(qa, state):
    qa.eval(f"{SCENE}.mixie_chat_active_turn_mode = 'AGENT'\n"
            f"{SCENE}.mixie_chat_state = {state!r}\nresult = True")
    qa.wait(f"{LOCK} == {state == 'BUSY'}", timeout=5)


def protected_viewport(qa, x, y):
    cursor = qa.eval(f"result = list({SCENE}.cursor.location)")
    objects = qa.eval("result = {o.name: list(o.location) for o in bpy.data.objects}")
    move(qa, x, y)
    qa.press("RIGHTMOUSE", shift=True)
    qa.press("G")
    move(qa, x + 45, y + 25)
    qa.press("RET")
    require(qa.eval(f"result = list({SCENE}.cursor.location)") == cursor,
            "Locked viewport allowed a cursor edit")
    require(qa.eval("result = {o.name: list(o.location) for o in bpy.data.objects}") == objects,
            "Locked viewport allowed an object transform")
    require(qa.eval(f"result = {LOCK}"), "Moodboard action dropped the lock")
    return True


def add_text(qa):
    qa.click(op="MIXIE_OT_moodboard_add_textbox")
    qa.wait(f"len({SCENE}.mixie_moodboard_textboxes) == 1", timeout=4)
    panel = target(qa, "moodboard_drawer_panel")
    pos = point(panel, 0.35, 0.4)
    move(qa, **pos)
    qa.cmd("click_xy", **pos)
    qa.wait("drv.main_window().modal_operators.get('MIXIE_OT_moodboard_add_textbox') is None",
            timeout=4)
    return True


def edit_reference(qa, node_id):
    qa.eval(f"for i in {SCENE}.mixie_moodboard_images: i.selected = False\nresult = True")
    select(qa, node_id)
    before = qa.eval(f"i = next(i for i in {SCENE}.mixie_moodboard_images if i.node_id == {node_id!r})\n"
                     "result = [i.position_x, i.position_y]")
    pos = point(target(qa, "moodboard_media", text=node_id))
    qa.cmd("drag", **{"from": {"surface": "moodboard_media", "text": node_id},
                      "to": {"x": pos["x"] - 60, "y": pos["y"] + 30}, "steps": 12})
    qa.wait(f"any(i.node_id == {node_id!r} and [i.position_x, i.position_y] != {before!r} "
            f"for i in {SCENE}.mixie_moodboard_images)", timeout=4)
    # Context menu is another formerly swallowed right-click path.
    pos = point(target(qa, "moodboard_media", text=node_id))
    move(qa, **pos)
    qa.press("RIGHTMOUSE")
    qa.wait("len(drv.find(popup=True)) > 0", timeout=4)
    snap(qa, "03_context_menu_while_busy")
    qa.press("ESC")
    return True


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.dismiss_splash()
    require(geometry(qa)["workspace"] == "Zen Mode", "Start in Zen Mode")
    qa.eval("w = drv.main_window()\n"
            "cube = w.scene.objects.get('Cube')\n"
            "assert cube is not None, 'Use a clean startup scene'\n"
            "for o in w.scene.objects: o.select_set(o == cube)\n"
            "w.view_layer.objects.active = cube\n"
            "w.scene.cursor.location = (0, 0, 0)\nresult = True")
    qa.eval(f"{SCENE}.mixie_moodboard_images.clear()\n"
            f"{SCENE}.mixie_moodboard_textboxes.clear()\nresult = True")
    if geometry(qa)["amount"] != 0:
        toggle(qa, 0)
    try:
        qa.step("activate_real_lock", busy, qa, "BUSY")
        qa.step("open_grip_while_busy", toggle, qa, 1)
        qa.step("add_and_place_text_while_busy", add_text, qa)
        fixture = png(OUT / "reference.png", (80, 170, 110), width=160, height=120)
        pos = point(target(qa, "moodboard_drawer_panel"), 0.6, 0.65)
        node_id = qa.step("drop_reference_while_busy", drop, qa, fixture, **pos)
        qa.step("select_move_and_context_menu", edit_reference, qa, node_id)
        qa.step("snap_interactive_board_and_halo", snap, qa, "04_interactive_board")
        view = geometry(qa)["viewport"]
        qa.step("viewport_edits_still_blocked", protected_viewport, qa,
                view[0] + 0.35 * (view[2] - view[0]), view[1] + 0.4 * (view[3] - view[1]))
        grip = target(qa, "moodboard_drawer_grip")["rect"]
        # Transparent gutter above the grip belongs to the viewport.
        qa.step("transparent_gutter_stays_locked", protected_viewport, qa,
                (grip[0] + grip[2]) / 2, grip[3] + 70)
        qa.step("close_grip_while_busy", toggle, qa, 0)
        qa.step("closed_drawer_footprint_stays_locked", protected_viewport, qa,
                view[2] - 100, view[1] + 0.25 * (view[3] - view[1]))
        qa.step("reopen_grip_while_busy", toggle, qa, 1)
        start = point(target(qa, "moodboard_drawer_grip"))
        qa.cmd("drag", **{"from": {"surface": "moodboard_drawer_grip"},
                          "to": {"x": start["x"] - 180, "y": start["y"]}, "steps": 18})
        settle(qa, 1)
        require(target(qa, "moodboard_drawer_grip")["rect"][0] < start["x"] - 100,
                "Drawer did not resize while busy")
        select(qa, node_id)
        qa.step("snap_resized_board", snap, qa, "05_resized_board")
        qa.step("unlock_on_idle", busy, qa, "IDLE")
        cursor = qa.eval(f"result = list({SCENE}.cursor.location)")
        move(qa, view[0] + 350, view[1] + 300)
        qa.press("RIGHTMOUSE", shift=True)
        qa.wait(f"list({SCENE}.cursor.location) != {cursor!r}", timeout=4)
        qa.step("snap_unlocked", snap, qa, "06_idle")
        return {"fixture": "BUSY/AGENT, no backend turn", "screenshots": str(OUT)}
    finally:
        busy(qa, "IDLE")


if __name__ == "__main__":
    run_scenario("moodboard_agent_lock_e2e", run)
