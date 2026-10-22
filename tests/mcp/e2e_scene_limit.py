# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replay: an AI app fills Mixar to the scene-tab limit and keeps asking for more.

Against a real isolated app (e2e_launch.py --normal-input on the loopback
fixture). A scripted client once made one tab per asset, hit the 32-tab limit
and retried mixar_scene_new for minutes. Checks: tabs made through
mixar_scene_new up to the limit; every further call is the same final
scene_limit refusal (retryable false, counts, the tabs to reuse) and makes
nothing; a reuse session switches; once the user closes a tab in the app, the
next mixar_scene_new succeeds. Spends no credits. Screenshot goes to the
fixture, never into the repository.
"""

import argparse
import asyncio
import json
from pathlib import Path

from e2e_tool_availability import Replay

MAX_SCENES = 32
TAB_COUNT = "result = len(__import__('mixar.modules.space_mixie_chat.ui.operators.scene_tab_ops'," \
            "fromlist=['real_scenes']).real_scenes())"


async def run(options):
    replay = Replay(options)
    replay.ready()
    replay.qa.eval("result=list(bpy.ops.mixar.copy_mcp_setup(client='JSON'))")
    replay.qa.wait("__import__('mixar.modules.mcp_bridge.core.eligibility',fromlist=['valid']).valid()",
                   timeout=60)
    async with replay.session() as s:
        listed = (await s.call("mixar_scenes"))[1]["scenes"]
        for index in range(MAX_SCENES - len(listed)):
            result, _, text = await s.call("mixar_scene_new", {"name": f"Asset {index + 1:02d}"})
            replay.check(f"tab_{index + 1:02d}_created", not result.is_error, text[:300])
        listed = (await s.call("mixar_scenes"))[1]["scenes"]
        replay.check("filled_to_the_limit", len(listed) == MAX_SCENES == replay.qa.eval(TAB_COUNT), len(listed))

        refusals = []
        for _ in range(3):
            result, payload, text = await s.call("mixar_scene_new", {"name": "One More"})
            refusals.append((result.is_error, payload))
        replay.evidence["refusal"] = refusals[0][1]
        replay.check("every_retry_refused", all(error for error, _ in refusals), [p for _, p in refusals])
        refusal = refusals[0][1]
        replay.check("refusal_is_final_with_counts",
                     refusal.get("error_type") == "scene_limit" and refusal.get("retryable") is False
                     and refusal.get("scene_count") == MAX_SCENES and refusal.get("max_scenes") == MAX_SCENES,
                     refusal)
        replay.check("refusal_names_the_way_out", "Do not retry" in refusal.get("error", "")
                     and "mixar_scene_switch" in refusal["error"] and "close tool" not in refusal["error"],
                     refusal.get("error"))
        replay.check("reuse_lists_the_open_tabs",
                     sorted(t["session"] for t in refusal.get("reuse", []))
                     == sorted(t["session"] for t in listed), refusal.get("reuse"))
        replay.check("retries_are_identical", all(p == refusal for _, p in refusals), [p for _, p in refusals])
        replay.check("retries_made_nothing", replay.qa.eval(TAB_COUNT) == MAX_SCENES
                     and not any(t["name"] == "One More" for t in (await s.call("mixar_scenes"))[1]["scenes"]))

        target = next(t for t in refusal["reuse"] if not t["shown"])
        result, switched, text = await s.call("mixar_scene_switch", {"session": target["session"]})
        replay.check("reuse_session_switches", not result.is_error and switched.get("session") == target["session"]
                     and switched.get("shown") is True, text[:300] or switched)
        result, _, text = await s.call("scene_overview")
        replay.check("switched_tab_scene_tools_work", not result.is_error, text[:300])

        # The user closes a tab in the Scenes drawer (the drawer's own operator).
        doomed = next(t["name"] for t in refusal["reuse"] if t["session"] != target["session"])
        closed = replay.qa.eval(f"result = list(bpy.ops.mixie_chat.close_scene_tab(scene_name={doomed!r}))")
        replay.check("user_closed_a_tab", closed == ["FINISHED"] and replay.qa.eval(TAB_COUNT) == MAX_SCENES - 1,
                     closed)
        result, created, text = await s.call("mixar_scene_new", {"name": "One More"})
        replay.check("freed_capacity_creates_a_tab", not result.is_error and created.get("name") == "One More"
                     and replay.qa.eval(TAB_COUNT) == MAX_SCENES, text[:300] or created)
        result, payload, _ = await s.call("mixar_scene_new", {"name": "Too Many"})
        replay.check("full_again_refuses_again", result.is_error and payload.get("error_type") == "scene_limit",
                     payload)
        replay.qa.snap(str(replay.out / "scene-limit.png"))
    replay.check("all", True)
    print(json.dumps({"ok": True, "evidence": str(replay.out / "availability-verdict.json")}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--harness", type=Path, required=True)
    parser.add_argument("--port", type=int, default=4827)
    parser.add_argument("--second-port", type=int, default=4828)
    options = parser.parse_args()
    options.fixture = options.fixture.resolve()
    asyncio.run(run(options))


if __name__ == "__main__":
    main()
