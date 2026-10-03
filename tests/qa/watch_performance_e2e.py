# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replay watch Boolean/coordinate bottlenecks in one real Dev GUI process.

Run against an idle isolated QA app, e.g. --port 4791. --baseline deliberately
replays the old sequential native cuts first (a brief expected UI pause).
No Blender worker is launched. Leaves state asserts, timings and a screenshot.
"""
import argparse
import json
import math
from pathlib import Path
import sys


def main():
    repo = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=4791)
    parser.add_argument("--out", default="/tmp/mixar-watch-performance")
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--harness", default=str(repo.parent / "mixar-qa-harness"))
    args = parser.parse_args()
    sys.path.insert(0, str(Path(args.harness) / "scenarios"))
    from lib import QA
    qa = QA(port=args.port)
    root = Path(args.out)
    root.mkdir(parents=True, exist_ok=True)
    assert qa.status()["state"] == "IDLE"
    qa.eval("import os; assert os.environ.get('MIXAR_QA')=='1'; result=True")
    source = Path(__file__).with_name("watch_performance_probe.py").read_text()
    qa.eval("import importlib\nfrom mixar.modules.common.agent_execution import mesh_ops\n"
            "importlib.reload(mesh_ops)\n"
            "ns={'api':mesh_ops}\nexec(compile(" + repr(source) +
            ", 'watch_performance_probe', 'exec'),ns)\n"
            "bpy.app.driver_namespace['_qa_watch_perf']=ns\n"
            "assert bpy.data.scenes.get('QA_Watch_Performance') is None, 'use a fresh fixture scene'\n"
            "ns['previous_scene']=drv.main_window().scene\n"
            "drv.main_window().scene=bpy.data.scenes.new('QA_Watch_Performance')\nresult=True")
    results = {}
    try:
        for name, expression in (
            *(([("sequential", "boolean_case(api,False)")] if args.baseline else [])),
            ("batched", "boolean_case(api,True)"),
            ("coordinates", "coordinate_case(api)"),
            ("contracts", "contracts(api)"),
            ("fallback", "fallback_cases(api)"),
        ):
            results[name] = qa.cmd("eval", code=
                "ns=bpy.app.driver_namespace['_qa_watch_perf']\nresult=eval(" + repr(expression) + ",ns)",
                _sock_timeout=45)
            assert qa.cmd("eval", code="result=True", _sock_timeout=2)
            (root / "verdict.json").write_text(json.dumps(results, indent=2))
            print(name, json.dumps(results[name]), flush=True)
        if args.baseline:
            assert results["batched"]["seconds"] < results["sequential"]["seconds"], results
            assert math.isclose(results["batched"]["volume"], results["sequential"]["volume"],
                                rel_tol=1e-4), results
        coords = results["coordinates"]
        assert coords["bulk_seconds"] < coords["sequential_seconds"], results
        qa.eval("""
w=drv.main_window()
for obj in w.scene.objects:
    obj.select_set(True)
for area in w.screen.areas:
    if area.type=='VIEW_3D':
        region=next(r for r in area.regions if r.type=='WINDOW')
        with bpy.context.temp_override(window=w,area=area,region=region):
            bpy.ops.view3d.view_axis(type='TOP')
            bpy.ops.view3d.view_selected()
result=True
""")
        qa.cmd("snap", path=str(root / "drilled-plates.png"), area="VIEW_3D")
    finally:
        qa.eval("drv.main_window().scene=bpy.app.driver_namespace['_qa_watch_perf']['previous_scene']\nresult=True")


if __name__ == "__main__":
    main()
