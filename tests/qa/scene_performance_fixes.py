# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replay: python3 tests/qa/scene_performance_fixes.py --port 4787.

Start a freshly built Dev app using the QA harness with an isolated profile and
MIXAR_QA_OUT. Requires sibling backend/harness checkouts (or CLI overrides).
Leaves results and a native viewport screenshot in the isolated evidence folder.
Uses synthetic stress assets, about 1 GB peak memory and 120 MB temporary disk.
No generation requests are submitted. The city fixture is optional; object-count
baseline and timings depend on the loaded scene. Review viewport.png after run.
"""
import argparse
import json
import sys
from pathlib import Path


def main():
    repo = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=4787)
    parser.add_argument("--backend", default=str(repo.parent / "mixar-backend"))
    parser.add_argument("--harness", default=str(repo.parent / "mixar-qa-harness"))
    args = parser.parse_args()
    sys.path.insert(0, str(Path(args.harness) / "scenarios"))
    from lib import QA
    qa = QA(port=args.port)
    root = qa.eval("import os; assert os.environ.get('MIXAR_QA') == '1'; result=os.environ.get('MIXAR_QA_OUT')")
    assert root, "Use an isolated QA app with MIXAR_QA_OUT set"
    source = Path(__file__).with_name("scene_performance_probe.py").read_text()
    code = ("namespace={}\nexec(compile(" + repr(source) + ", 'scene_performance_probe', 'exec'), namespace)\n"
            + "result=namespace['run'](" + repr(root) + ", " + repr(args.backend) + ")")
    result = qa.cmd("eval", code=code, _sock_timeout=180)
    # Exercise the complete backend template through the real safe executor,
    # including its private-workspace routing and idempotent merge path.
    fixture = Path(args.backend) / "tests/qa/workspace_rename_fixture.py"
    code = ("namespace={}\nexec(compile(" + repr(fixture.read_text())
            + ", 'workspace_rename_fixture', 'exec'), namespace)\n"
            + "window=drv.main_window()\nwindow.scene=bpy.data.scenes.new('QA_PerformanceWorkspace')\n"
            + "with bpy.context.temp_override(window=window):\n"
            + " result=namespace['run_fixture'](" + repr(args.backend) + ")['assertions']\n"
            + " for area in window.screen.areas:\n"
            + "  if area.type == 'VIEW_3D':\n"
            + "   region=next(r for r in area.regions if r.type == 'WINDOW')\n"
            + "   with bpy.context.temp_override(area=area, region=region):\n"
            + "    bpy.ops.view3d.view_all(center=False)\n")
    result["sandbox_workspace_merge"] = qa.cmd("eval", code=code, _sock_timeout=180)
    path = Path(root) / "performance-verdict.json"
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    qa.cmd("snap", path=str(Path(root) / "viewport.png"), area="VIEW_3D")
    print("Evidence:", path)


if __name__ == "__main__":
    main()
