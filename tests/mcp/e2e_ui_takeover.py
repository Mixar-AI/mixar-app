# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Verify OS input revokes MCP ownership in the isolated normal-input fixture.

Run after e2e_ui_control.py. When takeover-ready.json appears, send a real OS
Escape key to THIS fixture's Mixar window within 10 seconds, then create
takeover-done. Never use Window.event_simulate or the MCP injector for that key.
This spends no credits and cancels the temporary transform. The OS action must
be performed by the operator or a computer-use tool; its source is independent
of the system under test.
"""

import argparse
import asyncio
import json
import os
from pathlib import Path
import time
from uuid import uuid4

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from e2e_scene import load_qa


async def run(options):
    root = options.fixture
    qa = load_qa(options.harness, options.port)
    verdict = json.loads((root / "ui-verdict.json").read_text())
    name = verdict["object"]
    before = qa.eval(f"o=bpy.data.objects[{name!r}]; result={{'location':list(o.location),"
        "'active':bpy.context.view_layer.objects.active.name,'simulation':bpy.app.use_event_simulate}")
    assert before["active"] == name and not before["simulation"], before
    ready, done = root / "takeover-ready.json", root / "takeover-done"
    ready.unlink(missing_ok=True)
    done.unlink(missing_ok=True)
    env = {**os.environ, "MIXAR_MCP_DISCOVERY_DIR": str(root / "discovery")}
    parameters = StdioServerParameters(command=str(root / "connector/mixar-mcp"), args=[], env=env)
    async with stdio_client(parameters) as streams:
        async with ClientSession(*streams) as client:
            await client.initialize()

            async def observed_key(key, snapshot=None):
                if snapshot is None:
                    result = await client.call_tool("mixar_ui_observe", {})
                    assert not result.is_error, result.content
                    snapshot = result.structured_content["result"]
                target = next(r for r in snapshot["regions"]
                              if r["area_type"] == "VIEW_3D" and r["region_type"] == "WINDOW")
                return await client.call_tool("mixar_ui_act", {"action": "press", "key": key,
                    "context": snapshot["context"], "target": target["target"]},
                    meta={"mixar/request-id": str(uuid4())})

            for key in ("G", "X"):
                result = await observed_key(key)
                assert not result.is_error, result.content
            snapshot = (await client.call_tool("mixar_ui_observe", {})).structured_content["result"]
            state = qa.eval("from mixar.modules.common.ui_control.core import ownership; "
                "result={'owned':ownership.active(),'generation':bpy.context.window_manager.mixar_ui_generation()}")
            assert state["owned"]
            started = time.monotonic()
            ready.write_text(json.dumps({"generation": state["generation"], "ready_monotonic": started}))
            while not done.exists():
                if time.monotonic()-started > 10:
                    raise RuntimeError("OS takeover was not delivered before the test deadline; no takeover claim")
                await asyncio.sleep(0.05)
            elapsed = time.monotonic()-started
            assert elapsed < 10  # Below the native lease's 15-second expiry.
            after = qa.eval(f"from mixar.modules.common.ui_control.core import ownership; o=bpy.data.objects[{name!r}]; "
                "result={'owned':ownership.active(),'generation':bpy.context.window_manager.mixar_ui_generation(),"
                "'location':list(o.location)}")
            assert not after["owned"] and after["generation"] != state["generation"], after
            assert after["location"] == before["location"], after
            stale = await observed_key("TWO", snapshot)
            assert stale.is_error and stale.structured_content["result"]["error_type"] == "context_changed"
            result = {"ok": True, "normal_input": True, "physical_input_seconds": elapsed,
                      "before": before, "after": after, "stale_input_refused": True,
                      "os_input": "Escape delivered independently of MCP and QA event simulation"}
            (root / "takeover-verdict.json").write_text(json.dumps(result, indent=2))
            print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--harness", type=Path, required=True)
    parser.add_argument("--port", type=int, default=4827)
    asyncio.run(run(parser.parse_args()))
