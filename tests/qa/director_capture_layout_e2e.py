# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Real-click Cinema capture and compact top-row layout; no backend or credits.

Load this replay through the installed QA harness with the Scenes drawer open.
Run at 1280x720 and a smaller supported window, in Zen and Engine (the default).
For a tall window, set QA_DIRECTOR_LAYOUT=wide to check the designed surface's
capture path separately. QA_DIRECTOR_MODES can limit a run to Zen or Engine.

Camera pose, locked-take and free-view states are synthetic fixtures. All
actions under test use semantic native clicks, never operator execution or
the I shortcut. The old compact layout captures no beat and exits Cinema.
Snapshots must be inspected alongside the state assertions.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4777 \
QA_SCENARIO_OUT=/tmp/director-layout python tests/qa/director_capture_layout_e2e.py
"""

import os
from pathlib import Path
import sys

if os.environ.get("QA_HARNESS"):
    sys.path.insert(0, str(Path(os.environ["QA_HARNESS"]) / "scenarios"))
from lib import ScenarioFail, ensure_scenes_drawer, run_scenario  # noqa: E402


STATE = "drv.main_window().scene.mixar_director"
SHOT = f"{STATE}.shots[{STATE}.active_shot_index]"


def _state(qa):
    return qa.eval(
        "s = drv.main_window().scene; d = s.mixar_director\n"
        "sh = d.shots[d.active_shot_index]\n"
        "result = {'directing': d.is_directing, 'shots': len(d.shots), "
        "'beats': len(sh.beats), 'state': sh.state, 'take': sh.version, "
        "'auto_key': s.tool_settings.use_keyframe_insert_auto, "
        "'walking': d.walk_active, "
        "'navigation': d.navigation_mode, 'camera': s.camera.name}"
    )


def _targets(qa, **query):
    return qa.find(**query)["widgets"]


def _top_target(qa, **query):
    """One live compact button, with its full rect clear of Cinema's toolbar."""
    matches = _targets(qa, region_type="WINDOW", **query)
    if len(matches) != 1:
        raise ScenarioFail(f"Expected one compact control: {query}: {matches}")
    target = matches[0]
    for toolbar in _targets(qa, op="MIXAR_OT_director_enter"):
        if toolbar["window"] != target["window"]:
            continue
        a, b = target["rect"], toolbar["rect"]
        overlap = max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])
        if overlap:
            raise ScenarioFail(f"Compact control overlaps Cinema toolbar: {target}, {toolbar}")
    return target


def _snap(qa, mode, label):
    out = os.environ.get("QA_SCENARIO_OUT", "/tmp")
    return qa.snap(os.path.join(out, f"director-{mode.lower()}-{label}.png"))


def _free_view(qa):
    # Exercise the alternate top row without starting a native walk modal.
    qa.eval(
        "w=drv.main_window(); a=next(a for a in w.screen.areas if a.type=='VIEW_3D')\n"
        "a.spaces.active.region_3d.view_perspective='PERSP'\n"
        "w.scene.mixar_director.navigation_mode='EXPLORE'\n"
        "a.tag_redraw(); result=True"
    )
    qa.wait("len(drv.find(op='MIXAR_OT_director_return_to_shot', region_type='WINDOW')) == 1", timeout=5)


