# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replay the hard tool-list cases with the real thing, not simulations.

Complements e2e_tool_availability.py. Normal-input QA app (e2e_launch.py
--normal-input) on a disposable backend; spends no credits. Every tool is listed
at once from the list the app saved; calls made too early say why, and the same
session works once Mixar is ready. Covers: a real Sign out and Sign in (the
app's own operators); the backend process actually stopped and restarted; two
apps BOTH signed in (the user chooses, then the tools work); no saved list yet
(first use: local tools, then "reconnect"); and Mixar absent with MCP disabled
(answered at once, never cold-started). Saves a screenshot at each stage.
"""

import argparse
import asyncio
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time

from e2e_tool_availability import SCENE_TOOL, Replay as Base

NOTIFY_ELIGIBLE = "__import__('mixar.modules.mcp_bridge.core.eligibility',fromlist=['valid']).valid()"
WM = "bpy.context.window_manager"
CONNECTED = ("__import__('mixar.modules.space_mixie_chat.core.connection_manager',fromlist=['x'])"
             ".get_connection_manager().is_connected")


class Replay(Base):
    def __init__(self, options):
        super().__init__(options)
        self.out = self.fixture / "tool-list-live"
        self.out.mkdir(exist_ok=True)

    def check(self, name, ok, detail=None):
        self.evidence["checks"][name] = {"ok": bool(ok), "detail": detail}
        (self.out / "tool-list-verdict.json").write_text(json.dumps(self.evidence, indent=2, default=str))
        print(("[scenario] OK   " if ok else "[scenario] FAIL ") + name, flush=True)
        if not ok:
            raise AssertionError(f"{name}: {detail}")

    def snap(self, name, qa=None):
        try:
            (qa or self.qa).snap(str(self.out / name))
        except Exception as exc:  # noqa: BLE001 - evidence only
            print("snap failed", name, exc)

    def backend(self, start):
        if not start:
            record = json.loads((self.fixture / "backend-process.json").read_text())
            os.kill(record["pid"], signal.SIGINT)
            for _ in range(60):
                if not _listening(self.options.backend_port):
                    return
                time.sleep(0.5)
            raise RuntimeError("Fixture backend did not stop")
        log = (self.fixture / "serve-restart.log").open("a")
        subprocess.Popen([self.options.backend_python, "tests/mcp/e2e_backend.py", "--serve", str(self.fixture),
                          "--port", str(self.options.backend_port)], cwd=self.options.backend_dir,
                         stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        for _ in range(120):
            if _listening(self.options.backend_port):
                return
            time.sleep(0.5)
        raise RuntimeError("Fixture backend did not start")


def _listening(port):
    with socket.socket() as probe:
        return probe.connect_ex(("127.0.0.1", port)) == 0


async def context(s):
    _, payload, _ = await s.call("mixar_ui_context")
    return payload or {}


async def real_sign_out(replay):
    replay.qa.eval("result = list(bpy.ops.mixie_chat.logout())")
    replay.qa.wait(f"not {WM}.mixie_chat_is_logged_in", timeout=30)
    await asyncio.sleep(1.5)
    replay.snap("1-signed-out.png")
    async with replay.session() as s:
        names, seconds = await s.tools()
        replay.check("signed_out_lists_every_tool_at_once", SCENE_TOOL in names and seconds < 5,
                     {"seconds": seconds, "count": len(names)})
        result, _, text = await s.call("scene_overview")
        replay.check("signed_out_scene_call_says_sign_in", result.is_error and "Sign in to Mixar" in text, text[:160])
        state = await context(s)
        replay.check("signed_out_context", state.get("scene_tools") == "signed_out" and state.get("next_step"), state)
        replay.qa.eval("result = list(bpy.ops.mixie_chat.login())")
        replay.qa.wait(f"{WM}.mixie_chat_is_logged_in", timeout=90)
        seen = await s.until_works()
        replay.check("signed_in_same_session_works_without_reload", True, seen[-2:])
    replay.qa.wait(NOTIFY_ELIGIBLE, timeout=90)
    replay.snap("2-signed-in-again.png")


async def backend_stopped(replay):
    replay.backend(start=False)
    replay.qa.wait(f"not {CONNECTED}", timeout=60)
    await asyncio.sleep(1.5)
    replay.snap("3-backend-stopped.png")
    async with replay.session() as s:
        names, seconds = await s.tools()
        replay.check("backend_down_lists_every_tool", SCENE_TOOL in names and seconds < 10,
                     {"seconds": seconds, "count": len(names)})
        result, _, text = await s.call("scene_overview")
        replay.check("backend_down_call_says_connecting", result.is_error and "connecting" in text, text[:160])
        state = await context(s)
        replay.check("backend_down_context",
                     state.get("server_connected") is False and state.get("scene_tools") == "connecting", state)
        replay.backend(start=True)
        seen = await s.until_works(timeout=180)
        replay.check("backend_back_same_session_works", True, seen[-2:])
    replay.qa.wait(NOTIFY_ELIGIBLE, timeout=90)
    replay.snap("4-backend-back.png")


async def no_saved_list(replay):
    """First use: nothing saved yet and Mixar signed out. Local tools only, and
    once signed in the app saves the list and the agent is told to reconnect."""
    saved = replay.fixture / "connector" / "tools.json"
    replay.qa.eval("result = list(bpy.ops.mixie_chat.logout())")
    replay.qa.wait(f"not {WM}.mixie_chat_is_logged_in", timeout=30)
    saved.unlink(missing_ok=True)
    await asyncio.sleep(1.5)
    async with replay.session() as s:
        names, _ = await s.tools()
        replay.check("first_use_signed_out_lists_local_tools", SCENE_TOOL not in names and "mixar_ui_context" in names,
                     len(names))
        replay.qa.eval("result = list(bpy.ops.mixie_chat.login())")
        replay.qa.wait(f"{WM}.mixie_chat_is_logged_in", timeout=90)
        replay.qa.wait(NOTIFY_ELIGIBLE, timeout=90)
        deadline = time.monotonic() + 60
        while not saved.exists() and time.monotonic() < deadline:
            await asyncio.sleep(1)
        replay.check("sign_in_saves_the_list", saved.exists())
        state = await context(s)
        replay.check("first_use_context_says_reconnect",
                     state.get("scene_tools") == "reconnect" and "/mcp" in (state.get("next_step") or ""), state)
    async with replay.session() as s:
        names, _ = await s.tools()
        replay.check("reconnected_session_lists_every_tool", SCENE_TOOL in names, len(names))


def launch_signed_in_second(replay):
    profile = replay.fixture / "profile-second-signed-in"
    if profile.exists():
        shutil.rmtree(profile)
    for part in ("scripts/startup", "config/mixar", "datafiles/mixar"):
        (profile / part).mkdir(parents=True)
    shutil.copy(replay.options.harness / "qa_boot_startup.py", profile / "scripts/startup/qa_boot.py")
    fixture = json.loads((replay.fixture / "fixture.json").read_text())
    (profile / "datafiles/mixar/onboarding_seen.json").write_text(json.dumps({"users_seen": [fixture["username"]]}))
    (profile / "config/mixar/mixar.json").write_text(json.dumps({
        "backend_url": fixture["backend_url"], "share_usage_data": False, "mcp_enabled": True, "ui_mode": "ai",
        "dev_bypass": {"enabled": True, "username": fixture["username"], "password": fixture["password"]}}))
    marker = json.loads((replay.fixture / "app-process.json").read_text())
    env = dict(os.environ, MIXAR_QA="1", MIXAR_USER_RESOURCES=str(profile), MIXAR_QA_OUT=str(replay.out),
               MIXAR_QA_PORT=str(replay.options.second_port), MIXAR_MCP_DISCOVERY_DIR=str(replay.discovery),
               MIXAR_OPERATION_HISTORY_DIR=str(replay.fixture / "ophistory-second"))
    with (replay.fixture / "app-second-signed-in.log").open("w") as log:
        return subprocess.Popen([marker["app"], "-p", "140", "140", "1280", "800", "--python",
                                 str(Path(marker["harness"]) / "driver/qa_server.py")],
                                env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)


async def both_signed_in(replay):
    from e2e_scene import load_qa
    replay.second = launch_signed_in_second(replay)
    second = load_qa(replay.options.harness, replay.options.second_port)
    deadline = time.monotonic() + 180
    while True:
        live = replay.records()
        if len(live) >= 2 and all(h.get("signed_in") and h.get("connected") for _, h in live):
            break
        if time.monotonic() > deadline:
            raise RuntimeError(f"Second app never signed in: {[h for _, h in live]}")
        await asyncio.sleep(2)
    replay.evidence["both_apps"] = [h for _, h in replay.records()]
    replay.snap("5-first-app.png")
    replay.snap("5-second-app.png", qa=second)
    async with replay.session() as s:
        names, seconds = await s.tools()
        replay.check("both_signed_in_lists_every_tool_without_guessing", SCENE_TOOL in names and seconds < 5,
                     {"seconds": seconds, "count": len(names)})
        listing = await context(s)
        instances = listing.get("instances") or []
        replay.check("both_signed_in_user_is_asked_to_choose",
                     len(instances) == 2 and all(i["signed_in"] and i["connected"] for i in instances), listing)
        result, _, text = await s.call("scene_overview")
        replay.check("both_signed_in_scene_call_says_choose", result.is_error and "Several Mixar" in text, text[:160])
        first = next(r["instance_id"] for r, _ in replay.records() if r["pid"] != replay.second.pid)
        await s.call("mixar_ui_context", {"instance": first})
        result, _, text = await s.call("scene_overview")
        replay.check("choice_makes_scene_tools_work", not result.is_error, text[:160])
    try:
        second.cmd("quit")
    except Exception:  # noqa: BLE001
        pass
    replay.second.wait(timeout=60)
    replay.second = None


async def absent(replay):
    replay.qa.eval("result = list(bpy.ops.mixar.set_mcp_enabled(enabled=False))")
    await asyncio.sleep(2)
    installation = json.loads((replay.fixture / "connector" / "installation.json").read_text())
    replay.check("disabling_mcp_disables_cold_start", installation.get("enabled") is False, installation)
    subprocess.run([sys.executable, str(Path(__file__).with_name("e2e_launch.py")), str(replay.fixture), "--stop"],
                   check=True, capture_output=True)
    (replay.fixture / "connector" / "starting").unlink(missing_ok=True)
    env = {**replay.env}
    from contextlib import AsyncExitStack
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.types import Implementation
    async with AsyncExitStack() as stack:
        params = StdioServerParameters(command=replay.launcher, args=[], env=env)
        streams = await stack.enter_async_context(stdio_client(params))
        mcp = await stack.enter_async_context(
            ClientSession(*streams, client_info=Implementation(name="claude-code", version="1")))
        await mcp.initialize()
        started = time.monotonic()
        names = {tool.name for tool in (await mcp.list_tools()).tools}
        seconds = round(time.monotonic() - started, 1)
        replay.check("absent_lists_every_tool_at_once", SCENE_TOOL in names and seconds < 3,
                     {"seconds": seconds, "count": len(names)})
        result = await mcp.call_tool("scene_overview", {})
        text = " ".join(block.text for block in result.content if block.type == "text")
        replay.check("absent_scene_call_says_not_open", result.is_error and "not open" in text, text[:200])
    replay.check("absent_never_cold_started", not replay.records())


async def run(options):
    replay = Replay(options)
    replay.second = None
    replay.ready()
    facts = replay.qa.eval("from mixar.config.config import get_server_url\nimport os\n"
                           "result={'qa':os.environ.get('MIXAR_QA')=='1','backend':get_server_url()}")
    if not facts["qa"] or not facts["backend"].startswith("http://127.0.0.1:"):
        raise RuntimeError("Run only in an isolated loopback QA app")
    replay.qa.eval("result=list(bpy.ops.mixar.copy_mcp_setup(client='JSON'))")
    replay.qa.wait(NOTIFY_ELIGIBLE, timeout=60)
    try:
        for step in (real_sign_out, backend_stopped, both_signed_in, no_saved_list, absent):
            await step(replay)
    finally:
        if replay.second:
            replay.second.terminate()
    replay.evidence["ok"] = True
    replay.check("all", True)
    print(json.dumps({"ok": True, "evidence": str(replay.out)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--harness", type=Path, required=True)
    parser.add_argument("--port", type=int, default=4827)
    parser.add_argument("--second-port", type=int, default=4828)
    parser.add_argument("--backend-dir", type=Path, required=True, help="mixar-backend checkout serving the fixture")
    parser.add_argument("--backend-python", required=True)
    parser.add_argument("--backend-port", type=int, default=8017)
    options = parser.parse_args()
    options.fixture = options.fixture.resolve()
    asyncio.run(run(options))


if __name__ == "__main__":
    main()
