# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replay MCP response minimization against the real desktop and backend.

The model reads ``content`` and ``structuredContent``; the billing receipt rides
in ``_meta["mixar/usage"]`` alone. Through the real stdio launcher and the
official MCP SDK client this checks:

a. free backend and local tools show no request id, no ``Mixar usage:`` line
   and no Claude/Codex text; ``usage`` is ``{}`` where the tool declares an
   outputSchema; ``_meta`` holds the receipt with ``call_id`` only;
b. every structured result validates against the listed outputSchema AND the
   schema sessions cached before the change (``required: [result, usage]``);
c. a failed mutation shows ``usage {call_id, status}`` and ``mixar_call_status``
   answers the minimal shape;
d. refused calls (MCP switched off, backend stopped) are plain errors without a
   call id; a call whose answer is lost (backend killed mid-call) shows
   ``usage {call_id, status: "unknown"}`` and the recovery note;
e. a Codex session (clientInfo ``codex-mcp-client``) gets image results without
   structuredContent, and their text carries no ids either.

Event-simulate or normal-input QA app from e2e_launch.py on a disposable
backend from e2e_backend.py; run with the backend's Python (mcp==2.2.0 and
jsonschema). Scene tools are free: no credits move, no generation, no agent turn.
Step d SIGKILLs this fixture's own backend (PID fingerprint checked) and its
Redis, then restarts ``--serve`` on the same fixture.
"""

import argparse
import asyncio
from contextlib import AsyncExitStack
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time
from uuid import uuid4

import jsonschema
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import Implementation, PaginatedRequestParams

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e2e_scene import load_qa  # noqa: E402

OLD_SCHEMA = {"type": "object", "properties": {"result": {}, "usage": {"type": "object"}},
              "required": ["result", "usage"]}
FORBIDDEN = [re.compile(p) for p in (r"request_id", r"Mixar usage:", r"(?i)\bclaude\b", r"(?i)\bcodex\b")]
RUNTIME = "__import__('mixar.modules.mcp_bridge.core.runtime', fromlist=['x'])"
CONNECTED = ("__import__('mixar.modules.space_mixie_chat.core.connection_manager',fromlist=['x'])"
             ".get_connection_manager().is_connected")
STATUS_KEYS = {"call_id", "state", "tool", "status", "is_error",
               "credits_charged", "credits_refunded", "remaining_credits"}


def visible(result):
    """What the AI app's model reads: text blocks plus structuredContent."""
    texts = [block.text for block in result.content if block.type == "text"]
    if result.structured_content is not None:
        texts.append(json.dumps(result.structured_content))
    return "\n".join(texts)


def forbidden(text):
    return [p.pattern for p in FORBIDDEN if p.search(text)]


