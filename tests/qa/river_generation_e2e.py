# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Live procedural river regression through Agent Bubble; uses one agent turn.

Run in an isolated QA Dev app configured for UAT5:
python3 tests/qa/river_generation_e2e.py --port 4789 --out /tmp/river-e2e
Uses backend model credits, no paid asset/image generation. --observe attaches
to an already-submitted identical prompt. Does not cancel/retry timed-out turns.
"""
import argparse
import json
from pathlib import Path
import sys
import time

PROMPT = (
    "Create a compact procedural mountain-valley scene for a mesh-cleanup regression test. "
    "Use a winding turquoise river, two green sloped terrain banks, and 40 small low-poly "
    "shoreline rocks sharing mesh data. The river should follow the banks and contain "
    "roughly 15000-30000 faces. Use procedural mesh geometry only, no asset search, "
    "downloads, image generation, textures or rendering. Put every new object under an "
    "empty named QA_RIVER_ROOT and prefix all new object names QA_RIVER_. Validate the "
    "generated geometry, remove any unwanted faces and loose vertices, and verify the "
    "final counts. Leave the finished scene visible. Proceed directly without asking "
    "for style choices."
)


def main():
    repo = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=4789)
    parser.add_argument("--out", default="/tmp/mixar-river-e2e")
    parser.add_argument("--observe", action="store_true")
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--harness", default=str(repo.parent / "mixar-qa-harness"))
    args = parser.parse_args()
    sys.path.insert(0, str(Path(args.harness) / "scenarios"))
    from lib import QA
    qa = QA(port=args.port)
    root = Path(args.out)
    root.mkdir(parents=True, exist_ok=True)
    qa.eval("import os; assert os.environ.get('MIXAR_QA') == '1'; result=True")
    if not args.observe:
        assert qa.status()["state"] == "IDLE"
        assert qa.eval("result=not any('QA_RIVER_' in o.name for o in bpy.data.objects)"), "use a fresh QA scene"
        qa.eval("""
window=drv.main_window()
area=next(a for a in window.screen.areas if a.type=='VIEW_3D')
with bpy.context.temp_override(window=window,area=area):
    bpy.ops.mixar.open_mixie()
result=True
""")
        qa.cmd("set_text", widget={"prop": "mixie_chat_input", "area_type": "AGENT_BUBBLE"},
               text=PROMPT, enter=False)
        qa.click(op="MIXIE_CHAT_OT_send_message")
    assert qa.eval(
        "result=next((m.text for m in reversed(drv.main_window().scene.mixie_chat_messages) "
        "if m.sender=='USER'), '') == " + repr(PROMPT)
    ), "the active turn must belong to this replay's prompt"
    (root / "prompt.txt").write_text(PROMPT + "\n")
    observations = []
    started = time.monotonic()
    while time.monotonic() - started < args.timeout:
        start = time.monotonic()
        status = qa.cmd("status", _sock_timeout=10)
        observations.append(dict(elapsed=time.monotonic() - started,
                                 roundtrip=time.monotonic() - start, **status))
        (root / "progress.json").write_text(json.dumps(observations, indent=2) + "\n")
        if status["state"] == "IDLE" and not status["busy"]:
            break
        assert status["state"] != "AWAITING_INPUT", "unexpected choice gate; inspect without auto-answering"
        time.sleep(2)
    else:
        raise TimeoutError("agent turn still running; left active for inspection")
    result = qa.cmd("eval", code="""
from mixar.modules.space_mixie_chat.core.connection_manager import get_connection_manager
from mixar.config.config import get_server_url
objects=[o for o in drv.main_window().scene.objects if 'QA_RIVER_' in o.name]
meshes={o.data.name:o.data for o in objects if o.type=='MESH'}
invalid=[]
for mesh in meshes.values():
    probe=mesh.copy()
    try:
        if probe.validate(clean_customdata=False):
            invalid.append(mesh.name)
    finally:
        bpy.data.meshes.remove(probe)
result={'backend':get_server_url(),'connected':bool(get_connection_manager().is_connected),
        'objects':[{'name':o.name,'type':o.type,'mesh':o.data.name if o.type=='MESH' else None,
                    'faces':len(o.data.polygons) if o.type=='MESH' else 0} for o in objects],
        'invalid_meshes':invalid,
        'last_agent_text':next((m.text for m in reversed(drv.main_window().scene.mixie_chat_messages)
                                if m.sender=='AGENT' and m.text), '')}
""", _sock_timeout=30)
    result["max_probe_roundtrip_seconds"] = max(o["roundtrip"] for o in observations)
    (root / "verdict.json").write_text(json.dumps(result, indent=2) + "\n")
    assert result["connected"] and result["objects"] and not result["invalid_meshes"], result
    rocks = [o for o in result["objects"] if o["type"] == "MESH" and "rock" in o["name"].lower()]
    assert len(rocks) == 40 and len({o["mesh"] for o in rocks}) == 1, rocks
    water = [o for o in result["objects"] if o["type"] == "MESH" and "water" in o["name"].lower()]
    assert any(15000 <= o["faces"] <= 30000 for o in water), water
    qa.eval("""
window=drv.main_window()
with bpy.context.temp_override(window=window):
    for obj in window.scene.objects:
        generated='QA_RIVER_' in obj.name
        obj.hide_set(not generated)
        obj.select_set(generated)
    for area in window.screen.areas:
        if area.type=='VIEW_3D':
            area.spaces.active.shading.color_type='MATERIAL'
            region=next(r for r in area.regions if r.type=='WINDOW')
            with bpy.context.temp_override(area=area,region=region):
                bpy.ops.view3d.view_axis(type='TOP')
                bpy.ops.view3d.view_selected()
result=True
""")
    qa.cmd("snap", path=str(root / "viewport.png"), area="VIEW_3D")
    scene_path = str(root / "river.mixar")
    qa.eval(f"result=str(bpy.ops.wm.save_as_mainfile(filepath={scene_path!r}, copy=True))")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
