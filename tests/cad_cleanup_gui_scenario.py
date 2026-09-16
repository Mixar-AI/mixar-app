# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""No-credit CAD tool integration scenario for an isolated running Mixar QA app.

Run with QA_HARNESS=<harness root> and CAD_QA_CLIENT_ROOT=<client repo/staging>
using ordinary Python. Uses the same real tool implementation as the agent;
no provider calls, scene file replacement, or user preferences changes.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(os.environ["QA_HARNESS"]) / "scenarios"))
from lib import run_scenario


def run(qa):
    client_root = Path(os.environ.get("CAD_QA_CLIENT_ROOT", Path(__file__).resolve().parents[1]))
    out_dir = Path(os.environ.get("QA_SCENARIO_OUT", client_root / "build/cad-qa"))
    out_dir.mkdir(parents=True, exist_ok=True)
    setup = (
        "import sys\n"
        f"sys.path.insert(0, {str(client_root / 'tests')!r})\n"
        f"sys.path.insert(0, {str(client_root / 'src/scripts')!r})\n"
        "import cad_cleanup_blender_qa as cadqa\n"
        f"result = cadqa.run_geometry_checks({str(out_dir)!r}, isolated=True)\n"
    )
    result = qa.step("cad_geometry_and_lifecycle", qa.eval, setup)
    qa.step("frame_cad_result", qa.eval,
            "win = drv.main_window()\n"
            "area = next(a for a in win.screen.areas if a.type == 'VIEW_3D')\n"
            "region = next(r for r in area.regions if r.type == 'WINDOW')\n"
            "with bpy.context.temp_override(window=win, area=area, region=region):\n"
            "    bpy.ops.view3d.view_camera()\n"
            "result = {'camera_view': True}\n")
    qa.snap(str(out_dir / "cad-cleanup-viewport.png"))
    return result


if __name__ == "__main__":
    run_scenario("cad_cleanup_tool_lifecycle", run)
