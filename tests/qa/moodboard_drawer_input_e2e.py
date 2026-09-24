#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit GUI regression for what the Zen moodboard drawer OWNS.

Four defects found by driving the real app, each of which the drawer looked
correct through: the shut drawer claimed viewport presses along the right and
bottom of its band, the hidden N-panel's reveal tab lived inside the open
drawer, Annotate survived a close into a mode nothing could exit, and a drop
left a clipped redo panel behind.

Launch an isolated Dev app with the QA harness, then run:
    QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4777 \
        QA_SCENARIO_OUT=/tmp/moodboard-drawer-input \
        python3 tests/qa/moodboard_drawer_input_e2e.py

All feature actions use real simulated mouse/key/file-drop events. Eval reads
state or prepares fixtures. Screenshots must also be viewed by the QA agent.
"""

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from moodboard_drawer_e2e import (  # noqa: E402
    SCENE, drop, geometry, png, require, settle, target, tilde_toggle, toggle,
)

HARNESS = os.environ.get("QA_HARNESS")
if not HARNESS:
    raise SystemExit("Set QA_HARNESS to the local mixar-qa-harness checkout")
sys.path.insert(0, str(Path(HARNESS) / "scenarios"))
from lib import run_scenario  # noqa: E402

OUT = Path(os.environ.get("QA_SCENARIO_OUT", "/tmp/moodboard-drawer-input"))
SIDEBAR = "drv.main_window().screen.areas[0].spaces.active.show_region_ui"
ANNOTATING = "bpy.context.window_manager.mixie_moodboard_annotating"
STROKES = f"len({SCENE}.mixie_moodboard_annotations)"


def snap(qa, name, **args):
    OUT.mkdir(parents=True, exist_ok=True)
    return qa.cmd("snap", path=str(OUT / f"{name}.png"), **args)


def sidebar_set(qa, shown):
    qa.eval(f"{SIDEBAR} = {bool(shown)}\nresult = {SIDEBAR}")
    qa.wait(f"{SIDEBAR} is {bool(shown)}", timeout=4)


def selection(qa):
    return qa.eval("result = sorted(o.name for o in bpy.data.objects if o.select_get())")


def select_all_objects(qa):
    qa.eval("for o in bpy.data.objects: o.select_set(True)\nresult = 1")
    require(selection(qa), "Fixture needs at least one selectable object")


def passes_through(qa, label, x, y):
    """A press the drawer must NOT claim reaches the viewport and deselects."""
    select_all_objects(qa)
    qa.cmd("click_xy", x=x, y=y)
    qa.wait("not any(o.select_get() for o in bpy.data.objects)", timeout=4)
    require(geometry(qa)["amount"] == 0.0,
            f"{label} at ({x},{y}) moved the drawer instead of reaching the viewport")


def band_passes_through(qa):
    """The shut drawer's region spans the viewport's right 425 px in BOTH
    states — closing is a paint translation, not a resize. Its scroller action
    zones used to claim every press along the right and bottom of that band.
    Probe points deliberately avoid the closed grip, which SHOULD claim its
    own rect."""
    grip = target(qa, "moodboard_drawer_grip")["rect"]
    region = qa.eval(
        "a = drv.main_window().screen.areas[0]\n"
        "r = next(x for x in a.regions if x.type == 'TOOL_PROPS')\n"
        "result = [r.x, r.y, r.x + r.width, r.y + r.height]")
    probes = [
        ("right edge above grip", region[2] - 5, grip[3] + 180),
        ("right edge below grip", region[2] - 5, grip[1] - 140),
        ("right edge inset", region[2] - 9, grip[1] - 190),
        ("bottom edge", (region[0] + region[2]) // 2, region[1] + 6),
        ("bottom edge inset", (region[0] + region[2]) // 2 + 100, region[1] + 13),
        ("band interior", (region[0] + region[2]) // 2, (region[1] + region[3]) // 2),
    ]
    for label, x, y in probes:
        inside_grip = grip[0] <= x <= grip[2] and grip[1] <= y <= grip[3]
        require(not inside_grip, f"probe {label} ({x},{y}) landed on the grip")
        passes_through(qa, label, x, y)
    return [p[0] for p in probes]


def sidebar_tab_suppressed(qa, where):
    """`region_azone_tab_plus` pins the hidden N-panel's reveal tab to the
    area's top-right corner, which in Zen Mode is inside the open drawer and
    on the navigation gizmo when it is shut. Azones resolve screen-wide before
    any region handler, so one press there silently opened a full stock
    sidebar UNDER the board."""
    sidebar_set(qa, False)
    area = geometry(qa)["area"]
    for dx, dy in ((-3, -35), (-7, -50), (-13, -65)):
        qa.cmd("click_xy", x=area[2] + dx, y=area[3] + dy)
        shown = qa.eval(f"result = {SIDEBAR}")
        require(shown is False,
                f"{where}: press at the area's top-right corner opened the sidebar")
    return True


def sidebar_key_still_works(qa):
    """Suppressing the tab must not strand the sidebar: N still opens it."""
    sidebar_set(qa, False)
    qa.eval("import qa_driver as d\nd.move_to(drv.main_window(), 600, 400)\nresult = 1")
    qa.press("N")
    qa.wait(f"{SIDEBAR} is True", timeout=4)
    sidebar_set(qa, False)
    return True


def annotate_released_on_close(qa, node_id):
    """Annotate is a mode on the surface being put away. Left armed it
    survived the close, and `mixie.moodboard_annotation_exit` polls a context
    that needs the drawer OPEN — so nothing could clear it, and the first
    click after reopening laid down a saved stroke instead of selecting."""
    qa.click(op="MIXIE_OT_moodboard_annotate_canvas")
    qa.wait(f"{ANNOTATING} is True", timeout=4)
    strokes = qa.eval(f"result = {STROKES}")

    toggle(qa, 0)
    require(qa.eval(f"result = {ANNOTATING}") is False,
            "Closing the drawer left Annotate armed")

    toggle(qa, 1)
    qa.eval(f"for i in {SCENE}.mixie_moodboard_images: i.selected = False\nresult = 1")
    card = target(qa, "moodboard_media", text=node_id)["rect"]
    qa.cmd("click_xy", x=(card[0] + card[2]) // 2, y=(card[1] + card[3]) // 2)
    qa.wait(f"any(i.node_id == {node_id!r} and i.selected "
            f"for i in {SCENE}.mixie_moodboard_images)", timeout=4)
    require(qa.eval(f"result = {STROKES}") == strokes,
            "The first click after reopening drew a stroke instead of selecting")
    return True


def annotate_survives_a_programmatic_close(qa):
    """Only a USER close releases Annotate.

    Scribble's capture closes the drawer through `view3d.moodboard_drawer_set`
    (`scribble_mark/core/drawer_guard.py`) and its restore returns only
    `amount`/`target`, so releasing the mode on that path would silently disarm
    Annotate across every capture.
    """
    qa.click(op="MIXIE_OT_moodboard_annotate_canvas")
    qa.wait(f"{ANNOTATING} is True", timeout=4)
    for amount in (0.0, 1.0):
        qa.eval("\n".join((
            "w = drv.main_window()",
            "a = next(x for x in w.screen.areas if x.type == 'VIEW_3D')",
            "r = next(x for x in a.regions if x.type == 'WINDOW')",
            "with bpy.context.temp_override(window=w, screen=w.screen, area=a, region=r):",
            f"    bpy.ops.view3d.moodboard_drawer_set(amount={amount}, target={amount})",
            "result = 1",
        )))
        settle(qa, amount)
        require(qa.eval(f"result = {ANNOTATING}") is True,
                f"A scripted drawer_set to {amount} released Annotate")
    qa.click(op="MIXIE_OT_moodboard_annotate_canvas")
    qa.wait(f"{ANNOTATING} is False", timeout=4)
    return True


def annotate_survives_a_close_beside_a_mixie_editor(qa):
    """The flag is WindowManager-wide and the standalone Mixie editor is an
    annotate host of its own, so closing the drawer must not cancel a session
    that editor owns."""
    qa.eval("\n".join((
        "w = drv.main_window()",
        "a = next(x for x in w.screen.areas if x.type == 'VIEW_3D')",
        "with bpy.context.temp_override(window=w, screen=w.screen, area=a):",
        "    bpy.ops.screen.area_split(direction='VERTICAL', factor=0.4)",
        "drv.main_window().screen.areas[0].ui_type = 'MIXIE'",
        "result = [x.type for x in drv.main_window().screen.areas]",
    )))
    qa.wait("any(a.type == 'MIXIE' for a in drv.main_window().screen.areas)", timeout=6)
    try:
        if geometry(qa)["amount"] != 1.0:
            toggle(qa, 1)
        qa.click(op="MIXIE_OT_moodboard_annotate_canvas")
        qa.wait(f"{ANNOTATING} is True", timeout=4)
        toggle(qa, 0)
        require(qa.eval(f"result = {ANNOTATING}") is True,
                "Closing the drawer cancelled Annotate in the standalone Mixie editor")
    finally:
        qa.eval(f"{ANNOTATING} = False\nresult = 1")
        qa.eval("\n".join((
            "w = drv.main_window()",
            "a = next(x for x in w.screen.areas if x.type == 'MIXIE')",
            "with bpy.context.temp_override(window=w, screen=w.screen, area=a):",
            "    bpy.ops.screen.area_close()",
            "result = [x.type for x in drv.main_window().screen.areas]",
        )))
        qa.wait("not any(a.type == 'MIXIE' for a in drv.main_window().screen.areas)", timeout=6)
        # Hand the drawer back open, the way the step found it.
        if geometry(qa)["amount"] != 1.0:
            toggle(qa, 1)
    return True


def drop_leaves_no_redo_panel(qa, path):
    """Every drop property is SKIP_SAVE, so REGISTER drew an empty redo block
    that collapsed to its minimum width and clipped its own header to
    "Drop Media to Moodboar", then stayed as the last operator afterwards."""
    qa.eval("result = bpy.ops.ed.undo_push(message='qa drop fence')")
    node_id = drop(qa, path, x=1340, y=400)
    last = qa.eval(
        "op = getattr(bpy.context, 'active_operator', None)\n"
        "result = op.bl_idname if op else None")
    require(last != "MIXIE_OT_moodboard_drop_image",
            f"The drop still registers a redo panel (active_operator={last})")
    return node_id


def prepare(qa):
    """Start from a shut drawer, a hidden sidebar and an empty board.

    Board state is eval fixture work; the drawer itself is shut with a real
    grip click, and only when it is open. The suite resets state between
    scenarios, but this one both starts AND ends at the drawer, so it must not
    depend on the previous case leaving it shut.
    """
    qa.eval("\n".join((
        f"{SCENE}.mixie_moodboard_images.clear()",
        f"{SCENE}.mixie_moodboard_annotations.clear()",
        f"{ANNOTATING} = False",
        "result = 1",
    )))
    if geometry(qa)["amount"] != 0.0:
        toggle(qa, 0)
    sidebar_set(qa, False)
    return True


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    require(geometry(qa)["workspace"] == "Zen Mode", "Scenario starts in Zen Mode")
    qa.step("prepare", prepare, qa)

    qa.step("shut_drawer_passes_presses_through", band_passes_through, qa)
    qa.step("snap_shut", snap, qa, "01_shut", area="VIEW_3D")
    qa.step("reveal_tab_suppressed_when_shut", sidebar_tab_suppressed, qa, "shut")
    qa.step("sidebar_key_still_works", sidebar_key_still_works, qa)
    qa.step("tilde_opens_from_viewport", tilde_toggle, qa, 1, over="viewport")
    qa.step("tilde_closes_from_panel", tilde_toggle, qa, 0, over="panel")

    qa.step("open_drawer", toggle, qa, 1)
    qa.step("reveal_tab_suppressed_when_open", sidebar_tab_suppressed, qa, "open")

    fixture = png(OUT / "reference.png", (80, 170, 110))
    node_id = qa.step("drop_leaves_no_redo_panel", drop_leaves_no_redo_panel, qa, fixture)
    qa.step("snap_open_with_reference", snap, qa, "02_open", area="VIEW_3D")
    qa.step("annotate_released_on_close", annotate_released_on_close, qa, node_id)
    qa.step("annotate_survives_a_programmatic_close",
            annotate_survives_a_programmatic_close, qa)
    qa.step("annotate_survives_a_close_beside_a_mixie_editor",
            annotate_survives_a_close_beside_a_mixie_editor, qa)

    settle(qa, 1)
    qa.step("snap_capsule", snap, qa, "03_add_tools_over_content",
            target={"block": "moodboard_drawer_add_tools"}, margin=64)
    return {"reference": node_id, "screenshots": str(OUT),
            "band_passes_through": True, "reveal_tab_suppressed": True,
            "annotate_released_on_close": True, "drop_has_no_redo_panel": True,
            "annotate_release_is_user_and_zen_only": True}


if __name__ == "__main__":
    run_scenario("moodboard_drawer_input_e2e", run)
