# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replay native UI through installed MCP in a normal-input, isolated QA app.

Use e2e_backend.py --prepare/--serve and e2e_launch.py --normal-input first.
The QA harness prepares setup and asserts Blender state; all tested UI edits
travel through MCP and native events. Uses two disposable fixture credits.
Read the emitted PNGs before claiming visual acceptance.
"""

import argparse
import asyncio
import base64
import json
import os
from pathlib import Path
import sys
import time
import tomllib
from uuid import uuid4

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from e2e_scene import load_qa


async def run(options):
    qa = load_qa(options.harness, options.port)
    deadline = time.monotonic()+60
    while True:
        try:
            await asyncio.to_thread(qa.cmd, "ping")
            break
        except OSError:
            if time.monotonic() >= deadline:
                raise
            await asyncio.sleep(0.25)
    await asyncio.to_thread(qa.cmd, "wait_login", timeout=90)
    sys.path.insert(0, str(options.harness / "scenarios"))
    from startup_health import run as startup_health
    from lib import ensure_scenes_drawer
    health = await asyncio.to_thread(startup_health, qa)
    facts = qa.eval("from mixar.config.config import get_server_url\n"
                    "result={'simulation':bpy.app.use_event_simulate,'backend':get_server_url(),"
                    "'qa':__import__('os').environ.get('MIXAR_QA')=='1'}")
    assert facts["qa"] and not facts["simulation"], facts
    assert facts["backend"].startswith("http://127.0.0.1:"), facts
    setup = qa.eval("result={'copied':list(bpy.ops.mixar.copy_mcp_setup(client='CODEX')),"
                    "'config':bpy.context.window_manager.clipboard}")
    assert "FINISHED" in setup["copied"]
    # QA only establishes the user's single setup action, no controller bypass.
    await asyncio.to_thread(qa.wait,
        "__import__('mixar.modules.mcp_bridge.core.eligibility',fromlist=['valid']).valid()", timeout=45)
    evidence = {"normal_input": True, "setup": setup, "startup_health": health, "calls": []}
    env = {**os.environ, "MIXAR_MCP_DISCOVERY_DIR": str(options.fixture / "discovery")}
    configured = tomllib.loads(setup["config"])["mcp_servers"]["mixar"]
    installation = json.loads((options.fixture / "connector/installation.json").read_text())
    assert Path(installation["python"]).resolve() == options.python.resolve()
    assert Path(installation["script"]).resolve() == options.launcher.resolve()
    parameters = StdioServerParameters(command=configured["command"], args=configured["args"], env=env)
    async with stdio_client(parameters) as streams:
        async with ClientSession(*streams) as client:
            await client.initialize()
            listed = await client.list_tools()
            names = {t.name for t in listed.tools}
            assert {"mixar_ui_observe", "mixar_ui_act", "execute_bpy_script"} <= names
            evidence["tool_count"] = len(names)

            async def call(name, args, call_id=None, expect_error=False):
                identity = call_id or str(uuid4())
                entry = {"tool": name, "call_id": identity, "status": "submitted"}
                evidence["calls"].append(entry)
                (options.fixture / "ui-progress.json").write_text(json.dumps(evidence, indent=2))
                result = await client.call_tool(name, args, meta={"mixar/request-id": identity})
                entry.update(status="returned", error=result.is_error)
                (options.fixture / "ui-progress.json").write_text(json.dumps(evidence, indent=2))
                if result.is_error != expect_error:
                    raise AssertionError(str(result.content))
                return result

            async def observe(image_name=None):
                result = await call("mixar_ui_observe", {"image": bool(image_name), "limit": 200})
                if image_name:
                    block = next(b for b in result.content if b.type == "image")
                    (options.fixture / image_name).write_bytes(base64.b64decode(block.data))
                return result.structured_content["result"]

            async def press(key, *, identity=None, snapshot=None):
                state = snapshot or await observe()
                popup = next((t for t in state["targets"] if t.get("popup")), None)
                target = popup or next(r for r in state["regions"]
                                      if r["area_type"] == "VIEW_3D" and r["region_type"] == "WINDOW")
                args = {"action": "press", "key": key, "context": state["context"], "target": target["target"]}
                result = await call("mixar_ui_act", args, identity)
                return args, result

            await press("ESC")  # Dismiss startup splash through production native input.
            await asyncio.to_thread(ensure_scenes_drawer, qa)
            await observe("ui-before.png")
            protected = qa.eval("result={o.name:[v for row in o.matrix_world for v in row] for o in bpy.context.scene.objects}")
            name = "MCP_NATIVE_UI_"+uuid4().hex[:8]
            evidence["object"] = name
            create = "import bpy\nbpy.ops.mesh.primitive_cube_add(size=2, location=(0,0,0))\n"
            create += f"bpy.context.object.name={name!r}\nprint('__RESULT__'+ '{{\"success\": true}}')"
            await call("execute_bpy_script", {"code": create})
            await press("NUMPAD_PERIOD")
            await asyncio.sleep(0.7)  # Blender's native smooth-view transition.
            stale = await observe()
            await press("G")
            async with stdio_client(parameters) as other_streams:
                async with ClientSession(*other_streams) as other:
                    await other.initialize()
                    snapshot = (await other.call_tool("mixar_ui_observe", {})).structured_content["result"]
                    region = next(r for r in snapshot["regions"]
                                  if r["area_type"] == "VIEW_3D" and r["region_type"] == "WINDOW")
                    refused = await other.call_tool("mixar_ui_act", {"action": "press", "key": "ESC",
                        "context": snapshot["context"], "target": region["target"]})
                    assert refused.is_error and refused.structured_content["result"]["error_type"] == "ui_busy"
                    evidence["concurrent_controller_refused"] = True
            await press("X")
            identity = str(uuid4())
            args, first = await press("TWO", identity=identity)
            replay = await call("mixar_ui_act", args, identity)
            assert replay.structured_content["result"]["replayed"] is True
            await press("RET")
            state = qa.eval(f"o=bpy.data.objects[{name!r}]\nresult={{'location':list(o.location),'vertices':len(o.data.vertices)}}")
            assert abs(state["location"][0]-2) < 0.0001, state
            assert state["vertices"] == 8, state
            target = next(r for r in stale["regions"] if r["area_type"] == "VIEW_3D" and r["region_type"] == "WINDOW")
            rejected = await call("mixar_ui_act", {"action": "press", "key": "X",
                "context": stale["context"], "target": target["target"]}, expect_error=True)
            assert rejected.structured_content["result"]["error_type"] == "context_changed"
            followup = f"import bpy\no=bpy.data.objects[{name!r}]\no.scale.z=1.5\nprint('__RESULT__'+ '{{\"success\": true}}')"
            await call("execute_bpy_script", {"code": followup})
            state = qa.eval(f"o=bpy.data.objects[{name!r}]\nresult={{'location':list(o.location),'scale':list(o.scale)}}")
            assert abs(state["location"][0]-2) < 0.0001 and state["scale"][2] == 1.5, state
            await press("NUMPAD_PERIOD")
            await asyncio.sleep(0.7)
            framed = await observe()
            viewport = next(r for r in framed["regions"]
                            if r["area_type"] == "VIEW_3D" and r["region_type"] == "WINDOW")
            await call("mixar_ui_act", {"action": "scroll", "steps": -3,
                "context": framed["context"], "target": viewport["target"]})
            await observe("ui-after.png")
            evidence["state"] = state
            unchanged = qa.eval(f"result={{name:[v for row in bpy.data.objects[name].matrix_world for v in row] for name in {list(protected)!r}}}")
            assert unchanged == protected, {"before": protected, "after": unchanged}
            await call("mixar_ui_context", {"release": True})
            project = str((options.fixture / "ui-control.blend").resolve())
            qa.eval(f"bpy.ops.wm.save_as_mainfile(filepath={project!r}); result=True")
            qa.eval(f"bpy.ops.wm.open_mainfile(filepath={project!r}); result=True")
            reopened = qa.eval(f"o=bpy.data.objects[{name!r}]; result={{'location':list(o.location),'scale':list(o.scale)}}")
            assert reopened == state, reopened
            await asyncio.to_thread(qa.wait,
                "__import__('mixar.modules.mcp_bridge.core.eligibility',fromlist=['valid']).valid()", timeout=45)
            after_reopen = await observe("ui-reopened.png")
            evidence["mcp_available_after_reopen"] = bool(after_reopen["context"])
            evidence["save_reopen"] = {"method": "QA fixture operators", "state": reopened}
            evidence["protected_objects_unchanged"] = True
            evidence["replayed_without_duplicate_input"] = True
            evidence["stale_context_refused"] = True
    evidence["ok"] = True
    (options.fixture / "ui-verdict.json").write_text(json.dumps(evidence, indent=2))
    print(json.dumps({"ok": True, "evidence": str(options.fixture / "ui-verdict.json")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--harness", type=Path, required=True)
    parser.add_argument("--port", type=int, default=4827)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--launcher", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
