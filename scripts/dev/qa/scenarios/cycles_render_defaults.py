# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Free GUI replay. QA_HARNESS points to mixar-qa-harness; MIXAR_QA_PORT selects
an isolated running app. QA_LOAD_SOURCE=1 hot-loads this checkout's Python
changes into that process only. QA_EVIDENCE selects the local output directory.

Run with Python 3 against a throwaway Dev profile with a compatible GPU.
The replay replaces the open file and writes temporary projects, screenshots
and a verdict locally; generated evidence is not committed.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ["QA_HARNESS"]) / "scenarios"))
from lib import QA, run_scenario

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(os.environ.get("QA_EVIDENCE", "/tmp/cycles-render-defaults"))


def run(qa: QA):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "cycles-render.png").unlink(missing_ok=True)
    qa.step("login", qa.cmd, "wait_login", timeout=60)
    qa.press("ESC")
    if os.environ.get("QA_LOAD_SOURCE") == "1":
        qa.eval(f'''import importlib.util, sys, mixar.bootstrap
from pathlib import Path
root = Path({str(ROOT / 'src/scripts/mixar')!r})
from mixar.modules.space_mixie_chat.core import render_device
path = root / "modules/space_mixie_chat/core/render_device.py"
exec(compile(path.read_text(), str(path), "exec"), render_device.__dict__)
for leaf in ("render_defaults_module", "render_device_module"):
    name = "mixar.bootstrap." + leaf
    old = sys.modules.get(name)
    if old:
        old.unregister()
    spec = importlib.util.spec_from_file_location(name, root / "bootstrap" / (leaf + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    setattr(sys.modules["mixar.bootstrap"], leaf, module)
    module.register()
result = True
''')
    qa.wait('__import__("mixar.bootstrap.render_defaults_module", fromlist=["_ready"])._ready')
    qa.eval('''import sys
assert sys.platform in {"darwin", "win32", "linux"}
from mixar.modules.space_mixie_chat.core import render_device
render_device.enable_gpu_device()
assert render_device.use_gpu(), "QA requires an available GPU"
win = drv.main_window()
scene = bpy.data.scenes.new("QA Cycles render defaults")
win.scene = scene
scene.render.engine = "BLENDER_EEVEE"
area = next(a for a in win.screen.areas if a.type in {"VIEW_3D", "PROPERTIES"})
area.type = "PROPERTIES"
area.spaces.active.context = "RENDER"
result = True
''')

    def properties(context):
        qa.eval(f'a = next(a for a in drv.main_window().screen.areas if a.type == "PROPERTIES"); a.spaces.active.context = {context!r}; result = True')
        # A real event presents the newly selected tab on Metal; a layout dump
        # alone can be fresh while the screenshot framebuffer is still old.
        qa.press("ESC")

    def snap(name):
        qa.press("ESC")
        # Layout introspection can lead the Metal front buffer. Present two
        # frames in the main window before reading pixels; no render involved.
        qa.eval('''w = drv.main_window()
a = next(a for a in w.screen.areas if a.type == "PROPERTIES")
with bpy.context.temp_override(window=w, area=a):
    bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)
result = True
''')
        return qa.cmd("snap", path=str(OUT / (name + ".png")), area="PROPERTIES")

    def choose(prop, item):
        qa.cmd("choose", widget={"prop": prop, "area_type": "PROPERTIES"}, item=item)

    snap("before")
    qa.step("choose_cycles", choose, "engine", "Cycles")
    qa.wait('drv.main_window().scene.cycles.device == "GPU" and drv.main_window().scene.render.use_border')
    gpu = qa.find(prop="device", area_type="PROPERTIES")["widgets"][0]
    assert gpu["text"] == "GPU Compute" and gpu["enabled"]
    snap("gpu-compute")
    properties("OUTPUT")
    border = qa.find(prop="use_border", area_type="PROPERTIES")["widgets"][0]
    assert border.get("sel") and border["enabled"]
    snap("render-region")
    qa.click(prop="use_border", area_type="PROPERTIES")
    properties("RENDER")
    choose("device", "CPU")
    choose("engine", "EEVEE")
    choose("engine", "Cycles")
    qa.wait('drv.main_window().scene.cycles.device == "CPU" and not drv.main_window().scene.render.use_border')
    snap("manual-cpu-preserved")
    properties("OUTPUT")
    snap("manual-region-preserved")
    # Keep a reservation through separate RPCs so the real RNA notification
    # gets a main-loop turn during render setup, before native RENDER exists.
    qa.eval('''from mixar.modules.common.render_coordinator import core as slot
assert slot.acquire("QA render defaults") is not None
s = bpy.data.scenes.new("QA scripted engine")
drv.main_window().scene = s
s.render.engine = "CYCLES"
result = True
''')
    try:
        qa.press("ESC")
        assert qa.eval('''s = drv.main_window().scene
result = not s.render.use_border and s.cycles.device == "CPU" and not s.get("_mixar_cycles_defaults_applied")
''')
        qa.eval('''s = drv.main_window().scene
s.render.engine = "BLENDER_EEVEE"
result = True
''')
    finally:
        qa.eval('''from mixar.modules.common.render_coordinator import core as slot
slot.release(slot._active)
result = True
''')
    # Exercise the real load_post path: File > New must re-arm the timer,
    # initialize an EEVEE startup scene, and retain the GPU when choosing Cycles.
    qa.eval('with bpy.context.temp_override(window=drv.main_window()):\n    bpy.ops.wm.read_homefile()\nresult = True')
    qa.wait('not bpy.data.filepath and drv.main_window().scene.cycles.device == "GPU"')
    qa.eval('''w = drv.main_window()
area = next(a for a in w.screen.areas if a.type in {"VIEW_3D", "PROPERTIES"})
area.type = "PROPERTIES"
area.spaces.active.context = "RENDER"
result = True
''')
    choose("engine", "Cycles")
    qa.wait('drv.main_window().scene.render.use_border')
    snap("file-new-gpu")
    # Actual tiny Cycles render through the native render job (no paid calls).
    qa.eval(f'''s = drv.main_window().scene
s.render.resolution_x = s.render.resolution_y = 64
s.render.resolution_percentage = 100
s.cycles.samples = 4
s.render.filepath = {str(OUT / "cycles-render.png")!r}
bpy.context.preferences.view.render_display_type = "NONE"
with bpy.context.temp_override(window=drv.main_window()):
    assert "RUNNING_MODAL" in bpy.ops.render.render("INVOKE_DEFAULT", write_still=True)
result = True
''')
    qa.wait('not bpy.app.is_job_running("RENDER")', timeout=90)
    assert (OUT / "cycles-render.png").is_file(), "Cycles render did not write an image"
    # Save CPU/unchecked settings, reload, then switch away and back. Testing
    # a file without a defaults marker catches legacy-project regressions too.
    choose("device", "CPU")
    properties("OUTPUT")
    qa.click(prop="use_border", area_type="PROPERTIES")
    project = OUT / "saved-cpu.mixar"
    qa.eval(f'''s = drv.main_window().scene
s.pop("_mixar_cycles_defaults_applied", None)
with bpy.context.temp_override(window=drv.main_window()):
    bpy.ops.wm.save_as_mainfile(filepath={str(project)!r})
    bpy.ops.wm.open_mainfile(filepath={str(project)!r})
result = True
''')
    qa.wait('__import__("mixar.bootstrap.render_defaults_module", fromlist=["_ready"])._ready')
    properties("RENDER")
    choose("engine", "EEVEE")
    choose("engine", "Cycles")
    qa.wait('drv.main_window().scene.cycles.device == "CPU" and not drv.main_window().scene.render.use_border')
    snap("saved-cpu-preserved")
    runtime = qa.eval('''import sys
p = bpy.context.preferences.addons["cycles"].preferences
result = {"platform": sys.platform, "backend": p.compute_device_type,
          "devices": [d.name for d in p.devices if d.use and d.type == p.compute_device_type]}
''')
    # The global CPU preference is restored by a different load_post handler.
    # This catches applying defaults too early, before that handler runs.
    old_preference = qa.eval('result = drv.main_window().scene.mixar_paint_preferences.default_render_device')
    try:
        qa.eval('drv.main_window().scene.mixar_paint_preferences.default_render_device = "CPU"; result = True')
        qa.eval('with bpy.context.temp_override(window=drv.main_window()):\n    bpy.ops.wm.read_homefile()\nresult = True')
        qa.wait('__import__("mixar.bootstrap.render_defaults_module", fromlist=["_ready"])._ready')
        assert qa.eval('result = drv.main_window().scene.cycles.device == "CPU"')
    finally:
        qa.eval(f'drv.main_window().scene.mixar_paint_preferences.default_render_device = {old_preference!r}; result = True')
    verdict = {"gpu_compute": True, "cpu_preference_on_file_new": True, "file_new_gpu": True, "native_render": True,
            "saved_project_preserved": True, "runtime": runtime, "render_region": True,
            "manual_choices_preserved": True, "scripted_switch_untouched": True,
            "source_hot_loaded": os.environ.get("QA_LOAD_SOURCE") == "1",
            "screenshots": str(OUT)}
    (OUT / "verdict.json").write_text(json.dumps(
        {"scenario": "cycles_render_defaults", "ok": True, "steps": qa.log, **verdict}, indent=2) + "\n")
    return verdict


if __name__ == "__main__":
    run_scenario("cycles_render_defaults", run)
