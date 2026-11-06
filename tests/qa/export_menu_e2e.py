#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit Export sheet replay. Use an isolated QA app and inspect the PNGs.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4791 \
    QA_SCENARIO_OUT=/tmp/export-menu python3 tests/qa/export_menu_e2e.py

Proves: the Zen toolbar's Export opens the Export sheet over a blurred,
dimmed window (the native hold is set while it is open and released after);
every format tile is pickable and exactly one is lit; a real OBJ (twice:
never overwriting), .blend, .mixar, GLB, Unreal FBX and Unity glTF, a Fast
PNG and WebP still and a 12-frame WebM (scene render settings restored) are
written into the artifact folder; Selected objects only with no
selection disables Export; ✕ and Esc close it without writing. Vision: the
sheet over the blur per format, and the window after closing.
"""

import json
import os
import time
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
    """Snap, then wait for the PNG: the capture lands a frame later, and a
    click sent before it would show up in the picture."""
    path = OUT / f"{name}.png"
    path.unlink(missing_ok=True)
    qa.cmd("snap", path=str(path))
    deadline = time.monotonic() + 10
    while not (path.exists() and path.stat().st_size > 0):
        assert time.monotonic() < deadline, f"snap {name} never landed"
        time.sleep(0.1)


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


RENDER_SETTINGS = ("r=drv.main_window().scene.render; result=[r.engine, "
                   "r.image_settings.media_type, r.image_settings.file_format, "
                   "r.ffmpeg.format, r.ffmpeg.codec, r.resolution_percentage, r.filepath]")


def choose(qa, name, value):
    qa.eval(f"{PROPS}.{name} = {value!r}\nresult=True")


def models(qa):
    """GLB, Unreal (FBX preset) and Unity (glTF), each a real file."""
    sizes = {}
    for label, option, file in ((".glb", None, "QA_Export.glb"),
                                ("Unreal", None, "QA_Export.fbx"),
                                ("Unity", ("engine_format", "GLB"), "QA_Export_2.glb")):
        open_sheet(qa)
        pick(qa, label)
        if option:
            choose(qa, *option)
        sizes[label] = export_and_wait(qa, file)
        assert sizes[label] > 0, label
    head = (FILES / "QA_Export.fbx").read_bytes()[:20]
    assert head.startswith(b"Kaydara FBX Binary"), head
    assert (FILES / "QA_Export.glb").read_bytes()[:4] == b"glTF"
    return sizes


def project(qa):
    open_sheet(qa)
    pick(qa, ".mixar")
    return {"bytes": export_and_wait(qa, "QA_Export.mixar")}


def web_formats(qa):
    """A Fast WebP still and a 12-frame WebM: the containers the tests fake."""
    qa.eval("s=drv.main_window().scene; s.frame_start=1; s.frame_end=12; result=True")
    before = qa.eval(RENDER_SETTINGS)
    open_sheet(qa)
    pick(qa, ".png")
    choose(qa, "image_format", "WEBP")
    webp = export_and_wait(qa, "QA_Export.webp", timeout=180)
    qa.wait("not bpy.app.is_job_running('RENDER')", timeout=60)
    assert (FILES / "QA_Export.webp").read_bytes()[8:12] == b"WEBP"
    open_sheet(qa)
    pick(qa, ".mp4")
    choose(qa, "video_format", "WEBM")
    snap(qa, "04b-webm-settings")
    webm = export_and_wait(qa, "QA_Export.webm", timeout=300)
    qa.wait("not bpy.app.is_job_running('RENDER')", timeout=60)
    assert (FILES / "QA_Export.webm").read_bytes()[:4] == b"\x1a\x45\xdf\xa3"  # EBML
    after = qa.eval(RENDER_SETTINGS)
    assert after == before, (before, after)
    return {"webp": webp, "webm": webm, "settings_restored": True}


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
                     ("models", models), ("project", project), ("web-formats", web_formats),
                     ("blocked", blocked), ("cancel", cancel)):
        checks[name] = qa.step(name, fn, qa)
    verdict = {"checks": checks, "paid_requests": 0, "artifacts": str(OUT)}
    (OUT / "verdict.json").write_text(json.dumps(verdict, indent=2) + "\n")
    return verdict


if __name__ == "__main__":
    run_scenario("export_menu_e2e", run)
