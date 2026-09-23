#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit regression: the Zen toolbar stays above the agent halo and Sketch hint.

Run on an isolated QA app:
  QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4797 \
    QA_SCENARIO_OUT=/tmp/zen-toolbar-agent-lock \
    python3 tests/qa/zen_toolbar_agent_lock_e2e.py

The fixture sets BUSY/AGENT; the real bootstrap starts the real lock and halo.
Toolbar controls must work through native events while the canvas, and the
empty toolbar bed Blender routes to it, stay locked. Sketch is then armed to
capture its hint below the toolbar. Inspect the screenshots as well as the
verdict.
"""

import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).parent))
from zen_scene_toolbar_e2e import HEADER, SETUP, reset_zen_scene  # noqa: E402

sys.path.insert(0, str(Path(os.environ["QA_HARNESS"]) / "scenarios"))
from lib import run_scenario  # noqa: E402

OUT = Path(os.environ.get("QA_SCENARIO_OUT", "/tmp/zen-toolbar-agent-lock"))
SCENE = "drv.main_window().scene"
LOCK = ("__import__('mixar.modules.agent_viewport_lock.ui.operators.viewport_block_op', "
        "fromlist=['is_running']).is_running()")
REGIONS = SETUP + """
rect = lambda r: [r.x, r.y, r.x + r.width, r.y + r.height]
result = {r.type: rect(r) for r in area.regions if r.width > 1 and r.height > 1}
result['inset'] = __import__('mixar.modules.common.utils.ui_utils',
    fromlist=['x']).top_header_overlap_px(area, next(r for r in area.regions if r.type == 'WINDOW'))
"""


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def move(qa, x, y):
    qa.eval(f"drv.move_to(drv.main_window(), {int(x)}, {int(y)})\nresult = True")


def snap(qa, name):
    qa.eval("for a in drv.main_window().screen.areas: a.tag_redraw()\nresult = True")
    qa.wait(f"__import__('time').monotonic() >= {time.monotonic() + 0.4}", timeout=2)
    path = str(OUT / f"{name}.png")
    saved = qa.eval("w = drv.main_window()\n"
                    "with bpy.context.temp_override(window=w):\n"
                    f" result = w.mixar_qa_capture_frame(filepath={path!r})")
    require(saved, f"Could not capture QA frame: {path}")
    return path


def connection_settled(qa):
    """Login lands before the WebSocket handshake; a CONNECTING that arrives
    after the BUSY fixture replaces it (and the turn mode) mid-scenario."""
    qa.cmd("wait_login", timeout=60)
    return qa.eval("""
import time
def ready():
    began, since = time.monotonic(), None
    while time.monotonic() - began < 30:
        if drv.main_window().scene.mixie_chat_state == 'IDLE':
            since = since or time.monotonic()
            if time.monotonic() - since > 2:
                return True
        else:
            since = None
        yield .1
    raise AssertionError('Chat connection did not settle')
