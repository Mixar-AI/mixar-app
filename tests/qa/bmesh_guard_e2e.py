# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replay: python3 tests/qa/bmesh_guard_e2e.py --port 4789.

Use a freshly built isolated QA Dev instance with MIXAR_QA_OUT set. Exercises
the actual ScriptExecutor and native geometry; leaves verdict.json/viewport.png.
No generation requests or credits. Only synthetic meshes are modified.
"""
import argparse
import json
from pathlib import Path
import sys


def main():
    repo = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=4789)
    parser.add_argument("--harness", default=str(repo.parent / "mixar-qa-harness"))
    args = parser.parse_args()
    sys.path.insert(0, str(Path(args.harness) / "scenarios"))
    from lib import QA
    qa = QA(port=args.port)
    root = qa.eval("import os; assert os.environ.get('MIXAR_QA') == '1'; result=os.environ['MIXAR_QA_OUT']")
    source = Path(__file__).with_name("bmesh_guard_probe.py").read_text()
    code = ("namespace={}\nexec(compile(" + repr(source) + ", 'bmesh_guard_probe', 'exec'), namespace)\n"
            "result=namespace['run']()")
    verdict = qa.cmd("eval", code=code, _sock_timeout=60)
    # A separate request proves the main loop services work after refusal/retry.
    assert qa.eval("result=bpy.data.objects.get('QA_ValidatedRiver') is not None")
    verdict["main_loop_responsive_after_repair"] = True
    qa.eval("""
window=drv.main_window()
obj=bpy.data.objects['QA_ValidatedRiver']
with bpy.context.temp_override(window=window):
    for other in bpy.context.scene.objects:
        other.select_set(False)
        other.hide_set(other != obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active=obj
    for area in window.screen.areas:
        if area.type == 'VIEW_3D':
            area.spaces.active.shading.color_type='MATERIAL'
            region=next(r for r in area.regions if r.type == 'WINDOW')
            with bpy.context.temp_override(area=area, region=region):
                bpy.ops.view3d.view_axis(type='TOP')
                bpy.ops.view3d.view_selected()
result=True
""")
    path = Path(root) / "verdict.json"
    path.write_text(json.dumps(verdict, indent=2) + "\n")
    qa.cmd("snap", path=str(Path(root) / "viewport.png"), area="VIEW_3D")
    print(json.dumps(verdict, indent=2))
    print("Evidence:", path)


if __name__ == "__main__":
    main()
