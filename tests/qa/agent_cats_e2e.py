#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reference-style cats in the real GUI; no generation calls or credit spend.

Run against an isolated QA app:
  QA_HARNESS=/path/to/mixar-qa-harness python3 tests/qa/agent_cats_e2e.py
Snapshots go to QA_SCENARIO_OUT (default /tmp). Inspect the PNGs as well as
the state verdict. Requires Pillow in the scenario interpreter. Reuses the
harness's semantic-target event helper.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(os.environ["QA_HARNESS"]) / "scenarios"))
from lib import ScenarioFail, run_scenario  # noqa: E402
from agent_panel_cards_e2e import _click_at, _centre  # noqa: E402
from cat_motion import capture, preview, verify  # noqa: E402


NAMES = ["Shape the character", "Paint soft textures", "Light the scene",
         "Build the backdrop", "Frame the camera", "Polish the details"]
ITEMS = [{"id": f"cat-{i}", "text": text, "status": "in_progress"}
         for i, text in enumerate(NAMES)]
PALETTES = ["Emerald", "Amber", "Lagoon", "Lilac", "Sky", "Lime"]


def identities(qa):
    return qa.eval("result = {w['text']: w['value'] "
                   "for w in drv.find(surface='agent_panel_cat')}")


def mirror(qa, items, clear=False):
    return qa.eval(
        "from mixar.modules.agent_panel.core.cards import clear_cards, mirror_todo_items\n"
        + ("clear_cards()\n" if clear else "")
        + f"result = mirror_todo_items({items!r})"
    )


def run(qa):
    out = Path(os.environ.get("QA_SCENARIO_OUT", "/tmp"))
    out.mkdir(parents=True, exist_ok=True)
    qa.step("ready", qa.cmd, "wait_login", timeout=60)
    expected = {f"cat-{i}": name for i, name in enumerate(PALETTES)}
    qa.step("spawn_six", mirror, qa, ITEMS, True)
    try:
        qa.step("three_visible", qa.wait,
                "[w['text'] for w in drv.find(surface='agent_panel_cat')] == "
                "['cat-0', 'cat-1', 'cat-2']", timeout=12)
        first = qa.step("first_identities", identities, qa)
        if first != dict(list(expected.items())[:3]):
            raise ScenarioFail(f"first three cats: {first}")
        qa.step("stack_picture", qa.cmd, "snap", path=str(out / "cats_stack.png"),
                target={"surface": "agent_panel_card", "index": 1}, margin=230)
        for i in range(3):
            qa.step(f"cat_{i}_picture", qa.cmd, "snap", path=str(out / f"cat_{i}.png"),
                    target={"surface": "agent_panel_cat", "text": f"cat-{i}"}, margin=4)
        pill = qa.step("capture_pill_motion", capture, qa,
                       [{"surface": "pill_cat"}], out / "pill_motion")[0]
        pill_motion = qa.step("pupils_move_and_blink", verify, pill, blink=True)
        qa.step("animation_preview", preview, pill, out / "cat_animation.gif")
        running = qa.step("capture_running_cats", capture, qa,
                          [{"surface": "agent_panel_cat", "text": f"cat-{i}"}
                           for i in range(3)], out / "running_motion")
        running_motion = [qa.step(f"working_cat_{i}_moves", verify, frames)
                          for i, frames in enumerate(running)]

        qa.step("scroll", _click_at, qa, *_centre(qa, "agent_panel_chevron"))
        qa.step("last_three_visible", qa.wait,
                "[w['text'] for w in drv.find(surface='agent_panel_cat')] == "
                "['cat-3', 'cat-4', 'cat-5']", timeout=8)
        second = qa.step("other_identities", identities, qa)
        if first | second != expected:
            raise ScenarioFail(f"six distinct cats: {first | second}")
        for i in range(3, 6):
            qa.step(f"cat_{i}_picture", qa.cmd, "snap", path=str(out / f"cat_{i}.png"),
                    target={"surface": "agent_panel_cat", "text": f"cat-{i}"}, margin=4)
        qa.step("other_stack_picture", qa.cmd, "snap", path=str(out / "cats_other_stack.png"),
                target={"surface": "agent_panel_card", "index": 4}, margin=230)

        reordered = list(reversed(ITEMS))
        reordered[-1] = dict(reordered[-1], status="failed")
        reordered[-2] = dict(reordered[-2], status="pending")
        qa.step("reorder_and_settle", mirror, qa, reordered)
        qa.step("identity_survives_reorder_and_status", qa.wait,
                "{w['text']: w['value'] for w in drv.find(surface='agent_panel_cat')} == "
                + repr(dict(list(expected.items())[:3])), timeout=8)
        settled = qa.step("capture_settled_cats", capture, qa,
                          [{"surface": "agent_panel_cat", "text": f"cat-{i}"}
                           for i in range(2)], out / "settled_motion", duration=2.0)
        for i, frames in enumerate(settled):
            qa.step(f"settled_cat_{i}_stays_still", verify, frames, still=True)
        qa.step("dismiss", _click_at, qa, *_centre(qa, "agent_panel_dismiss", 4))
        qa.step("dismissed", qa.wait,
                "'cat-1' not in [c.task_id for c in bpy.context.window_manager.mixar_agent_cards]",
                timeout=8)
        remaining = qa.step("remaining_identities", identities, qa)
        if not remaining or any(expected[k] != v for k, v in remaining.items()):
            raise ScenarioFail(f"dismiss changed another cat: {remaining}")
        qa.step("new_fanout", mirror, qa, list(reversed(ITEMS[:3])), True)
        qa.step("new_generation_resets_palette", qa.wait,
                "{w['text']: w['value'] for w in drv.find(surface='agent_panel_cat')} == "
                + repr({"cat-2": "Emerald", "cat-1": "Amber", "cat-0": "Lagoon"}), timeout=10)
        return {"variations": expected, "identity_stable": True,
                "pill_motion": pill_motion, "running_motion": running_motion,
                "animation_preview": str(out / "cat_animation.gif")}
    finally:
        qa.eval("from mixar.modules.agent_panel.core.cards import clear_cards; clear_cards(); result=True")


if __name__ == "__main__":
    run_scenario("agent_cats_e2e", run)
