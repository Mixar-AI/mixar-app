# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replay MCP usage attribution end to end: real AI-app sessions, real PostHog.

Normal-input QA app (e2e_launch.py --normal-input) on a disposable backend whose
fixture forwards telemetry to the configured PostHog project (events carry the
fixture's own user id and deployment_environment=development). Scene tools are
free (mcp_tool_call = 0, as migration f82c4e6d9a10 seeds it), so no credits move.

With ``--generation`` (fixture served with MIXAR_QA_JOB_QUEUE=1: jobs are
accepted, never dispatched, so no provider is called; two credits) it also
queues one image through MCP and one through the operator directly, and checks
generation.submitted says origin mcp and user respectively.

Checks: every backend tool call is one mcp.tool_called (surface backend) with the
AI app normalised from clientInfo; the local tools report surface desktop; the
connector's own input-release calls are not reported; turning Share Usage Data
off stops both; scene edits cost nothing. Reads PostHog with a personal API key
(``POSTHOG_PERSONAL_API_KEY``) through HogQL.
"""

import argparse
import asyncio
from contextlib import AsyncExitStack
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import time
import urllib.request
from uuid import uuid4

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import Implementation

from e2e_scene import load_qa

NOTIFY_ELIGIBLE = "__import__('mixar.modules.mcp_bridge.core.eligibility',fromlist=['valid']).valid()"
SET_TELEMETRY = "from mixar.modules.common.analytics.preferences import set_enabled\nresult = set_enabled({})"
CONSENT = ("__import__('mixar.modules.mcp_bridge.core.runtime', fromlist=['x'])"
           ".snapshot().get('headers', {}).get('x-telemetry-consent')")
FLUSH = ("import importlib\ncapture = importlib.import_module('mixar.modules.common.analytics.capture')\n"
         "capture._wake.set()\nresult = capture._events.qsize()")


class Replay:
    def __init__(self, options):
        self.options, self.fixture = options, options.fixture
        self.out = self.fixture / "usage"
        self.out.mkdir(exist_ok=True)
        self.qa = load_qa(options.harness, options.port)
        self.evidence = {"checks": {}}
        self.env = {**os.environ, "MIXAR_MCP_DISCOVERY_DIR": str(self.fixture / "discovery")}
        self.user_id = json.loads((self.fixture / "fixture.json").read_text())["user_id"]

    def check(self, name, ok, detail=None):
        self.evidence["checks"][name] = {"ok": bool(ok), "detail": detail}
        (self.out / "usage-verdict.json").write_text(json.dumps(self.evidence, indent=2, default=str))
        print(("[scenario] OK   " if ok else "[scenario] FAIL ") + name, flush=True)
        if not ok:
            raise AssertionError(f"{name}: {detail}")

    async def session(self, name, version):
        stack = AsyncExitStack()
        params = StdioServerParameters(command=str(self.fixture / "connector" / "mixar-mcp"), args=[], env=self.env)
        streams = await stack.enter_async_context(stdio_client(params))
        mcp = await stack.enter_async_context(
            ClientSession(*streams, client_info=Implementation(name=name, version=version)))
        await mcp.initialize()
        await mcp.list_tools()
        return stack, mcp

    def consent(self, enabled):
        self.qa.eval(SET_TELEMETRY.format(enabled))
        self.qa.wait(CONSENT + f" == {'1' if enabled else '0'!r}", timeout=20)

    def hogql(self, query):
        request = urllib.request.Request(
            f"{self.options.posthog_api.rstrip('/')}/api/projects/@current/query/",
            data=json.dumps({"query": {"kind": "HogQLQuery", "query": query}}).encode(),
            headers={"Authorization": "Bearer " + os.environ["POSTHOG_PERSONAL_API_KEY"],
                     "Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(request, timeout=60))["results"]

    def posthog(self, since):
        query = (
            "select event, properties.surface, properties.tool, properties.tool_kind, properties.status, "
            "properties.mcp_client, properties.mcp_client_version, properties.agent_source, "
            "properties.credits_charged, properties.deployment_environment, properties.scene_session_id "
            f"from events where distinct_id = '{self.user_id}' and event = 'mcp.tool_called' "
            f"and timestamp >= toDateTime('{since:%Y-%m-%d %H:%M:%S}', 'UTC') order by timestamp")
        results = self.hogql(query)
        keys = ("event", "surface", "tool", "tool_kind", "status", "client", "version", "agent_source",
                "credits", "environment", "scene_session")
        return [dict(zip(keys, row)) for row in results]


async def call(mcp, name, args=None):
    result = await mcp.call_tool(name, args or {}, meta={"mixar/request-id": str(uuid4())})
    payload = result.structured_content or {}
    return result, payload.get("result"), payload.get("usage") or {}


async def run(options):
    replay = Replay(options)
    replay.qa.cmd("wait_login", timeout=150)
    facts = replay.qa.eval("from mixar.config.config import get_server_url\nimport os\n"
                           "result={'qa':os.environ.get('MIXAR_QA')=='1','backend':get_server_url()}")
    if not facts["qa"] or not facts["backend"].startswith("http://127.0.0.1:"):
        raise RuntimeError("Run only in an isolated loopback QA app")
    replay.qa.eval("result=list(bpy.ops.mixar.copy_mcp_setup(client='JSON'))")
    replay.qa.wait(NOTIFY_ELIGIBLE, timeout=90)
    replay.consent(True)
    since = datetime.now(timezone.utc) - timedelta(seconds=5)

    stack, mcp = await replay.session("claude-code", "2.1.0")
    try:
        _, balance, _ = await call(mcp, "mixar_credit_balance")
        start = balance["available_credits"]
        await call(mcp, "mixar_guide")
        _, overview, _ = await call(mcp, "scene_overview")
        result, _, usage = await call(mcp, "execute_bpy_script", {
            "code": "import bpy\nbpy.ops.mesh.primitive_cube_add()\nbpy.context.object.name = 'MCP_USAGE_CUBE'\n"
                    "print(bpy.context.object.name)"})
        replay.check("scene_edit_is_free", not result.is_error and usage.get("credits_charged") == 0, usage)
        refused, _, _ = await call(mcp, "execute_bpy_script", {"code": 123})
        replay.check("schema_refusal_is_an_error", refused.is_error)
        await call(mcp, "mixar_scenes")
        await call(mcp, "mixar_ui_context")
        _, balance, _ = await call(mcp, "mixar_credit_balance")
        replay.check("credits_unchanged_after_edits", balance["available_credits"] == start,
                     {"before": start, "after": balance["available_credits"]})
    finally:
        await stack.aclose()
    stack, mcp = await replay.session("codex-mcp-client", "0.160.0")
    try:
        await call(mcp, "scene_overview")
    finally:
        await stack.aclose()

    replay.consent(False)  # Share Usage Data off: neither side may report.
    stack, mcp = await replay.session("claude-code", "2.1.0")
    try:
        await call(mcp, "scene_hierarchy")
        await call(mcp, "mixar_projects")
    finally:
        await stack.aclose()
    replay.consent(True)
    replay.qa.eval(FLUSH)

    expected = {"backend:mixar_credit_balance": 2, "backend:mixar_guide": 1,
                "backend:scene_overview": 2, "backend:execute_bpy_script": 2,
                "desktop:mixar_scenes": 1, "desktop:mixar_ui_context": 1}
    deadline, events = time.monotonic() + options.wait, []
    while time.monotonic() < deadline:
        events = replay.posthog(since)
        counts = {}
        for event in events:
            key = f"{event['surface']}:{event['tool']}"
            counts[key] = counts.get(key, 0) + 1
        if all(counts.get(key, 0) >= n for key, n in expected.items()):
            await asyncio.sleep(20)  # Late stragglers would be wrong extras.
            events = replay.posthog(since)
            break
        replay.qa.eval(FLUSH)
        await asyncio.sleep(10)
    replay.evidence["events"] = events
    counts = {}
    for event in events:
        key = f"{event['surface']}:{event['tool']}"
        counts[key] = counts.get(key, 0) + 1
    replay.check("every_call_reported_once_on_its_surface", counts == expected, counts)
    replay.check("all_tagged_mcp_in_development",
                 all(e["agent_source"] == "mcp" and e["environment"] == "development" for e in events))
    edits = [e for e in events if e["tool"] == "execute_bpy_script"]
    replay.check("edit_kind_status_and_free", sorted((e["tool_kind"], e["status"], e["credits"]) for e in edits) == [
        ("edit", "invalid_arguments", 0), ("edit", "ok", 0)], edits)
    clients = {(e["tool"], e["client"], e["version"]) for e in events if e["tool"] == "scene_overview"}
    replay.check("ai_app_normalised_with_version",
                 clients == {("scene_overview", "claude-code", "2.1.0"), ("scene_overview", "codex", "0.160.0")}, clients)
    kinds = {(e["tool"], e["tool_kind"]) for e in events}
    replay.check("tool_kinds", {("mixar_guide", "account"), ("scene_overview", "read"),
                                ("mixar_scenes", "scene_tab"), ("mixar_ui_context", "ui")} <= kinds, kinds)
    replay.check("desktop_events_name_the_ai_app",
                 all(e["client"] == "claude-code" for e in events if e["surface"] == "desktop"))
    replay.check("opt_out_reports_nothing",
                 not [e for e in events if e["tool"] in {"scene_hierarchy", "mixar_projects"}])
    if options.generation:
        await generation_origin(replay, since)
    replay.evidence["ok"] = True
    replay.check("all", True)


async def generation_origin(replay, since):
    stack, mcp = await replay.session("claude-code", "2.1.0")
    try:
        result, queued, _ = await call(mcp, "enqueue_generation", {"job_type": "image_gen", "params": {
            "prompt": "a small green cone on white", "model": "flash", "user_requested": True}})
        replay.check("mcp_generation_queued", not result.is_error and queued.get("dispatched"), queued)
    finally:
        await stack.aclose()
    await asyncio.sleep(5)  # The desktop submits asynchronously.
    replay.qa.eval("result=list(bpy.ops.mixie.imagegen_generate(prompt='a small yellow torus on white', model='flash'))")
    query = ("select properties.origin, properties.service from events where event = 'generation.submitted' "
             f"and distinct_id = '{replay.user_id}' and timestamp >= toDateTime('{since:%Y-%m-%d %H:%M:%S}', 'UTC') "
             "order by timestamp")
    deadline, rows = time.monotonic() + replay.options.wait, []
    while time.monotonic() < deadline and len(rows) < 2:
        rows = replay.hogql(query)
        await asyncio.sleep(10)
    replay.evidence["generations"] = rows
    replay.check("generation_origin_mcp_then_user", [r[0] for r in rows] == ["mcp", "user"], rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--harness", type=Path, required=True)
    parser.add_argument("--port", type=int, default=4827)
    parser.add_argument("--posthog-api", default="https://us.posthog.com")
    parser.add_argument("--wait", type=float, default=900)
    parser.add_argument("--generation", action="store_true",
                        help="Also check generation.submitted origin (fixture with MIXAR_QA_JOB_QUEUE=1)")
    options = parser.parse_args()
    options.fixture = options.fixture.resolve()
    asyncio.run(run(options))


if __name__ == "__main__":
    main()