class Replay:
    def __init__(self, options):
        self.options, self.fixture = options, options.fixture
        self.out = options.out
        self.out.mkdir(parents=True, exist_ok=True)
        self.qa = load_qa(options.harness, options.port)
        self.evidence = {"checks": {}, "calls": []}
        self.backend_url = json.loads((self.fixture / "fixture.json").read_text())["backend_url"]
        self.backend_port = int(self.backend_url.rsplit(":", 1)[1])
        self.redis_port = int(json.loads((self.fixture / "backend-env.json").read_text())["REDIS_PORT"])
        self.schemas = {}

    def check(self, name, ok, detail=None):
        self.evidence["checks"][name] = {"ok": bool(ok), "detail": detail}
        self.save()
        print(("[scenario] OK   " if ok else "[scenario] FAIL ") + name, flush=True)
        if not ok:
            raise AssertionError(f"{name}: {json.dumps(detail, default=str)[:4000]}")

    def save(self):
        (self.out / "minimization-verdict.json").write_text(json.dumps(self.evidence, indent=2, default=str))

    async def session(self, stack, name, version):
        params = StdioServerParameters(command=self.options.python, args=[str(self.options.launcher)],
                                       env={"MIXAR_MCP_DISCOVERY_DIR": str(self.fixture / "discovery")})
        streams = await stack.enter_async_context(stdio_client(params))
        mcp = await stack.enter_async_context(ClientSession(
            *streams, client_info=Implementation(name=name, version=version)))
        await mcp.initialize()
        tools, cursor = [], None
        while True:
            page = await mcp.list_tools(params=PaginatedRequestParams(cursor=cursor) if cursor else None)
            tools.extend(page.tools)
            cursor = page.next_cursor
            if not cursor:
                return mcp, {t.name: t.output_schema for t in tools}

    async def call(self, mcp, name, args=None, call_id=None):
        call_id = call_id or str(uuid4())
        started = time.monotonic()
        result = await mcp.call_tool(name, args or {}, read_timeout_seconds=240,
                                     meta={"mixar/request-id": call_id})
        self.evidence["calls"].append({
            "tool": name, "call_id": call_id, "is_error": result.is_error,
            "seconds": round(time.monotonic() - started, 2),
            "structured": result.structured_content, "meta": result.meta,
            "text": [b.text[:600] for b in result.content if b.type == "text"],
            "images": sum(b.type == "image" for b in result.content)})
        self.save()
        return result, call_id

    # -- shared shape checks ---------------------------------------------------

    def assert_schemas(self, label, name, result, schemas):
        schema = schemas.get(name)
        sc = result.structured_content
        if schema is None:
            self.check(f"{label}:no_schema_usage_absent_or_empty",
                       sc is None or sc.get("usage", {}) == {}, sc)
            return
        errors = []
        for which, candidate in (("listed", schema), ("pre_minimization", OLD_SCHEMA)):
            try:
                jsonschema.validate(sc, candidate)
            except jsonschema.ValidationError as exc:
                errors.append(f"{which}: {exc.message}")
        self.check(f"{label}:validates_listed_and_old_schema", not errors, {"errors": errors, "sc": sc})

    def assert_free(self, label, name, result, call_id, schemas):
        text = visible(result)
        self.check(f"{label}:succeeded", not result.is_error, text[:1500])
        self.check(f"{label}:no_ids_receipt_or_ai_app_text",
                   not forbidden(text) and call_id not in text, {"hits": forbidden(text), "text": text[:1500]})
        sc = result.structured_content or {}
        if schemas.get(name) is not None:
            self.check(f"{label}:usage_is_empty", sc.get("usage") == {}, sc.get("usage"))
        else:
            self.check(f"{label}:no_usage_block", sc.get("usage", {}) == {}, sc.get("usage"))
        receipt = (result.meta or {}).get("mixar/usage")
        self.check(f"{label}:meta_receipt_has_call_id_only_ids",
                   isinstance(receipt, dict) and receipt.get("call_id") == call_id
                   and not {"request_id", "note"} & set(receipt), receipt)
        self.assert_schemas(label, name, result, schemas)

    def assert_refused(self, label, name, result, call_id, schemas):
        text = visible(result)
        sc = result.structured_content or {}
        self.check(f"{label}:is_error_without_call_id",
                   result.is_error and call_id not in text and sc.get("usage") == {}
                   and not forbidden(text), {"hits": forbidden(text), "text": text[:1500]})
        self.assert_schemas(label, name, result, schemas)

    # -- backend process control (this fixture's own processes only) ---------

    def kill_backend(self):
        record = json.loads((self.fixture / "backend-process.json").read_text())
        current = fingerprint(record["pid"])
        if not current or current != record["fingerprint"]:
            raise RuntimeError("Fixture backend marker is stale; refusing to signal another process")
        redis = owned_redis(self.redis_port, record["pid"])
        os.kill(record["pid"], signal.SIGKILL)  # A lost answer: no graceful shutdown.
        for pid in redis:
            os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 20
        while listening(self.backend_port) or listening(self.redis_port):
            if time.monotonic() > deadline:
                raise RuntimeError("Fixture backend or Redis did not stop")
            time.sleep(0.2)

    def start_backend(self):
        log = (self.fixture / "serve-restart.log").open("a")
        subprocess.Popen([self.options.backend_python, "tests/mcp/e2e_backend.py", "--serve", str(self.fixture),
                          "--port", str(self.backend_port)], cwd=self.options.backend_dir,
                         stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        deadline = time.monotonic() + 90
        while not listening(self.backend_port):
            if time.monotonic() > deadline:
                raise RuntimeError("Fixture backend did not restart")
            time.sleep(0.5)

    def wait_connected(self, connected, timeout=90):
        self.qa.wait(CONNECTED if connected else "not " + CONNECTED, timeout=timeout)


def fingerprint(pid):
    return subprocess.run(["ps", "-p", str(pid), "-o", "lstart=", "-o", "command="],
                          capture_output=True, text=True, check=False).stdout.strip()


def listening(port):
    with socket.socket() as probe:
        return probe.connect_ex(("127.0.0.1", port)) == 0


def owned_redis(port, backend_pid):
    """The fixture's redis-server: listens on its port and is the fixture backend's child."""
    pids = subprocess.run(["lsof", "-tiTCP:%d" % port, "-sTCP:LISTEN"], capture_output=True,
                          text=True, check=False).stdout.split()
    owned = []
    for pid in map(int, pids):
        command = fingerprint(pid)
        parent = subprocess.run(["ps", "-p", str(pid), "-o", "ppid="], capture_output=True,
                                text=True, check=False).stdout.strip()
        if "redis-server" not in command or parent != str(backend_pid):
            raise RuntimeError("Port %d is not this fixture's Redis: %s" % (port, command))
        owned.append(pid)
    return owned


async def free_calls(replay, mcp, schemas):
    """(a)+(b): free backend tools and the local tools."""
    backend = [("scene_overview", {}), ("mixar_status", {}), ("mixar_guide", {}),
               ("mixar_credit_balance", {}), ("scene_hierarchy", {}),
               ("mixar_tool_quote", {"tool": "execute_bpy_script"}),
               ("mixar_tool_catalog", {"query": "scene"})]
    local = [("mixar_scenes", {}), ("mixar_projects", {}), ("mixar_ui_context", {}),
             ("mixar_ui_call_status", {"call_id": str(uuid4())}),
             ("mixar_tool_quote", {"tool": "mixar_ui_observe"}),
             ("mixar_tool_catalog", {"domain": "scenes"})]
    missing = [n for n, _ in backend + local if n not in schemas]
    replay.check("tools_listed", not missing, missing)
    for name, args in backend + local:
        label = name + ("(local)" if (name, args) in local and name.startswith("mixar_tool") else "")
        result, call_id = await replay.call(mcp, name, args)
        if name == "mixar_ui_call_status":
            # An unknown UUID is a read; only the shape matters here.
            text = visible(result)
            replay.check(label + ":no_receipt_or_ai_app_text", not forbidden(text), text[:1500])
            replay.assert_schemas(label, name, result, schemas)
            continue
        replay.assert_free(label, name, result, call_id, schemas)


async def failed_mutation(replay, mcp, schemas):
    """(c): an edit that raises, then mixar_call_status on its UUID."""
    result, call_id = await replay.call(mcp, "execute_bpy_script",
                                        {"code": "raise RuntimeError('mcp minimization qa: deliberate failure')"})
    text, sc = visible(result), result.structured_content or {}
    usage = sc.get("usage") or {}
    replay.check("failed_edit:is_error", result.is_error, text[:1500])
    replay.check("failed_edit:usage_is_call_id_and_status_only",
                 usage.get("call_id") == call_id and set(usage) == {"call_id", "status"}, usage)
    # A recoverable outcome may repeat the minimal block as a text line for
    # text-only clients; it must be exactly that block, never the receipt.
    lines = [json.loads(line[len("Mixar usage: "):]) for line in text.splitlines()
             if line.startswith("Mixar usage: ")]
    replay.check("failed_edit:usage_text_line_is_the_minimal_block", all(line == usage for line in lines), lines)
    hits = [hit for hit in forbidden(text) if hit != "Mixar usage:"]
    replay.check("failed_edit:no_request_id_or_ai_app_text", not hits, {"hits": hits, "text": text[:1500]})
    receipt = (result.meta or {}).get("mixar/usage") or {}
    replay.check("failed_edit:meta_receipt", receipt.get("call_id") == call_id and receipt.get("credits_charged") == 0
                 and not {"request_id", "note"} & set(receipt), receipt)
    replay.assert_schemas("failed_edit", "execute_bpy_script", result, schemas)
    await call_status(replay, mcp, schemas, call_id, "failed_edit_status", expect_tool="execute_bpy_script")
    return call_id


async def call_status(replay, mcp, schemas, target, label, expect_tool=None):
    result, own_id = await replay.call(mcp, "mixar_call_status", {"call_id": target})
    text, sc = visible(result), result.structured_content or {}
    answer = sc.get("result") or {}
    replay.check(label + ":minimal_shape",
                 not result.is_error and answer.get("call_id") == target and set(answer) <= STATUS_KEYS
                 and "state" in answer and (expect_tool is None or answer.get("tool") == expect_tool),
                 answer)
    replay.check(label + ":no_receipt_or_ai_app_text",
                 not forbidden(text) and own_id not in text and sc.get("usage") == {},
                 {"hits": forbidden(text), "text": text[:1500]})
    replay.assert_schemas(label, "mixar_call_status", result, schemas)
    return answer


async def refused_and_lost(replay, mcp, schemas):
    """(d): refused before dispatch vs. an answer lost after dispatch."""
    qa = replay.qa
    # Refused: MCP switched off in Mixar (the launcher reads the manifest).
    qa.eval("result = list(bpy.ops.mixar.set_mcp_enabled(enabled=False))")
    qa.wait("not " + RUNTIME + ".enabled()", timeout=15)
    result, call_id = await replay.call(mcp, "scene_overview")
    replay.assert_refused("mcp_off", "scene_overview", result, call_id, schemas)
    replay.evidence["mcp_off_text"] = visible(result)[:800]
    qa.eval("result = list(bpy.ops.mixar.set_mcp_enabled(enabled=True))")
    qa.wait(RUNTIME + ".snapshot().get('connected')", timeout=60)
    result, call_id = await replay.call(mcp, "scene_overview")
    replay.assert_free("after_mcp_on:scene_overview", "scene_overview", result, call_id, schemas)

    # Lost answer: the backend dies while the desktop runs a dispatched edit.
    name = "MCP_MIN_LOST_" + uuid4().hex[:6]
    code = (f"import bpy, time\nmesh = bpy.data.meshes.new({name!r})\n"
            f"bpy.context.scene.collection.objects.link(bpy.data.objects.new({name!r}, mesh))\n"
            f"time.sleep({replay.options.hold})\nprint('held')")
    task = asyncio.create_task(replay.call(mcp, "execute_bpy_script", {"code": code}))
    await asyncio.sleep(replay.options.kill_after)
    killed_at = time.monotonic()
    replay.check("lost:call_still_pending_when_backend_killed", not task.done(), None)
    await asyncio.to_thread(replay.kill_backend)
    result, lost_id = await task
    replay.evidence["lost_seconds_after_kill"] = round(time.monotonic() - killed_at, 2)
    text, sc = visible(result), result.structured_content or {}
    replay.evidence["lost_text"] = text[:1500]
    replay.check("lost:usage_call_id_status_unknown",
                 result.is_error and sc.get("usage") == {"call_id": lost_id, "status": "unknown"}, sc)
    note = (sc.get("result") or {}).get("note") or ""
    replay.check("lost:recovery_note", "status" in note and "retry" in note, sc.get("result"))
    replay.check("lost:no_request_id_or_ai_app_text", not forbidden(text), {"hits": forbidden(text)})
    receipt = (result.meta or {}).get("mixar/usage") or {}
    replay.check("lost:meta_receipt_unknown", receipt.get("call_id") == lost_id
                 and receipt.get("status") == "unknown", receipt)
    replay.assert_schemas("lost", "execute_bpy_script", result, schemas)

    # Refused: the backend is gone and the desktop knows it ("connecting").
    await asyncio.to_thread(replay.wait_connected, False, 60)
    result, call_id = await replay.call(mcp, "scene_overview")
    replay.assert_refused("backend_down", "scene_overview", result, call_id, schemas)
    replay.evidence["backend_down_text"] = visible(result)[:800]

    await asyncio.to_thread(replay.start_backend)
    await asyncio.to_thread(replay.wait_connected, True, 120)
    qa.wait(RUNTIME + ".snapshot().get('connected')", timeout=60)
    exists = qa.eval(f"result = bpy.data.objects.get({name!r}) is not None")
    replay.evidence["lost_edit_ran_in_scene"] = exists
    answer = await call_status(replay, mcp, schemas, lost_id, "lost_status", expect_tool=None)
    replay.evidence["lost_status_answer"] = answer


async def codex(replay):
    """(e): Codex drops structuredContent for image results; the text stays id-free."""
    async with AsyncExitStack() as stack:
        mcp, schemas = await replay.session(stack, "codex-mcp-client", "0.160.0")
        replay.check("codex:no_output_schemas", not any(schemas.values()),
                     [n for n, s in schemas.items() if s][:10])
        result, call_id = await replay.call(mcp, "render_viewport", {
            "view": "hero", "width": 512, "height": 384, "quality": "fast"})
        text = visible(result)
        replay.check("codex:render_image_without_structured",
                     not result.is_error and result.structured_content is None
                     and any(b.type == "image" for b in result.content), text[:800])
        replay.check("codex:render_text_has_no_ids", not forbidden(text) and call_id not in text,
                     {"hits": forbidden(text), "text": text[:1500]})
        result, call_id = await replay.call(mcp, "scene_overview")
        text = visible(result)
        replay.check("codex:scene_overview_clean", not result.is_error and not forbidden(text)
                     and call_id not in text, {"hits": forbidden(text), "text": text[:1500]})


async def run(options):
    replay = Replay(options)
    qa = replay.qa
    qa.cmd("wait_login", timeout=150)
    facts = qa.eval("from mixar.config.config import get_server_url\nimport os\n"
                    "result={'qa':os.environ.get('MIXAR_QA')=='1','backend':get_server_url()}")
    if not facts["qa"] or facts["backend"] != replay.backend_url:
        raise RuntimeError("Run only in this fixture's isolated loopback QA app")
    if not qa.eval("result = " + RUNTIME + ".enabled()"):
        qa.eval("result = list(bpy.ops.mixar.set_mcp_enabled(enabled=True))")
    qa.wait(RUNTIME + ".snapshot().get('connected')", timeout=60)
    try:
        async with AsyncExitStack() as stack:
            mcp, schemas = await replay.session(stack, "claude-code", "2.1.0")
            replay.evidence["tool_count"] = len(schemas)
            replay.check("listed_schemas_require_only_result",
                         all(s.get("required") == ["result"] for s in schemas.values() if s),
                         sorted({json.dumps(s.get("required")) for s in schemas.values() if s}))
            await free_calls(replay, mcp, schemas)
            await failed_mutation(replay, mcp, schemas)
            if not options.skip_lost:
                await refused_and_lost(replay, mcp, schemas)
        await codex(replay)
        replay.evidence["ok"] = True
        replay.check("all", True)
    finally:
        try:
            qa.cmd("snap", path=str(replay.out / "minimization-final.png"))
        except Exception as exc:  # noqa: BLE001 - evidence only
            print("snap failed", exc)
        replay.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--harness", type=Path, required=True)
    parser.add_argument("--port", type=int, default=4797)
    parser.add_argument("--python", required=True, help="The app's embedded Python (runs the launcher)")
    parser.add_argument("--launcher", type=Path, required=True, help="The app's scripts/mixar/mcp.py")
    parser.add_argument("--backend-dir", type=Path, required=True, help="mixar-backend checkout serving the fixture")
    parser.add_argument("--backend-python", default=sys.executable)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--hold", type=float, default=8.0, help="Seconds the lost-answer edit keeps running")
    parser.add_argument("--kill-after", type=float, default=3.0, help="Seconds before the backend is killed")
    parser.add_argument("--skip-lost", action="store_true", help="Skip (d): no backend kill/restart")
    options = parser.parse_args()
    options.fixture = options.fixture.resolve()
    options.out = (options.out or options.fixture / "minimization").resolve()
    asyncio.run(run(options))


if __name__ == "__main__":
    main()
