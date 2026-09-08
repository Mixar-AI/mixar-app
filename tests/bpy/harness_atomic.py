# SPDX-License-Identifier: GPL-3.0-or-later
"""Run with Mixar --factory-startup --python this_file (isolated profile).

Tests the working-tree executor in a real Blender context, without a backend
or paid model. Exits after writing its verdict under MIXAR_HARNESS_QA_OUT.
"""

import json
import logging
import os
import sys
import types
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2] / "src/scripts/mixar"
for name, path in [
    ("mixar", ROOT),
    ("mixar.modules", ROOT / "modules"),
    ("mixar.modules.space_mixie_chat", ROOT / "modules/space_mixie_chat"),
    ("mixar.modules.space_mixie_chat.core", ROOT / "modules/space_mixie_chat/core"),
]:
    pkg = types.ModuleType(name)
    pkg.__path__ = [str(path)]
    sys.modules[name] = pkg
log = types.ModuleType("mixar.config.logging_config")
log.get_logger = logging.getLogger
sys.modules["mixar.config.logging_config"] = log
for key in list(sys.modules):
    if key.startswith("mixar.modules.space_mixie_chat.core."):
        del sys.modules[key]
from mixar.modules.space_mixie_chat.core.executor import ScriptExecutor


def run():
    out = Path(os.environ.get("MIXAR_HARNESS_QA_OUT", "/tmp/mixar-harness-qa"))
    out.mkdir(parents=True, exist_ok=True)
    result = {"passed": False}
    try:
        bpy.context.preferences.edit.use_global_undo = True
        executor = ScriptExecutor()
        before = set(bpy.data.objects.keys())
        if not bpy.app.background:
            bpy.ops.screen.screenshot(filepath=str(out / "before.png"))
        r = executor.execute(
            "bpy.ops.mesh.primitive_cube_add()\nbpy.context.object.name='Harness_A'\nbpy.ops.mesh.primitive_uv_sphere_add()\nbpy.context.object.name='Harness_B'\nraise ValueError('injected failure')",
            atomic=True,
        )
        assert not r.success, r.to_dict()
        assert r.rollback == "restored", r.to_dict()
        assert set(bpy.data.objects.keys()) == before, list(bpy.data.objects.keys())
        if not bpy.app.background:
            bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
            bpy.ops.screen.screenshot(filepath=str(out / "after-rollback.png"))
        r = executor.execute(
            "bpy.ops.mesh.primitive_cube_add()\nbpy.context.object.name='Harness_Passed'\nbpy.context.object.location=(3,0,0)",
            atomic=True,
        )
        assert r.success, r.to_dict()
        assert "Harness_Passed" in bpy.data.objects
        if not bpy.app.background:
            bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
            bpy.ops.screen.screenshot(filepath=str(out / "success.png"))
        assert "FINISHED" in bpy.ops.ed.undo()
        assert "Harness_Passed" not in bpy.data.objects
        result = {
            "passed": True,
            "rollback_restores_two_operations": True,
            "success_undoable_once": True,
        }
    except Exception as exc:  # noqa: BLE001 — retain failure evidence before closing the app
        import traceback

        result["error"] = str(exc)
        result["traceback"] = traceback.format_exc()
    (out / "atomic-verdict.json").write_text(json.dumps(result, indent=2))
    print("HARNESS_VERDICT", json.dumps(result))
    if not bpy.app.background:
        bpy.ops.wm.quit_blender()


if bpy.app.background:
    run()
else:
    bpy.context.preferences.view.show_splash = False

    def dismiss_splash():
        for window in bpy.context.window_manager.windows:
            window.event_simulate(type="ESC", value="PRESS")
            window.event_simulate(type="ESC", value="RELEASE")
        bpy.app.timers.register(run, first_interval=2)

    bpy.app.timers.register(dismiss_splash, first_interval=2)