result = ready()
""")


def busy(qa, state):
    qa.eval(f"{SCENE}.mixie_chat_active_turn_mode = 'AGENT'\n"
            f"{SCENE}.mixie_chat_state = {state!r}\nresult = True")
    qa.wait(f"{LOCK} == {state == 'BUSY'}", timeout=5)
    return True


def scene_state(qa):
    return qa.eval(f"result = {{'cursor': list({SCENE}.cursor.location), "
                   "'objects': sorted(o.name for o in bpy.data.objects), "
                   f"'selected': sorted(o.name for o in {SCENE}.objects if o.select_get())}}")


def header_overlaps(qa):
    regions = qa.eval(REGIONS)
    header, window = regions["HEADER"], regions["WINDOW"]
    # The premise: the WINDOW rect runs under the toolbar.
    require(header[1] < window[3], f"Header does not overlap the viewport: {regions}")
    require(regions["inset"] == window[3] - header[1], f"Inset mismatch: {regions}")
    return regions


def toolbar_controls(qa):
    xray = SETUP + "result = view.shading.show_xray"
    before = qa.eval(xray)
    qa.click(**HEADER, prop="show_xray")
    require(qa.eval(xray) != before, "X-ray toggle was blocked by the lock")
    qa.click(**HEADER, prop="show_xray")
    require(qa.eval(xray) == before, "X-ray toggle back was blocked by the lock")
    qa.click(**HEADER, but_type="Popover")
    qa.wait("len(drv.find(popup=True)) > 0", timeout=4)
    snap(qa, "02_shading_popover_while_busy")
    qa.press("ESC")
    qa.click(**HEADER, op="SCREEN_OT_animation_play")
    qa.wait("bpy.context.screen.is_animation_playing or "
            "any(w.screen.is_animation_playing for w in bpy.context.window_manager.windows)",
            timeout=4)
    qa.click(**HEADER, op="SCREEN_OT_animation_play")
    qa.wait("not any(w.screen.is_animation_playing for w in bpy.context.window_manager.windows)",
            timeout=4)
    lock = qa.eval(f"s = {SCENE}\n"
                   "op = drv.main_window().modal_operators.get('MIXAR_OT_agent_viewport_block')\n"
                   f"result = [{LOCK}, op is not None, s.mixie_chat_state, "
                   "s.mixie_chat_active_turn_mode]")
    require(lock[0], f"Toolbar use dropped the lock: {lock}")
    return {"xray": True, "shading_popover": True, "play_pause": True}


def empty_bed_x(qa, regions):
    """An x on the toolbar strip with no control within 40 px."""
    rects = [w["rect"] for w in qa.find(**HEADER)["widgets"]]
    header = regions["HEADER"]
    y = (header[1] + header[3]) // 2
    for x in range(header[0] + 60, header[2] - 60, 8):
        if all(x < r[0] - 40 or x > r[2] + 40 for r in rects):
            if not qa.eval(SETUP + f"result = area.mixar_header_contains({x}, {y})"):
                return x, y
    raise AssertionError(f"No empty toolbar bed found among {rects}")


def locked_at(qa, x, y):
    before = scene_state(qa)
    move(qa, x, y)
    qa.press("LEFTMOUSE")
    qa.press("RIGHTMOUSE", shift=True)
    qa.press("X")
    qa.press("DEL")
    require(not qa.eval("result = len(drv.find(popup=True)) > 0"), "A delete menu opened")
    after = scene_state(qa)
    require(after == before, f"Locked input changed the scene at {(x, y)}: {before} -> {after}")
    return True


def sketch_hint(qa, regions):
    busy(qa, "IDLE")
    qa.eval("bpy.ops.mixar.bubble_restore()")
    qa.wait("bool(drv.find(op='MIXAR_OT_scribble_toggle'))", timeout=10)
    qa.click(op="MIXAR_OT_scribble_toggle")
    qa.wait("bpy.context.window_manager.mixar_mark_armed", timeout=10)
    hint, voice = qa.eval("from mixar.modules.scribble_mark import constants as C\n"
                          "result = [C.MARK_HINT_IDLE, C.MARK_HINT_VOICE]")
    require(voice in hint and voice.startswith("Hold "), hint)
    return snap(qa, "04_sketch_hint_below_toolbar")


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.step("connection_settled", connection_settled, qa)
    reset_zen_scene(qa)
    qa.eval("w = drv.main_window()\n"
            "cube = w.scene.objects.get('Cube')\n"
            "assert cube is not None, 'Use a clean startup scene'\n"
            "for o in w.scene.objects: o.select_set(o == cube)\n"
            "w.view_layer.objects.active = cube\n"
            "w.scene.cursor.location = (0, 0, 0)\nresult = True")
    verdict = {}
    try:
        regions = qa.step("header_overlaps_viewport", header_overlaps, qa)
        verdict["regions"] = regions
        qa.step("activate_real_lock", busy, qa, "BUSY")
        snap(qa, "01_halo_below_toolbar")
        verdict["toolbar"] = qa.step("toolbar_controls_while_busy", toolbar_controls, qa)
        bed = empty_bed_x(qa, regions)
        verdict["empty_bed"] = qa.step("empty_toolbar_bed_stays_locked", locked_at, qa, *bed)
        window = regions["WINDOW"]
        verdict["canvas"] = qa.step(
            "canvas_stays_locked", locked_at, qa,
            window[0] + 0.4 * (window[2] - window[0]), window[1] + 0.4 * (window[3] - window[1]))
        snap(qa, "03_after_locked_input")
        verdict["sketch_hint"] = qa.step("sketch_hint_visible", sketch_hint, qa, regions)
        verdict["screenshots"] = str(OUT)
        return verdict
    finally:
        qa.eval("bpy.context.window_manager.mixar_mark_armed = False\nresult = True")
        busy(qa, "IDLE")
        (OUT / "verdict.json").write_text(json.dumps(verdict, indent=2))


if __name__ == "__main__":
    run_scenario("zen_toolbar_agent_lock_e2e", run)
