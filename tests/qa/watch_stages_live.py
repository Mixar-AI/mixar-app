# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""One live UAT5 watch-hotspot regression; requires an idle isolated QA app.

Uses one billed agent turn. No Blender subprocess is started. Replay into a
fresh scene; --observe only monitors the already-submitted identical prompt.
The deterministic geometry oracle is watch_performance_e2e.py.
"""
import argparse
import json
from pathlib import Path
import sys
import time

PROMPT = (
    "Build a small editable mechanical-watch performance regression fixture. "
    "Make a silver annular mainplate, 34.7 mm outer diameter, 29.3 mm inner diameter "
    "and 0.8 mm thick, with 16 real through-holes of 0.68 mm diameter evenly spaced "
    "on a 32 mm pitch circle. Add 16 separate named silver screws near the holes "
    "and a separate black curved leather strap sample beside it. Prefix every "
    "new object QA_STAGE_. Use actual geometry and native materials, no asset "
    "search, image generation, downloads or studio rendering. This is specifically "
    "a test of in-process staged execution: use the steps argument of "
    "execute_workspace_script or execute_bpy_script with self-contained stages, "
    "batch all mainplate cutters through "
    "mixar.modules.common.agent_execution.mesh_ops.boolean_difference, and use "
    "read_positions/write_positions with NumPy for strap coordinate changes. "
    "Build using data APIs, keep each stage short, add bevels only after cuts, "
    "delete owned temporary cutters after success, and preserve separate screws. "
    "Print stage measurements and the solver receipt. Validate final geometry "
    "and frame the completed fixture. Proceed directly without questions."
)

HEARTBEAT = """
import time
state={'last':time.monotonic(), 'max_gap':0.0, 'ticks':0, 'running':True}
def tick(state=state, clock=time.monotonic):
    if not state['running']:return None
    now=clock()
    state['max_gap']=max(state['max_gap'],now-state['last'])
    state['last']=now
    state['ticks']+=1
    return .02
bpy.app.driver_namespace['_qa_watch_heartbeat']=state
bpy.app.timers.register(tick, first_interval=.02)
result=True
"""


def main():
    repo = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=4791)
    parser.add_argument("--out", default="/tmp/mixar-watch-stages-live")
    parser.add_argument("--observe", action="store_true")
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--harness", default=str(repo.parent / "mixar-qa-harness"))
    args = parser.parse_args()
    sys.path.insert(0, str(Path(args.harness) / "scenarios"))
    from lib import QA
    qa = QA(port=args.port)
    root = Path(args.out)
    root.mkdir(parents=True, exist_ok=True)
    qa.eval("import os; assert os.environ.get('MIXAR_QA')=='1'; result=True")
    assert qa.eval("from mixar.config.config import get_server_url; result=get_server_url()") == "https://uat5.mixar.app"
    if not args.observe:
        assert qa.status()["state"] == "IDLE"
        qa.eval("""
assert bpy.data.scenes.get('QA_Watch_Stages_Live') is None, 'use a fresh test scene'
w=drv.main_window()
from mixar.modules.space_mixie_chat.ui.operators.scene_tab_ops import new_scene_tab
w.scene=new_scene_tab('QA_Watch_Stages_Live')
a=next(a for a in w.screen.areas if a.type=='VIEW_3D')
with bpy.context.temp_override(window=w,area=a):
    bpy.ops.mixar.open_mixie()
result=True
""")
        qa.cmd("set_text", widget={"prop":"mixie_chat_input", "area_type":"AGENT_BUBBLE"},
               text=PROMPT, enter=False)
        qa.eval(HEARTBEAT)
        qa.click(op="MIXIE_CHAT_OT_send_message")
    assert qa.eval("result=next((m.text for m in reversed(drv.main_window().scene.mixie_chat_messages) "
                   "if m.sender=='USER'), '') == " + repr(PROMPT))
    (root / "prompt.txt").write_text(PROMPT + "\n")
    started = time.monotonic()
    observations = []
    while time.monotonic() - started < args.timeout:
        start = time.monotonic()
        record = {"elapsed": start - started}
        try:
            record.update(qa.cmd("status", _sock_timeout=5))
        except Exception as exc:
            record["error"] = str(exc)
        record["roundtrip"] = time.monotonic() - start
        observations.append(record)
        (root / "progress.json").write_text(json.dumps(observations, indent=2))
        if record.get("state") == "IDLE" and not record.get("busy"):
            break
        assert record.get("state") != "AWAITING_INPUT", "unexpected choice gate; left for inspection"
        time.sleep(2)
    else:
        raise TimeoutError("turn still running; left active for inspection")
    result = qa.eval("""
from mixar.modules.space_mixie_chat.core.connection_manager import get_connection_manager
s=drv.main_window().scene
objects=[o for o in s.objects if 'QA_STAGE_' in o.name]
meshes={o.data.name:o.data for o in objects if o.type=='MESH'}
invalid=[]
for mesh in meshes.values():
    probe=mesh.copy()
    try:
        if probe.validate(clean_customdata=False):invalid.append(mesh.name)
    finally:
        bpy.data.meshes.remove(probe)
result={'connected':bool(get_connection_manager().is_connected),
        'session':s.mixie_session_id, 'invalid_meshes':invalid,
        'objects':[{'name':o.name,'type':o.type,
                    'faces':len(o.data.polygons) if o.type=='MESH' else 0} for o in objects],
        'agent_text':next((m.text for m in reversed(s.mixie_chat_messages)
                          if m.sender=='AGENT' and m.text), '')}
""")
    result["elapsed"] = time.monotonic() - started
    result["heartbeat"] = qa.eval("s=bpy.app.driver_namespace.get('_qa_watch_heartbeat',{})\n"
                                   "s['running']=False\nresult=s")
    result["probe_failures"] = sum("error" in o for o in observations)
    result["max_probe_seconds"] = max(o["roundtrip"] for o in observations)
    (root / "verdict.json").write_text(json.dumps(result, indent=2))
    assert result["connected"] and result["objects"] and not result["invalid_meshes"], result
    screws = [o for o in result["objects"] if "screw" in o["name"].lower() and o["type"] == "MESH"]
    assert len(screws) == 16, screws
    qa.cmd("snap", path=str(root / "viewport.png"), area="VIEW_3D")
    scene_path = str(root / "fixture.mixar")
    qa.eval(f"result=str(bpy.ops.wm.save_as_mainfile(filepath={scene_path!r}, copy=True))")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
