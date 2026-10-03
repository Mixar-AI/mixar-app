# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replay when an AI app gets Mixar's scene tools, against a real isolated app.

An AI app lists tools once while it starts. This replays the timings users hit:
the AI app connecting while Mixar is still starting, while it is signed out, with
a second signed-out Mixar open, and while Mixar's server connection is down.
Spends no credits (only free inspection tools are called). Normal-input QA app
from e2e_launch.py --normal-input; the harness only prepares state and asserts.
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
        self.replay, self.client, self.changed = replay, client, None

    async def __aenter__(self):
        self.replay.no_cold_start()
        self.changed = asyncio.Event()

        async def on_message(message):
            if getattr(message, "method", "") == "notifications/tools/list_changed":
                self.changed.set()

        self._stack = AsyncExitStack()
        params = StdioServerParameters(command=self.replay.launcher, args=[], env=self.replay.env)
        streams = await self._stack.enter_async_context(stdio_client(params))
        self.mcp = await self._stack.enter_async_context(ClientSession(
            *streams, client_info=Implementation(name=self.client, version="1"), message_handler=on_message))
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

    async def wait_changed(self, timeout):
        try:
            await asyncio.wait_for(self.changed.wait(), timeout)
            return True
        except TimeoutError:
            return False


async def startup(replay):
    """The AI app connects right as Mixar is reopened, before its relay exists:
    a start in progress is waited for (bounded), then the session catches up."""
    replay.no_cold_start()  # Stands for "another AI app just started Mixar".
    command = [sys.executable, str(Path(__file__).with_name("e2e_launch.py")), str(replay.fixture), "--relaunch"]
    subprocess.run(command, check=True, capture_output=True, text=True)
    async with replay.session() as s:
        names, seconds = await s.tools()
        replay.evidence["startup"] = {"list_seconds": seconds, "scene_tools_in_first_list": SCENE_TOOL in names,
                                      "health_after_list": [h for _, h in replay.records()]}
        replay.check("startup_list_answered_within_bounded_wait", seconds <= 15, seconds)
        if SCENE_TOOL not in names:  # Mixar took longer than the wait: the session catches up.
            replay.check("startup_late_tools_announced", await s.wait_changed(120))
            names, _ = await s.tools()
        replay.check("startup_session_gets_scene_tools", SCENE_TOOL in names,
                     {"seconds": seconds, "count": len(names)})
        _, context, _ = await s.call("mixar_ui_context")
        replay.check("startup_context_reports_available",
                     context.get("scene_tools") == "available" and context.get("signed_in") is True, context)
    replay.ready()
    replay.qa.wait(NOTIFY_ELIGIBLE, timeout=90)


async def signed_out(replay):
    """Signed out: answered at once with local tools, then the tools arrive."""
    replay.qa.eval(f"{WM}.mixie_chat_is_logged_in = False\nresult = True")
    await asyncio.sleep(1.5)  # The relay snapshot ticks.
    try:
        async with replay.session() as s:
            names, seconds = await s.tools()
            replay.check("signed_out_answers_at_once_without_scene_tools",
                         SCENE_TOOL not in names and "mixar_ui_context" in names and seconds < 5,
                         {"seconds": seconds, "count": len(names)})
            result, _, text = await s.call("scene_overview")
            replay.check("signed_out_scene_call_says_sign_in", result.is_error and "Sign in" in text, text[:200])
            replay.qa.eval(f"{WM}.mixie_chat_is_logged_in = True\nresult = True")
            await asyncio.sleep(1.5)
            started = time.monotonic()
            _, context, _ = await s.call("mixar_ui_context")
            replay.check("signed_in_context_reports_loading", context.get("scene_tools") in {"loading", "available"},
                         context)
            replay.check("signed_in_tools_announced", await s.wait_changed(15),
                         round(time.monotonic() - started, 1))
            names, _ = await s.tools()
            replay.check("signed_in_session_gets_scene_tools", SCENE_TOOL in names, len(names))
            _, context, _ = await s.call("mixar_ui_context")
            replay.check("context_reports_available_after_reload", context.get("scene_tools") == "available",
                         context)
    finally:
        replay.qa.eval(f"{WM}.mixie_chat_is_logged_in = True\nresult = True")


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
    """Mixar's server connection is down: discovery works, calls say why."""
    replay.qa.eval("from mixar.modules.space_mixie_chat.core.connection_manager import get_connection_manager\n"
                   "get_connection_manager().disconnect()\nresult = True")
    try:
        await asyncio.sleep(1.5)
        async with replay.session() as s:
            names, seconds = await s.tools()
            replay.check("disconnected_still_lists_scene_tools", SCENE_TOOL in names, {"seconds": seconds})
            result, _, text = await s.call("scene_overview")
            replay.check("disconnected_call_says_connecting", result.is_error and "connecting" in text, text[:200])
            _, context, _ = await s.call("mixar_ui_context")
            replay.check("disconnected_context_reports_connecting",
                         context.get("server_connected") is False and context.get("scene_tools") == "connecting",
                         context)
    finally:
        replay.qa.eval("from mixar.modules.space_mixie_chat.core.connection_manager import get_connection_manager\n"
                       "result = get_connection_manager().reconnect()")
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
        for step in (startup, signed_out, server_drop, second_app):
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
