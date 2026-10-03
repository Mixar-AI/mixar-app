# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replay how an external AI app's connection survives what a user does to Mixar.

Normal-input QA app (e2e_launch.py --normal-input); every UI action goes through
the product MCP connection, the harness only prepares state and asserts it.
Spends no credits. Covers: interface control off/on, Codex image results, File >
New clicked through mixar_ui_act (the stuck "UI operation" and the stale scene
pin), mixar_projects / mixar_project_open, and reconnecting after Mixar is quit
and reopened. Read the emitted PNGs before claiming visual acceptance.
"""

import argparse
import asyncio
import base64
from contextlib import AsyncExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import Implementation

from e2e_scene import load_qa

UI_INPUT = {"mixar_ui_observe", "mixar_ui_act", "mixar_ui_wait"}
NOTIFY_ELIGIBLE = "__import__('mixar.modules.mcp_bridge.core.eligibility',fromlist=['valid']).valid()"


class Replay:
    def __init__(self, options):
        self.options, self.out = options, options.fixture / "recovery"
        self.out.mkdir(exist_ok=True)
        self.qa = load_qa(options.harness, options.port)
        self.evidence = {"checks": {}}
        self.launcher = str(options.fixture / "connector" / "mixar-mcp")
        self.env = {**os.environ, "MIXAR_MCP_DISCOVERY_DIR": str(options.fixture / "discovery")}

    def check(self, name, ok, detail=None):
        self.evidence["checks"][name] = {"ok": bool(ok), "detail": detail}
        (self.out / "recovery-verdict.json").write_text(json.dumps(self.evidence, indent=2, default=str))
        print(("[scenario] OK   " if ok else "[scenario] FAIL ") + name, flush=True)
        if not ok:
            raise AssertionError(f"{name}: {detail}")

    def ready(self, timeout=150, eligible=True):
        deadline = time.monotonic() + timeout
        while True:
            try:
                self.qa.cmd("ping")
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(1)
        self.qa.cmd("wait_login", timeout=120)
        if eligible:  # Only once MCP is on: a fresh profile starts with it off.
            self.qa.wait(NOTIFY_ELIGIBLE, timeout=90)

    def relaunch(self, blend=None):
        command = [sys.executable, str(Path(__file__).with_name("e2e_launch.py")), str(self.options.fixture),
                   "--relaunch", *([str(blend)] if blend else [])]
        subprocess.run(command, check=True, capture_output=True, text=True)
        self.ready()

    def session(self, client="claude-code"):
        return _Session(self, client)


class _Session:
    def __init__(self, replay, client):
        self.replay, self.client = replay, client

    async def __aenter__(self):
        self._stack = AsyncExitStack()
        params = StdioServerParameters(command=self.replay.launcher, args=[], env=self.replay.env)
        streams = await self._stack.enter_async_context(stdio_client(params))
        self.mcp = await self._stack.enter_async_context(
            ClientSession(*streams, client_info=Implementation(name=self.client, version="1")))
        await self.mcp.initialize()
        return self

    async def __aexit__(self, *exc):
        await self._stack.aclose()

    async def tools(self):
        return {tool.name: tool for tool in (await self.mcp.list_tools()).tools}

    async def call(self, name, args=None):
        result = await self.mcp.call_tool(name, args or {}, meta={"mixar/request-id": str(uuid4())})
        payload = (result.structured_content or {}).get("result")
        text = " ".join(block.text for block in result.content if block.type == "text")
        return result, payload, text

    async def snap(self, name):
        result, _, _ = await self.call("mixar_ui_observe", {"limit": 5, "image": True})
        image = next(block for block in result.content if block.type == "image")
        (self.replay.out / name).write_bytes(base64.b64decode(image.data))

    async def click(self, text, *, op=None, popup=None):
        _, state, _ = await self.call("mixar_ui_observe", {"query": {"text": text}, "limit": 20})
        target = next(t for t in state["targets"] if (op is None or t.get("op") == op)
                      and (popup is None or bool(t.get("popup")) == popup)
                      and (op or t.get("type") == "Pulldown"))
        return await self.call("mixar_ui_act", {"action": "click", "context": state["context"],
                                                "target": target["target"]})


async def interface_control(replay):
    replay.qa.eval("result=list(bpy.ops.mixar.set_mcp_ui_control(enabled=False))")
    async with replay.session() as s:
        tools = await s.tools()
        replay.check("ui_off_hides_interface_tools", not UI_INPUT & set(tools)
                     and {"mixar_ui_context", "mixar_scenes", "mixar_projects"} <= set(tools), sorted(tools))
        result, payload, _ = await s.call("mixar_ui_observe", {"limit": 3})
        replay.check("ui_off_refuses_input", result.is_error and payload["error_type"] == "ui_control_off", payload)
        result, _, _ = await s.call("scene_overview")
        replay.check("ui_off_keeps_scene_tools", not result.is_error)
    replay.qa.eval("result=list(bpy.ops.mixar.set_mcp_ui_control(enabled=True))")
    async with replay.session() as s:
        replay.check("ui_on_lists_interface_tools", UI_INPUT <= set(await s.tools()))


async def codex_images(replay):
    async with replay.session("codex-mcp-client") as s:
        tools = await s.tools()
        replay.check("codex_gets_no_output_schemas", all(t.output_schema is None for t in tools.values()))
        result, _, text = await s.call("render_viewport", {"view": "hero", "width": 640, "height": 360})
        images = [block for block in result.content if block.type == "image"]
        replay.check("codex_render_carries_image_without_structured_content",
                     not result.is_error and images and result.structured_content is None, text[:120])
        (replay.out / "codex-render.png").write_bytes(base64.b64decode(images[0].data))
    async with replay.session() as s:
        result, _, _ = await s.call("render_viewport", {"view": "hero", "width": 320, "height": 180})
        replay.check("other_clients_keep_structured_content", result.structured_content is not None)


async def file_new(replay):
    replay.qa.eval("bpy.ops.mesh.primitive_monkey_add()\nbpy.ops.ed.undo_push(message='edit')\nresult=True")
    async with replay.session() as s:
        await s.click("File")
        await asyncio.sleep(0.5)
        _, clicked, _ = await s.click("New", op="WM_OT_read_homefile", popup=True)
        replay.check("file_new_click_reports_document_loaded", clicked.get("document_loaded") is True, clicked)
        await asyncio.sleep(2)
        result, payload, _ = await s.call("mixar_ui_observe", {"limit": 3})
        replay.check("stale_pin_explains_rebinding_for_ui", result.is_error and payload["error_type"] == "document_changed",
                     payload)
        result, _, text = await s.call("scene_overview")
        replay.check("stale_pin_explains_rebinding_for_scene_tools",
                     result.is_error and "mixar_ui_context(session=" in text, text[:200])
        _, context, _ = await s.call("mixar_ui_context")
        replay.check("no_stuck_ui_operation_after_load", context["input_busy"] is False, context)
        result, _, _ = await s.call("mixar_ui_context", {"session": context["session_id"]})
        result, overview, _ = await s.call("scene_overview")
        replay.check("rebound_connection_works", not result.is_error and overview["object_count"] == 3, overview)
        await s.snap("after-file-new.png")


async def projects(replay):
    work = replay.options.fixture / "work"
    work.mkdir(exist_ok=True)
    replay.qa.eval(f"""
