# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Real desktop MCP scenario; run with a Python environment containing mcp==2.2.0.

Requires an isolated QA app using a loopback backend and exactly two test
credits. Exercises the actual Enable MCP control, official SDK stdio client,
scene mutation, duplicate recovery, failure refund and insufficient credits.
It spends only the two disposable local fixture credits; no hosted model call.
The verdict and PNGs need a human/agent visual review before claiming success.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import importlib.util
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

from mcp import Client, StdioServerParameters


def load_qa(harness, port):
    spec = importlib.util.spec_from_file_location("mixar_e2e_qa", harness / "scenarios/lib.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.QA(port=port)


def assert_scene(qa, name):
    return qa.eval(
        f"o = bpy.data.objects.get({name!r})\n"
        "result = {'names': [o.name for o in bpy.data.objects if o.name.startswith('MCP_QA_CUBE_')],\n"
        " 'exists': o is not None, 'type': o.type if o else None,\n"
        " 'vertices': len(o.data.vertices) if o else None,\n"
        " 'scale': list(o.scale) if o else None,\n"
        " 'rotation_z': o.rotation_euler.z if o else None,\n"
        " 'material': list(o.data.materials[0].diffuse_color) if o and o.data.materials else None,\n"
        " 'bevel': next(({'width': m.width, 'segments': m.segments} for m in o.modifiers if m.type == 'BEVEL'), None) if o else None,\n"
        " 'busy': bool(drv.main_window().scene.mixie_chat_is_busy)}"
    )


def assert_appearance(state):
    assert len(state["material"]) == 4
    assert all(abs(actual - expected) < 0.000001 for actual, expected in
               zip(state["material"], (0.08, 0.55, 0.16, 1.0))), state
    assert state["bevel"] and state["bevel"]["segments"] == 3, state
    assert abs(state["bevel"]["width"] - 0.12) < 0.000001, state


def enable_in_ui(qa, output):
    deadline = time.monotonic() + 45
    while True:
        try:
            qa.status()
            break
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.25)
    qa.cmd("wait_login", timeout=90)
    qa.wait("not drv.main_window().scene.mixie_chat_is_busy", timeout=30)
    safe = qa.eval(
        "import os\n"
        "from mixar.config.config import get_server_url\n"
        "result = {'qa': os.environ.get('MIXAR_QA') == '1',\n"
        " 'simulated': bpy.app.use_event_simulate, 'backend': get_server_url()}"
    )
    if not safe["qa"] or not safe["simulated"] or not safe["backend"].startswith(
        ("http://127.0.0.1:", "http://localhost:")
    ):
        raise RuntimeError("Run this credit-spending scenario only in an isolated loopback QA app")
    email = qa.eval("result = drv.main_window().scene.mixie_chat_user_id")
    qa.click(text=email, area_type="TOPBAR")
    qa.click(op="MIXAR_OT_connect_ai")
    qa.cmd("snap", path=str(output / "setup-before.png"))
    qa.click(op="MIXAR_OT_set_mcp_enabled")
    qa.wait(
        "__import__('mixar.modules.mcp_bridge.core.runtime', fromlist=['enabled']).enabled()",
        timeout=10,
    )
    qa.cmd("snap", path=str(output / "setup-enabled.png"))
    qa.press("ESC")
    if qa.find(op="MIXAR_OT_connect_ai", popup=True)["total"]:
        qa.press("ESC")
    qa.wait(
        "__import__('mixar.modules.mcp_bridge.core.runtime', fromlist=['snapshot']).snapshot().get('connected')",
        timeout=30,
    )


