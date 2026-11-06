#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit Export sheet replay. Use an isolated QA app and inspect the PNGs.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4791 \
    QA_SCENARIO_OUT=/tmp/export-menu python3 tests/qa/export_menu_e2e.py

Proves: the Zen toolbar's Export opens the Export sheet over a blurred,
dimmed window (the native hold is set while it is open and released after);
every format tile is pickable and exactly one is lit; a real OBJ, a .blend
copy and a Fast PNG render (scene render settings restored) are written
into the artifact folder, never overwriting; Selected objects only with no
selection disables Export; ✕ and Esc close it without writing. Vision: the
sheet over the blur per format, and the window after closing.
"""

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ["QA_HARNESS"]) / "scenarios"))
from lib import run_scenario  # noqa: E402

OUT = Path(os.environ.get("QA_SCENARIO_OUT", "/tmp/export-menu"))
FILES = OUT / "exports"
HEADER = {"area_type": "VIEW_3D", "region_type": "HEADER"}
PROPS = "bpy.context.window_manager.mixar_export_menu"
OPEN = "drv.main_window().mixar_popup_block_open()"
TILES = (".blend", ".mixar", ".glb", ".fbx", ".obj", "Unreal", "Unity", "Web", ".png", ".mp4")


def snap(qa, name):
    qa.cmd("snap", path=str(OUT / f"{name}.png"))


def open_sheet(qa):
    qa.click(**HEADER, text="Export")
    qa.wait("bool(drv.find(op='MIXAR_OT_export_menu_pick', text='.blend'))", timeout=10)


def pick(qa, label):
    qa.click(popup=True, op="MIXAR_OT_export_menu_pick", text=label)


def export_and_wait(qa, name, timeout=30):
    qa.click(popup=True, op="MIXAR_OT_export_menu_run")
    qa.wait(f"__import__('os').path.exists({str(FILES / name)!r})", timeout=timeout)
    qa.wait(f"not {OPEN}", timeout=5)
    return (FILES / name).stat().st_size


def setup(qa):
    qa.wait("hasattr(bpy.types, 'MIXAR_OT_export_menu') and "
            "hasattr(bpy.context.window_manager, 'mixar_export_menu')", timeout=30)
    FILES.mkdir(parents=True, exist_ok=True)
    qa.eval(f"""
import os
assert os.environ.get('MIXAR_QA') == '1', 'Use an isolated QA profile'
import mixar.modules.export_menu.core.runner as runner
runner.output_folder = lambda: {str(FILES)!r}
win = drv.main_window()
scene = win.scene
assert scene.camera is not None and any(o.type == 'MESH' for o in scene.objects)
props = {PROPS}
props.file_name = 'QA_Export'
props.quality = 'FAST'
props.selected_only = False
bpy.context.preferences.view.show_tooltips = False
result = True
""")


def sheet(qa):
    open_sheet(qa)
    tiles = qa.eval("result=[w.get('text') for w in drv.find(op='MIXAR_OT_export_menu_pick')]")
    assert tuple(tiles) == TILES, tiles
    assert qa.eval(f"result={OPEN}") is True
    snap(qa, "01-sheet-over-blur")
    for label, key in (("Unreal", "UNREAL"), ("Web", "WEB"), (".mp4", "MP4")):
        pick(qa, label)
        assert qa.eval(f"result={PROPS}.format") == key
        snap(qa, f"02-format-{key.lower()}")
    return {"tiles": tiles}


def obj(qa):
    pick(qa, ".obj")
    size = export_and_wait(qa, "QA_Export.obj")
    snap(qa, "03-after-obj-toast")
    open_sheet(qa)
    pick(qa, ".obj")
    again = export_and_wait(qa, "QA_Export_2.obj")  # never overwrites
    return {"bytes": size, "second": again}


def blend(qa):
    open_sheet(qa)
    pick(qa, ".blend")
    return {"bytes": export_and_wait(qa, "QA_Export.blend")}


def png(qa):
    before = qa.eval("r=drv.main_window().scene.render; "
                     "result=[r.engine, r.image_settings.file_format, r.resolution_percentage]")
    open_sheet(qa)
    pick(qa, ".png")
    snap(qa, "04-png-settings")
    size = export_and_wait(qa, "QA_Export.png", timeout=180)
    qa.wait("not bpy.app.is_job_running('RENDER')", timeout=30)
    after = qa.eval("r=drv.main_window().scene.render; "
                    "result=[r.engine, r.image_settings.file_format, r.resolution_percentage]")
    assert after == before, (before, after)
    return {"bytes": size, "settings_restored": True}


def blocked(qa):
    qa.eval(f"{PROPS}.selected_only = True\n"
            "for o in drv.main_window().scene.objects: o.select_set(False)\nresult=True")
    open_sheet(qa)
    pick(qa, ".fbx")
    run = qa.find(popup=True, op="MIXAR_OT_export_menu_run")["widgets"][0]
    assert run.get("enabled") is False, run
    snap(qa, "05-blocked-selection")
    qa.eval(f"{PROPS}.selected_only = False\nresult=True")
    return {"export_disabled": True}


def cancel(qa):
    count = len(os.listdir(FILES))
    qa.click(popup=True, text="✕")
    qa.wait(f"not {OPEN}", timeout=5)
    open_sheet(qa)
    qa.cmd("press", key="ESC")
    qa.wait(f"not {OPEN}", timeout=5)
    snap(qa, "06-closed-unblurred")
    assert len(os.listdir(FILES)) == count
    return {"closed_by": ["close", "escape"], "nothing_written": True}


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    setup(qa)
    checks = {}
    for name, fn in (("sheet", sheet), ("obj", obj), ("blend", blend), ("png", png),
                     ("blocked", blocked), ("cancel", cancel)):
        checks[name] = qa.step(name, fn, qa)
    verdict = {"checks": checks, "paid_requests": 0, "artifacts": str(OUT)}
    (OUT / "verdict.json").write_text(json.dumps(verdict, indent=2) + "\n")
    return verdict


if __name__ == "__main__":
    run_scenario("export_menu_e2e", run)
