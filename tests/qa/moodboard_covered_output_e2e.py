#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit GUI regression: a covered output handle yields to the visible picture.

Run in a clean isolated Dev QA app:
    QA_HARNESS=/path/to/mixar-qa-harness python3 tests/qa/moodboard_covered_output_e2e.py

Reproduces the bug-hunt finding: drop a wide reference, then a narrow portrait,
and place the portrait so its body lies over the wide reference's ``+`` handle.
Before the fix the handle's hit disc won a click at the portrait's centre and
opened Create Next Node for the hidden reference. Now the handle is neither a
QA target nor painted, the click selects the portrait, and moving the portrait
away restores the handle. Drops, clicks and the drag use real input events;
eval only reads state and positions fixtures. No generation is submitted.
Inspect the saved PNGs: no ``+`` may float over the portrait's pixels.
"""

import json
import os
from pathlib import Path

os.environ.setdefault("QA_SCENARIO_OUT", str(Path(__file__).resolve().parents[2] /
                                            "build/qa/moodboard-covered-output"))

from moodboard_drawer_e2e import (  # noqa: E402
    QA, OUT, SCENE, SETUP, drop, geometry, media, png, point, require,
    run_scenario, snap, switch_mode, target, toggle,
)


def outputs(qa):
    return {w["text"]: w for w in qa.find(surface="moodboard_output", limit=50)["widgets"]}


def centre(widget):
    return point(widget)


def place_over(qa, node_id, window_x, window_y):
    """Centre the picture `node_id` on a window pixel without resizing it."""
    board = target(qa, "moodboard_drawer_panel")["rect"]
    qa.eval(SETUP + f"""
from mixar.modules.moodboard.constants import MOODBOARD_IMAGE_BASE_SIZE
item=next(i for i in win.scene.mixie_moodboard_images if i.node_id=={node_id!r})
x0,y0,x1,y1={board!r}
cx,cy=drawer.view2d.region_to_view({window_x}-drawer.x,{window_y}-drawer.y)
width=MOODBOARD_IMAGE_BASE_SIZE*item.scale
height=width*item.image.size[1]/max(item.image.size[0],1)
item.position_x=cx-width/2
item.position_y=cy-height/2
item.selected=False
area.tag_redraw()
""")
    qa.wait(f"len(drv.find(surface='moodboard_media', text={node_id!r})) == 1", timeout=8)


def clear_selection(qa):
    qa.eval(SETUP + """
for item in win.scene.mixie_moodboard_images:
    item.selected=False
win.scene.mixie_moodboard_active_node_id=''
area.tag_redraw()
""")


def selected_ids(qa):
    return {i["id"] for i in media(qa) if i["selected"]}


def run(qa: QA):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.step("wait_idle", qa.wait,
            f"{SCENE}.mixie_chat_state in ('IDLE', 'OFFLINE')", timeout=90)
    if geometry(qa)["workspace"] != "Zen Mode":
        qa.step("enter_zen", switch_mode, qa, "mixar.set_ui_mode_ai", "Zen Mode")
    if geometry(qa)["amount"] < 0.98:
        qa.step("open_drawer", toggle, qa, 1)
    panel = target(qa, "moodboard_drawer_panel")

    wide = png(OUT / "reference-wide.png", (220, 70, 70), width=192, height=96)
    portrait = png(OUT / "reference-portrait.png", (50, 130, 230), width=48, height=160)
    older = qa.step("drop_wide_reference", drop, qa, wide, **point(panel, 0.35, 0.55))
    newer = qa.step("drop_narrow_portrait", drop, qa, portrait, **point(panel, 0.7, 0.3))
    clear_selection(qa)

    before = outputs(qa)
    require(older in before and newer in before,
            f"Both uncovered handles must be QA targets, got {sorted(before)}")
    handle = centre(before[older])
    snap(qa, "01_both_handles_visible")

    # Lay the portrait over the older picture's "+" handle, as a drop/pan/zoom
    # sequence leaves older pictures behind a newly dropped one.
    qa.step("cover_older_handle", place_over, qa, newer, handle["x"], handle["y"])
    qa.wait(f"{older!r} not in [w['text'] for w in "
            f"drv.find(surface='moodboard_output', limit=50)]", timeout=6)
    covered = outputs(qa)
    require(older not in covered, "A covered handle must not be offered as a target")
    require(newer in covered, "The portrait's own handle stays available")
    snap(qa, "02_portrait_covers_older_handle")

    source_before = qa.eval(f"result={SCENE}.mixie_moodboard_output_source_id")
    # The click lands on the portrait exactly where the hidden handle's hit
    # disc used to win (a pixel click: `click` resolves a widget, and the
    # hidden handle is deliberately no longer one). It must select the
    # portrait and open no menu.
    qa.step("click_portrait_over_hidden_handle", qa.cmd, "click_xy",
            x=handle["x"], y=handle["y"])
    qa.wait(f"any(i.node_id == {newer!r} and i.selected for i in "
            f"{SCENE}.mixie_moodboard_images)", timeout=4)
    require(selected_ids(qa) == {newer},
            f"The visible portrait must be the only selection, got {selected_ids(qa)}")
    require(not qa.find(popup=True)["total"], "A covered handle opened its menu")
    require(qa.eval(f"result={SCENE}.mixie_moodboard_output_source_id") == source_before,
            "Create Next Node was armed for the hidden picture")
    require(not qa.eval(f"result=len({SCENE}.mixie_moodboard_links)"),
            "A link was minted from the hidden handle")
    snap(qa, "03_click_selected_portrait_no_menu")

    # Positive control: a drag of the portrait away uncovers the handle again.
    widget = target(qa, "moodboard_media", text=newer)
    start = point(widget)
    qa.cmd("drag", **{"from": {"surface": "moodboard_media", "text": newer},
                      "to": {"x": start["x"] + 260, "y": start["y"] - 140}, "steps": 12})
    qa.wait(f"{older!r} in [w['text'] for w in "
            f"drv.find(surface='moodboard_output', limit=50)]", timeout=6)
    require(older in outputs(qa), "Moving the portrait away must restore the handle")
    snap(qa, "04_handle_restored_after_move")

    require(qa.eval(f"result=len({SCENE}.mixie_moodboard_action_nodes)") == 0,
            "The scenario must not create nodes")
    result = {"credits_spent": 0, "older": older, "portrait": newer,
              "clicked_at": handle, "screenshots": str(OUT)}
    (OUT / "state-evidence.json").write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    run_scenario("moodboard_covered_output_e2e", run)
