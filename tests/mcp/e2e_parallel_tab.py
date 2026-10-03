# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replay: an AI app opens a new scene tab while Mixie works in another.

Against a real isolated app (e2e_launch.py --normal-input on the loopback
fixture). Mixie's turn is the state a running turn sets on its tab (BUSY in
Agent mode), which raises the real viewport lock and undo shield. Checks: scene
tools on the busy tab say another agent is working there and point to
mixar_scene_new; mixar_scene_new succeeds anyway; the busy tab keeps its state;
the new tab's scene tools work. Spends no credits. Screenshot goes to the
fixture, never into the repository.
"""

import argparse
import asyncio
import json
from pathlib import Path

from e2e_tool_availability import Replay

BUSY_TAB = "Royal Bedroom"
MODALS = ("result = sorted({op.bl_idname for w in bpy.context.window_manager.windows "
          "for op in w.modal_operators})")


def mixie_turn(qa):
    """Start a Mixie Agent turn on the shown tab, as the chat does."""
    qa.eval("from mixar.modules.space_mixie_chat.core.session import get_session_manager\n"
            "from mixar.modules.space_mixie_chat.constants import SessionState\n"
            "scene = bpy.context.window.scene\n"
            f"scene.name = {BUSY_TAB!r}\nscene.mixie_chat_mode = 'AGENT'\n"
            "get_session_manager().set_state(scene, SessionState.BUSY)\nresult = True")


async def run(options):
    replay = Replay(options)
    replay.ready()
    replay.qa.eval("result=list(bpy.ops.mixar.copy_mcp_setup(client='JSON'))")
    replay.qa.wait("__import__('mixar.modules.mcp_bridge.core.eligibility',fromlist=['valid']).valid()",
                   timeout=60)
    async with replay.session() as s:
        _, context, _ = await s.call("mixar_ui_context")
        busy_session = context["session_id"]
        mixie_turn(replay.qa)
        try:
            replay.qa.wait("{'MIXAR_OT_agent_viewport_block', 'MIXIE_CHAT_OT_undo_shield'} <= "
                           "{op.bl_idname for w in bpy.context.window_manager.windows for op in w.modal_operators}",
                           timeout=20)
            replay.evidence["modals_while_mixie_works"] = replay.qa.eval(MODALS)

            result, _, text = await s.call("scene_overview")
            replay.check("busy_tab_says_another_agent_works_there",
                         result.is_error and "Another agent" in text and "mixar_scene_new" in text, text[:300])

            result, created, text = await s.call("mixar_scene_new", {"name": "Tamil Temple Complex"})
            replay.check("new_tab_while_mixie_works", not result.is_error, text[:300] or created)
            tabs = {t["name"]: t for t in (await s.call("mixar_scenes"))[1]["scenes"]}
            replay.evidence["tabs"] = tabs
            replay.check("mixie_tab_keeps_working", tabs[BUSY_TAB]["state"] == "busy"
                         and tabs[BUSY_TAB]["session"] == busy_session, tabs[BUSY_TAB])
            replay.check("new_tab_is_shown", tabs["Tamil Temple Complex"]["shown"], tabs)

            result, _, text = await s.call("scene_overview")
            replay.check("new_tab_scene_tools_work", not result.is_error, text[:300])
            replay.evidence["modals_after_new_tab"] = replay.qa.eval(MODALS)
            replay.qa.snap(str(replay.out / "parallel-tab.png"))
        finally:
            replay.qa.eval("from mixar.modules.space_mixie_chat.core.session import get_session_manager\n"
                           "from mixar.modules.space_mixie_chat.constants import SessionState\n"
                           f"s = bpy.data.scenes.get({BUSY_TAB!r})\n"
                           "s and get_session_manager().set_state(s, SessionState.IDLE)\nresult = True")
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