def cube_script(name):
    return f"""import bpy
bpy.ops.mesh.primitive_cube_add(size=2.0, location=(4.0, 0.0, 1.0))
obj = bpy.context.active_object
obj.name = {name!r}
mat = bpy.data.materials.new({(name + '_Green')!r})
mat.diffuse_color = (0.08, 0.55, 0.16, 1.0)
obj.data.materials.append(mat)
bevel = obj.modifiers.new('Soft edges', 'BEVEL')
bevel.width = 0.12
bevel.segments = 3
for area in bpy.context.screen.areas:
    if area.type == 'VIEW_3D':
        area.spaces.active.shading.type = 'SOLID'
        area.spaces.active.shading.color_type = 'MATERIAL'
        region = next(r for r in area.regions if r.type == 'WINDOW')
        with bpy.context.temp_override(area=area, region=region):
            bpy.ops.view3d.view_selected(use_all_regions=False)
        area.spaces.active.region_3d.view_distance *= 1.7
print('Created ' + obj.name)
"""


async def run(options, qa, verdict):
    await asyncio.to_thread(enable_in_ui, qa, options.out)
    server = StdioServerParameters(
        command=options.python, args=[str(options.launcher), "--qa-port", str(options.qa_port)],
        env={"MIXAR_MCP_DISCOVERY_DIR": str(options.discovery_dir)},
    )
    async with Client(server, mode="legacy", read_timeout_seconds=240) as client:
        tools, cursor = [], None
        while True:
            page = await client.list_tools(cursor=cursor)
            tools.extend(t.name for t in page.tools)
            cursor = page.next_cursor
            if not cursor:
                break
        required = {"execute_bpy_script", "render_viewport", "mixar_credit_balance",
                    "mixar_qa_status", "mixar_qa_find", "mixar_qa_snap",
                    "mixar_qa_click", "mixar_qa_press"}
        assert required <= set(tools), tools
        verdict["tool_count"] = len(tools)

        async def call(name, arguments=None, call_id=None, expect_error=False):
            result = await client.call_tool(
                name, arguments or {}, meta={"mixar/request-id": call_id or str(uuid4())}
            )
            payload = result.structured_content
            assert isinstance(payload, dict) and "usage" in payload, result
            verdict["calls"].append({"tool": name, "usage": payload["usage"], "is_error": result.is_error})
            assert result.is_error is expect_error, result.model_dump(by_alias=True)
            return result

        balance = await call("mixar_credit_balance")
        start = balance.structured_content["result"]["available_credits"]
        assert start == 2, "Use a fresh local QA fixture with exactly two credits"
        name = "MCP_QA_CUBE_" + uuid4().hex[:8]
        verdict["object_name"] = name
        create_id = str(uuid4())
        arguments = {"code": cube_script(name)}
        created = await call("execute_bpy_script", arguments, create_id)
        assert created.structured_content["usage"]["credits_charged"] == 1
        state = await asyncio.to_thread(assert_scene, qa, name)
        assert state["names"] == [name] and state["type"] == "MESH" and state["vertices"] == 8, state
        assert not state["busy"], state
        assert_appearance(state)
        verdict["created_state"] = state

        replay = await call("execute_bpy_script", arguments, create_id)
        assert replay.structured_content["usage"]["replayed"] is True
        assert replay.structured_content["usage"]["additional_credits_charged"] == 0
        assert (await asyncio.to_thread(assert_scene, qa, name))["names"] == [name]

        failed = await call("execute_bpy_script", {"code": "print(undefined_mcp_qa_variable)"}, expect_error=True)
        usage = failed.structured_content["usage"]
        assert usage["credits_refunded"] == 1 and usage["credits_charged"] == 0, usage
        assert usage["remaining_credits"] == 1, usage

        await call("execute_bpy_script", {"code": f"import bpy\nbpy.data.objects[{name!r}].rotation_euler.z = 0.35"})
        exhausted = await call("mixar_credit_balance")
        assert exhausted.structured_content["result"]["available_credits"] == 0
        rejected = await call("execute_bpy_script", {
            "code": f"import bpy\nbpy.data.objects[{name!r}].scale = (3, 3, 3)"
        }, expect_error=True)
        assert rejected.structured_content["usage"]["credits_charged"] == 0
        assert rejected.structured_content["result"].get("status_code") == 402

        invalid = await call("execute_bpy_script", {"code": 123}, expect_error=True)
        assert invalid.structured_content["usage"]["credits_charged"] == 0
        state = await asyncio.to_thread(assert_scene, qa, name)
        assert state["names"] == [name] and state["scale"] == [1.0, 1.0, 1.0], state
        assert abs(state["rotation_z"] - 0.35) < 0.001 and not state["busy"], state
        assert_appearance(state)
        verdict["final_state"] = state
        verdict["appearance_verified"] = True

        capture = await call("render_viewport", {
            "view": "hero", "focus_objects": [name], "include_touching": False,
            "width": 1024, "height": 768, "quality": "fast",
        })
        images = [block for block in capture.content if block.type == "image"]
        assert images, "MCP viewport tool must return a real image content block"
        for i, block in enumerate(images):
            suffix = ".png" if block.mime_type == "image/png" else ".jpg"
            (options.out / (f"mcp-viewport-{i}" + suffix)).write_bytes(base64.b64decode(block.data, validate=True))
        await asyncio.to_thread(qa.cmd, "snap", path=str(options.out / "desktop-result.png"))
        qa_status = await call("mixar_qa_status")
        verdict["qa_status"] = qa_status.structured_content["result"]
        found = await call("mixar_qa_find", {"query": {"text": "Help", "but_type": "Pulldown"}, "limit": 10})
        assert found.structured_content["result"]["total"] >= 1
        click_id = str(uuid4())
        click_args = {"target": {"text": "Help", "but_type": "Pulldown"}}
        await call("mixar_qa_click", click_args, click_id)
        menu_query = {"query": {"text": "Documentation", "popup": True}, "limit": 10}
        menu = await call("mixar_qa_find", menu_query)
        assert menu.structured_content["result"]["total"] == 1
        duplicate_click = await call("mixar_qa_click", click_args, click_id)
        assert duplicate_click.structured_content["usage"]["replayed"] is True
        menu_after_replay = await call("mixar_qa_find", menu_query)
        assert menu_after_replay.structured_content["result"]["total"] == 1
        menu_snap = await call("mixar_qa_snap")
        menu_images = [block for block in menu_snap.content if block.type == "image"]
        assert len(menu_images) == 1 and menu_images[0].mime_type == "image/png"
        (options.out / "mcp-qa-help-menu.png").write_bytes(base64.b64decode(menu_images[0].data, validate=True))
        await call("mixar_qa_press", {"key": "ESC"})
        closed_menu = await call("mixar_qa_find", menu_query)
        assert closed_menu.structured_content["result"]["total"] == 0
        snap = await call("mixar_qa_snap")
        qa_images = [block for block in snap.content if block.type == "image"]
        assert len(qa_images) == 1 and qa_images[0].mime_type == "image/png"
        (options.out / "mcp-qa-desktop.png").write_bytes(base64.b64decode(qa_images[0].data, validate=True))
        verdict["qa_tools_verified"] = ["mixar_qa_status", "mixar_qa_find", "mixar_qa_snap",
                                        "mixar_qa_click", "mixar_qa_press"]
        verdict["qa_action_replay_verified"] = True
        verdict["image_count"] = len(images)
        verdict["credits_used"] = 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qa-harness", type=Path, required=True)
    parser.add_argument("--qa-port", type=int, default=4777)
    parser.add_argument("--discovery-dir", type=Path, required=True)
    parser.add_argument("--launcher", type=Path, default=Path(__file__).resolve().parents[2] / "src/scripts/mixar/mcp.py")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--out", type=Path, required=True)
    options = parser.parse_args()
    options.out.mkdir(parents=True, exist_ok=True)
    qa = load_qa(options.qa_harness, options.qa_port)
    verdict = {"scenario": "mcp_scene_e2e", "ok": False, "calls": [], "started": time.time()}
    try:
        asyncio.run(run(options, qa, verdict))
        verdict["ok"] = True
    except Exception as exc:
        verdict["error"] = str(exc)
        raise
    finally:
        verdict["elapsed_seconds"] = round(time.time() - verdict["started"], 2)
        (options.out / "verdict.json").write_text(json.dumps(verdict, indent=2))
        print(json.dumps(verdict, indent=2))


if __name__ == "__main__":
    main()