def _run_mode(qa, mode, compact):
    qa.step(f"{mode}_reset", qa.cmd, "reset_state")
    qa.cmd("wait_login", timeout=60)
    ensure_scenes_drawer(qa)
    desired = "pro" if mode == "Engine" else "ai"
    current = qa.eval("result=__import__('mixar.config.config',fromlist=['x']).get_ui_mode()")
    if current != desired:
        qa.click(text=mode)
        qa.wait(
            f"__import__('mixar.config.config',fromlist=['x']).get_ui_mode()=={desired!r}",
            timeout=10,
        )
    qa.click(op="MIXAR_OT_director_enter")
    qa.wait(f"{STATE}.is_directing and len({STATE}.shots) > 0", timeout=15)
    qa.wait("len(drv.find(surface='director_timeline')) >= 1", timeout=10)
    if not compact:
        qa.wait("len(drv.find(surface='director_add_camera')) == 1", timeout=10)

    qa.eval(
        "s=drv.main_window().scene; s.frame_set(10); s.camera.location.x += 0.7\n"
        "result=True"
    )
    before = _state(qa)
    if not before["walking"]:
        raise ScenarioFail("Cinema entry did not start walk; click pass-through would be untested")
    _snap(qa, mode, "before-capture")
    # Deliberately click before checking geometry: on the old build the
    # verdict records the actual user-facing failure (exit with zero beats).
    query = {"op": "MIXAR_OT_director_capture_beat"}
    if compact:
        query["region_type"] = "WINDOW"
    capture = qa.step(f"{mode}_click_capture", qa.click, **query)
    after = _state(qa)
    if not after["directing"] or after["beats"] != before["beats"] + 1:
        raise ScenarioFail(f"Capture click did not add exactly one beat in Cinema: {before} -> {after}")
    qa.wait(f"len({SHOT}.beats) == {before['beats'] + 1}", timeout=15)
    qa.wait("len(drv.find(surface='director_key')) >= 1", timeout=10)
    _snap(qa, mode, "captured")
    if not compact:
        return {"mode": mode, "layout": "wide", "capture": capture, "before": before, "after": after}
    _top_target(qa, op="MIXAR_OT_director_capture_beat")

    auto_target = _top_target(qa, prop="use_keyframe_insert_auto")
    original_auto = after["auto_key"]
    qa.click(prop="use_keyframe_insert_auto", region_type="WINDOW")
    qa.wait(f"drv.main_window().scene.tool_settings.use_keyframe_insert_auto == {not original_auto}", timeout=5)
    qa.click(prop="use_keyframe_insert_auto", region_type="WINDOW")
    qa.wait(f"drv.main_window().scene.tool_settings.use_keyframe_insert_auto == {original_auto}", timeout=5)

    # Lock the fixture without leaving Cinema so the compact new-take row is
    # visible. The click must preserve the locked parent and create a draft.
    qa.eval(
        "from mixar.modules.director.core.shot_api import lock_shot\n"
        f"lock_shot(drv.main_window().scene, {SHOT})\nresult=True"
    )
    qa.wait("len(drv.find(op='MIXAR_OT_director_new_take', region_type='WINDOW')) == 1", timeout=5)
    new_take_target = _top_target(qa, op="MIXAR_OT_director_new_take")
    qa.click(op="MIXAR_OT_director_new_take", region_type="WINDOW")
    qa.wait(f"len({STATE}.shots)=={after['shots'] + 1} and {SHOT}.state=='DRAFT'", timeout=5)
    take = _state(qa)
    if not qa.eval(f"result=any(sh.state == 'LOCKED' for sh in {STATE}.shots)"):
        raise ScenarioFail("Starting a new take lost its locked parent")

    _free_view(qa)
    return_target = _top_target(qa, op="MIXAR_OT_director_return_to_shot")
    qa.click(op="MIXAR_OT_director_return_to_shot", region_type="WINDOW")
    qa.wait(f"{STATE}.navigation_mode=='NAVIGATE'", timeout=5)
    if _state(qa)["shots"] != take["shots"]:
        raise ScenarioFail("Back to Shot added a camera")

    _free_view(qa)
    camera_target = _top_target(qa, op="MIXAR_OT_director_new_shot")
    _snap(qa, mode, "add-camera")
    qa.click(op="MIXAR_OT_director_new_shot", region_type="WINDOW")
    qa.wait(f"len({STATE}.shots)=={take['shots'] + 1} and {STATE}.is_directing", timeout=5)
    new_camera = _state(qa)
    if new_camera["camera"] == take["camera"]:
        raise ScenarioFail("Add Camera Here reused the existing shot's camera")
    _snap(qa, mode, "new-camera")
    return {"mode": mode, "layout": "compact", "before": before, "after_capture": after,
            "after_new_take": take, "after_new_camera": new_camera,
            "targets": {"capture": capture, "auto_key": auto_target, "new_take": new_take_target,
                        "return_to_shot": return_target, "new_camera": camera_target}}


def run(qa):
    layout = os.environ.get("QA_DIRECTOR_LAYOUT", "compact")
    if layout not in ("compact", "wide"):
        raise ScenarioFail(f"Unsupported QA_DIRECTOR_LAYOUT: {layout}")
    modes = os.environ.get("QA_DIRECTOR_MODES", "Zen,Engine").split(",")
    if not modes or any(mode not in ("Zen", "Engine") for mode in modes):
        raise ScenarioFail(f"Unsupported QA_DIRECTOR_MODES: {modes}")
    return {"cases": [_run_mode(qa, mode, layout == "compact") for mode in modes],
            "input": "Semantic native clicks; synthetic pose/lock/free-view fixtures; no shortcut fallback"}


if __name__ == "__main__":
    run_scenario("director_capture_layout_e2e", run)
