# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replay related topology failures and dense deletion workloads.

First: python3 tests/qa/bmesh_stress_e2e.py --headless --out /tmp/bmesh-stress
Then, with an isolated QA Dev app: python3 tests/qa/bmesh_stress_e2e.py --port 4789
Optional old-path reproduction: add --baseline (disposable child, 15s deadline).
Each headless process has a hard 30s deadline. GUI replay checks the main loop
after EVERY case and captures the repaired river. No generation requests.
"""
import argparse
import ast
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    repo = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--out", default="/tmp/mixar-bmesh-stress")
    parser.add_argument("--port", type=int, default=4789)
    parser.add_argument("--binary", default=str(repo / "build/Dev/bin/Mixar.app/Contents/MacOS/Mixar"))
    parser.add_argument("--harness", default=str(repo.parent / "mixar-qa-harness"))
    args = parser.parse_args()
    source = Path(__file__).with_name("bmesh_stress_probe.py")
    cases = next(ast.literal_eval(n.value) for n in ast.parse(source.read_text()).body
                 if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "CASES" for t in n.targets))
    root = Path(args.out)
    root.mkdir(parents=True, exist_ok=True)
    results = []
    if args.baseline:
        wrapper = root / "baseline_child.py"
        wrapper.write_text(f"import runpy\nrunpy.run_path({str(source)!r})['unguarded_repro']()\n")
        with (root / "baseline.log").open("w") as output:
            try:
                process = subprocess.run(
                    [args.binary, "-b", "--factory-startup", "--python-exit-code", "1",
                     "--python", str(wrapper)],
                    env={**os.environ, "MIXAR_QA_UNGUARDED_REPRO": "1",
                         "MIXAR_USER_RESOURCES": str(root / "baseline-profile")},
                    stdout=output, stderr=subprocess.STDOUT, timeout=15,
                )
                result = dict(exit=process.returncode, timed_out=False)
            except subprocess.TimeoutExpired:
                result = dict(timed_out=True, deadline_seconds=15)
        (root / "baseline-verdict.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))
        return
    if args.headless:
        wrapper = root / "child.py"
        wrapper.write_text(
            "import json,sys,runpy\nfrom pathlib import Path\n"
            "name=sys.argv[sys.argv.index('--')+1]\n"
            f"ns=runpy.run_path({str(source)!r})\n"
            "result=ns['run_case'](name)\n"
            f"Path({str(root)!r}+'/'+name+'.json').write_text(json.dumps(result))\n")
        for name in cases:
            path = root / (name + ".json")
            path.unlink(missing_ok=True)
            with (root / (name + ".log")).open("w") as output:
                try:
                    process = subprocess.run(
                        [args.binary, "-b", "--factory-startup", "--python-exit-code", "1",
                         "--python", str(wrapper), "--", name],
                        env={**os.environ, "MIXAR_USER_RESOURCES": str(root / "headless-profile")},
                        stdout=output, stderr=subprocess.STDOUT, timeout=30,
                    )
                    result = (json.loads(path.read_text()) if process.returncode == 0
                              else dict(case=name, failed=True, exit=process.returncode))
                except subprocess.TimeoutExpired:
                    result = dict(case=name, failed=True, timeout=30)
            results.append(result)
            print(json.dumps(result), flush=True)
        output = root / "headless-verdict.json"
    else:
        sys.path.insert(0, str(Path(args.harness) / "scenarios"))
        from lib import QA
        qa = QA(port=args.port)
        qa.eval("import os; assert os.environ.get('MIXAR_QA') == '1'; result=True")
        qa.eval("_mesh_stress={}\nexec(compile(" + repr(source.read_text()) +
                ", 'bmesh_stress_probe', 'exec'), _mesh_stress)\nbpy.app.driver_namespace['_mixar_stress_fixture']=_mesh_stress\nresult=True")
        for name in cases:
            result = qa.cmd("eval", code=f"result=bpy.app.driver_namespace['_mixar_stress_fixture']['run_case']({name!r})",
                            _sock_timeout=30)
            assert qa.cmd("eval", code="result=True", _sock_timeout=5)
            result["main_loop_responsive"] = True
            results.append(result)
            print(json.dumps(result), flush=True)
        qa.eval("""
for obj in list(bpy.data.objects):
    if obj.name == 'QA_RepairedClippedRiver':
        old=obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if old.users == 0:
            bpy.data.meshes.remove(old)
mesh, invalid, extra = bpy.app.driver_namespace['_mixar_stress_fixture']['build']('clipped_repaired')
assert not mesh.validate(clean_customdata=False)
obj=bpy.data.objects.new('QA_RepairedClippedRiver', mesh)
window=drv.main_window()
window.scene.collection.objects.link(obj)
material=bpy.data.materials.get('QA_StressWater') or bpy.data.materials.new('QA_StressWater')
material.diffuse_color=(.025,.39,.46,1)
mesh.materials.append(material)
with bpy.context.temp_override(window=window):
    for other in window.scene.objects:
        other.hide_set(other != obj)
        other.select_set(False)
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
        qa.cmd("snap", path=str(root / "river-viewport.png"), area="VIEW_3D")
        output = root / "gui-verdict.json"
    output.write_text(json.dumps(results, indent=2) + "\n")
    assert all(not result.get("failed") for result in results)
    print("Evidence:", output)


if __name__ == "__main__":
    main()