from pathlib import Path
work = Path({str(work)!r})
bpy.ops.mesh.primitive_cube_add(); bpy.context.object.name = 'AlphaCrate'
bpy.ops.wm.save_as_mainfile(filepath=str(work / 'Alpha Courtyard.mixar'))
bpy.ops.mesh.primitive_uv_sphere_add(); bpy.context.object.name = 'BetaGlobe'
bpy.ops.wm.save_as_mainfile(filepath=str(work / 'Beta Studio.mixar'))
bpy.ops.mesh.primitive_cone_add(); bpy.ops.ed.undo_push(message='edit')
result = True""")
    async with replay.session() as s:
        _, state, _ = await s.call("mixar_ui_observe", {"limit": 60})
        view = next(r for r in state["regions"] if r["area_type"] == "VIEW_3D" and r["region_type"] == "WINDOW")
        await s.call("mixar_ui_act", {"action": "press", "key": "S", "modifiers": {"oskey": True},
                                      "context": state["context"], "target": view["target"]})
        await asyncio.sleep(1)
        recent = replay.options.fixture / "profile" / "config" / "recent-files.txt"
        replay.check("ui_save_records_recent_project", recent.exists() and "Beta Studio" in recent.read_text())
        # An earlier session's history: Alpha was opened in the UI before.
        recent.write_text(recent.read_text().rstrip("\n") + "\n" + str(work / "Alpha Courtyard.mixar") + "\n")
        replay.qa.eval("bpy.ops.mesh.primitive_torus_add()\nbpy.ops.ed.undo_push(message='edit')\nresult=True")
        _, listed, _ = await s.call("mixar_projects")
        names = {p["name"]: p for p in listed["projects"]}
        replay.check("projects_listed_by_name_without_paths",
                     {"Alpha Courtyard", "Beta Studio"} <= set(names) and str(work) not in json.dumps(listed), listed)
        alpha = names["Alpha Courtyard"]["project"]
        result, payload, _ = await s.call("mixar_project_open", {"project": alpha})
        replay.check("unsaved_changes_need_the_users_choice",
                     result.is_error and payload["error_type"] == "unsaved_changes", payload)
        _, opened, _ = await s.call("mixar_project_open", {"project": alpha, "unsaved": "discard"})
        result, overview, _ = await s.call("scene_overview")
        roots = {root["name"] for root in overview["roots"]}
        replay.check("open_project_follows_into_the_file", opened["opened"] and "AlphaCrate" in roots, roots)
        _, again, _ = await s.call("mixar_project_open", {"project": alpha})
        replay.check("reopening_the_open_project_is_a_no_op", again["opened"] is False)
        await s.snap("project-opened.png")


async def reopen(replay):
    alpha = replay.options.fixture / "work" / "Alpha Courtyard.mixar"
    replay.qa.eval("bpy.ops.wm.save_mainfile()\nresult=True")
    async with replay.session() as s:
        _, before, _ = await s.call("mixar_ui_context")
        await asyncio.to_thread(replay.relaunch, alpha)
        result, overview, text = await s.call("scene_overview")
        replay.check("same_connection_follows_reopened_saved_scene",
                     not result.is_error and overview["active_object"] == "AlphaCrate", text[:200])
        _, after, _ = await s.call("mixar_ui_context")
        replay.check("still_bound_to_the_same_scene", after["bound_session"] == before["bound_session"])
        await asyncio.to_thread(replay.relaunch)
        result, _, text = await s.call("scene_overview")
        replay.check("unsaved_scene_gone_explains_choosing_an_app",
                     result.is_error and "was closed" in text and "mixar_ui_context" in text, text[:200])


async def run(options):
    replay = Replay(options)
    replay.ready(eligible=False)
    facts = replay.qa.eval("from mixar.config.config import get_server_url\nimport os\n"
                           "result={'sim':bpy.app.use_event_simulate,'qa':os.environ.get('MIXAR_QA')=='1',"
                           "'backend':get_server_url()}")
    if not facts["qa"] or facts["sim"] or not facts["backend"].startswith("http://127.0.0.1:"):
        raise RuntimeError("Run only in an isolated, normal-input loopback QA app")
    replay.qa.eval("result=list(bpy.ops.mixar.copy_mcp_setup(client='JSON'))")
    replay.qa.wait(NOTIFY_ELIGIBLE, timeout=60)
    for step in (interface_control, codex_images, file_new, projects, reopen):
        await step(replay)
    replay.evidence["ok"] = True
    replay.check("all", True)
    print(json.dumps({"ok": True, "evidence": str(replay.out / "recovery-verdict.json")}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--harness", type=Path, required=True)
    parser.add_argument("--port", type=int, default=4827)
    options = parser.parse_args()
    options.fixture = options.fixture.resolve()
    asyncio.run(run(options))


if __name__ == "__main__":
    main()
