# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replay that an AI app always gets every Mixar tool, against a real isolated app.

An AI app lists tools once, when it connects. The app saves the backend's tool
list while signed in, and the launcher lists it at once whatever state Mixar is
in; a call made too early says why, and the same session works once Mixar is
ready. Replays: the saved list appearing, connecting while Mixar is reopened,
the server connection dropping, and a second signed-out Mixar left open. Spends
no credits. Normal-input QA app from e2e_launch.py --normal-input.
"""

import argparse
import asyncio
from contextlib import AsyncExitStack
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
from uuid import uuid4

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import Implementation

from e2e_scene import load_qa

SCENE_TOOL = "execute_bpy_script"
NOTIFY_ELIGIBLE = "__import__('mixar.modules.mcp_bridge.core.eligibility',fromlist=['valid']).valid()"
WM = "bpy.context.window_manager"


class Replay:
    def __init__(self, options):
        self.options, self.fixture = options, options.fixture
        self.out = self.fixture / "availability"
        self.out.mkdir(exist_ok=True)
        self.qa = load_qa(options.harness, options.port)
        self.evidence = {"checks": {}}
        self.launcher = str(self.fixture / "connector" / "mixar-mcp")
        self.discovery = self.fixture / "discovery"
        self.env = {**os.environ, "MIXAR_MCP_DISCOVERY_DIR": str(self.discovery)}
        self.second = None

    def check(self, name, ok, detail=None):
        self.evidence["checks"][name] = {"ok": bool(ok), "detail": detail}
        (self.out / "availability-verdict.json").write_text(json.dumps(self.evidence, indent=2, default=str))
        print(("[scenario] OK   " if ok else "[scenario] FAIL ") + name, flush=True)
        if not ok:
            raise AssertionError(f"{name}: {detail}")

    def no_cold_start(self):
        """A fresh 'starting' marker stops the launcher from cold-starting the
        recorded installation (it would open the user's own profile)."""
        marker = self.fixture / "connector" / "starting"
        marker.touch()
        os.utime(marker)

    def records(self):
        found = []
        for path in self.discovery.glob("*.json"):
            try:
                record = json.loads(path.read_text())
                request = urllib.request.Request(f"http://127.0.0.1:{record['port']}/health",
                                                 headers={"Authorization": "Bearer " + record["token"]})
                found.append((record, json.load(urllib.request.urlopen(request, timeout=3))))
            except (OSError, ValueError, KeyError):
                continue
        return found

    def ready(self, qa=None, timeout=150):
        qa = qa or self.qa
        deadline = time.monotonic() + timeout
        while True:
            try:
                qa.cmd("ping")
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(1)
        qa.cmd("wait_login", timeout=120)

    def session(self, client="claude-code"):
        return _Session(self, client)


class _Session:
    def __init__(self, replay, client):
        self.replay, self.client = replay, client

    async def __aenter__(self):
        self.replay.no_cold_start()
        self._stack = AsyncExitStack()
        params = StdioServerParameters(command=self.replay.launcher, args=[], env=self.replay.env)
        streams = await self._stack.enter_async_context(stdio_client(params))
        self.mcp = await self._stack.enter_async_context(ClientSession(
            *streams, client_info=Implementation(name=self.client, version="1")))
        await self.mcp.initialize()
        return self

    async def __aexit__(self, *exc):
        await self._stack.aclose()

    async def tools(self):
        started = time.monotonic()
        names = {tool.name for tool in (await self.mcp.list_tools()).tools}
        return names, round(time.monotonic() - started, 1)

    async def call(self, name, args=None):
        result = await self.mcp.call_tool(name, args or {}, meta={"mixar/request-id": str(uuid4())})
        payload = (result.structured_content or {}).get("result", result.structured_content)
        text = " ".join(block.text for block in result.content if block.type == "text")
        return result, payload, text

    async def until_works(self, name="scene_overview", timeout=120):
        """Retry as an agent would; returns the messages seen before it worked."""
        deadline, seen = time.monotonic() + timeout, []
        while True:
            result, _, text = await self.call(name)
            if not result.is_error:
                return seen
            seen.append(text[:160])
            if time.monotonic() > deadline:
                raise AssertionError(f"{name} never worked: {seen[-3:]}")
            await asyncio.sleep(2)


def saved_tools(replay):
    try:
        return {t["name"] for t in json.loads((replay.fixture / "connector" / "tools.json").read_text())["tools"]}
    except (OSError, ValueError, KeyError):
        return set()


async def saved_list(replay):
    """Enabling MCP while signed in saves every backend tool for later sessions."""
    deadline = time.monotonic() + 60
    while SCENE_TOOL not in saved_tools(replay) and time.monotonic() < deadline:
        await asyncio.sleep(1)
    replay.check("signed_in_app_saves_the_tool_list", SCENE_TOOL in saved_tools(replay), len(saved_tools(replay)))


async def startup(replay):
    """The AI app connects right as Mixar is reopened: every tool at once, early
    calls say why, and the same session works once Mixar is ready."""
    replay.no_cold_start()  # Stands for "another AI app just started Mixar".
    command = [sys.executable, str(Path(__file__).with_name("e2e_launch.py")), str(replay.fixture), "--relaunch"]
    subprocess.run(command, check=True, capture_output=True, text=True)
    async with replay.session() as s:
        names, seconds = await s.tools()
        replay.check("startup_lists_every_tool_at_once", SCENE_TOOL in names and seconds < 5,
                     {"seconds": seconds, "count": len(names)})
        seen = await s.until_works()
        replay.evidence["startup_messages_before_ready"] = seen
        replay.check("startup_same_session_works_once_ready", True, seen[:3])
        _, context, _ = await s.call("mixar_ui_context")
        replay.check("startup_context_reports_available", context.get("scene_tools") == "available", context)
    replay.ready()
    replay.qa.wait(NOTIFY_ELIGIBLE, timeout=90)


async def second_app(replay):
    """A second, signed-out Mixar does not make the user choose or lose tools."""
    async with replay.session() as bound:
        _, first, _ = await bound.call("mixar_ui_context")
        replay.second = launch_second(replay)
        deadline = time.monotonic() + 150
        while len(replay.records()) < 2:
            if time.monotonic() > deadline:
                raise RuntimeError("The second app never published its relay")
            await asyncio.sleep(1)
        replay.evidence["two_apps"] = [h for _, h in replay.records()]
        async with replay.session() as s:
            names, seconds = await s.tools()
            replay.check("two_apps_still_list_scene_tools", SCENE_TOOL in names, {"seconds": seconds})
            _, context, _ = await s.call("mixar_ui_context")
            replay.check("two_apps_pick_the_signed_in_one_without_asking",
                         "instances" not in context and context.get("session_id") == first["session_id"], context)
            result, _, _ = await s.call("scene_overview")
            replay.check("two_apps_scene_tools_work", not result.is_error)
        result, _, _ = await bound.call("scene_overview")
        _, again, _ = await bound.call("mixar_ui_context")
        replay.check("an_open_session_stays_on_its_app",
                     not result.is_error and again.get("session_id") == first["session_id"], again)


def launch_second(replay):
    """A signed-out second Mixar sharing the fixture's discovery directory."""
    profile = replay.fixture / "profile-second"
    if profile.exists():
        shutil.rmtree(profile)
    for part in ("scripts/startup", "config/mixar"):
        (profile / part).mkdir(parents=True)
    shutil.copy(replay.options.harness / "qa_boot_startup.py", profile / "scripts/startup/qa_boot.py")
    fixture = json.loads((replay.fixture / "fixture.json").read_text())
    (profile / "config/mixar/mixar.json").write_text(json.dumps({
        "backend_url": fixture["backend_url"], "share_usage_data": False, "mcp_enabled": True, "ui_mode": "ai"}))
    marker = json.loads((replay.fixture / "app-process.json").read_text())
    env = dict(os.environ, MIXAR_QA="1", MIXAR_USER_RESOURCES=str(profile), MIXAR_QA_OUT=str(replay.out),
               MIXAR_QA_PORT=str(replay.options.second_port), MIXAR_MCP_DISCOVERY_DIR=str(replay.discovery),
               MIXAR_OPERATION_HISTORY_DIR=str(replay.fixture / "ophistory-second"))
    with (replay.fixture / "app-second.log").open("w") as log:
        return subprocess.Popen([marker["app"], "-p", "120", "120", "1280", "800", "--python",
                                 str(Path(marker["harness"]) / "driver/qa_server.py")],
                                env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)


async def server_drop(replay):
    """Mixar's server connection drops: every tool still listed, calls say
    "connecting", and the same session works once it is back."""
    replay.qa.eval("from mixar.modules.space_mixie_chat.core.connection_manager import get_connection_manager\n"
                   "get_connection_manager().disconnect()\nresult = True")
    try:
        await asyncio.sleep(1.5)
        async with replay.session() as s:
            names, seconds = await s.tools()
            replay.check("disconnected_still_lists_every_tool", SCENE_TOOL in names, {"seconds": seconds})
            result, _, text = await s.call("scene_overview")
            replay.check("disconnected_call_says_connecting", result.is_error and "connecting" in text, text[:200])
            _, context, _ = await s.call("mixar_ui_context")
            replay.check("disconnected_context_reports_connecting",
                         context.get("server_connected") is False and context.get("scene_tools") == "connecting",
                         context)
            replay.qa.eval("from mixar.modules.space_mixie_chat.core.connection_manager import get_connection_manager\n"
                           "result = get_connection_manager().reconnect()")
            await s.until_works()
            replay.check("reconnected_same_session_works", True)
    finally:
        replay.qa.eval("from mixar.modules.space_mixie_chat.core.connection_manager import get_connection_manager\n"
                       "cm = get_connection_manager()\nresult = cm.is_connected or cm.reconnect()")
    replay.qa.wait("__import__('mixar.modules.space_mixie_chat.core.connection_manager',fromlist=['x'])"
                   ".get_connection_manager().is_connected", timeout=60)


async def run(options):
    replay = Replay(options)
    replay.ready()
    facts = replay.qa.eval("from mixar.config.config import get_server_url\nimport os\n"
                           "result={'qa':os.environ.get('MIXAR_QA')=='1','backend':get_server_url()}")
    if not facts["qa"] or not facts["backend"].startswith("http://127.0.0.1:"):
        raise RuntimeError("Run only in an isolated loopback QA app")
    replay.qa.eval("result=list(bpy.ops.mixar.copy_mcp_setup(client='JSON'))")
    replay.qa.wait(NOTIFY_ELIGIBLE, timeout=60)
    try:
        for step in (saved_list, startup, server_drop, second_app):
            await step(replay)
    finally:
        if replay.second:
            replay.second.terminate()
    replay.evidence["ok"] = True
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
