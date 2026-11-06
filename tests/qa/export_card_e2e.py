#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""The Export card, driven from the viewport's Export button.

No backend calls and no credits: Publish to Web is covered by
web_publish_e2e.py. Writes only into QA_SCENARIO_OUT.

    QA_HARNESS=/path/to/mixar-qa-harness QA_PORT=4777 \
        QA_SCENARIO_OUT=/tmp/export-card-qa python3 tests/qa/export_card_e2e.py

Proves: Export opens the card on its tiles (all ten, one lit); picking a tile
and a "Made for" engine loads that preset into the settings; Export writes a
GLB / FBX / STL that exists on disk with the lane's re-import check; a second
export of the same name asks before replacing; Save copy writes a .blend
without changing the open file; Render image saves a PNG from a background
render; an empty folder is an actionable error that recovers; Esc closes the
card and Export reopens it on the same tile. Vision: snaps of every state.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA  # noqa: E402

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/export-card-qa'))
EXPORTS = OUT / 'exports'
CARD = "bpy.context.window_manager.mixar_export_card"

FIXTURE = """
import bpy
win = drv.main_window()
scene = win.scene
for obj in list(scene.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
with bpy.context.temp_override(window=win):
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0, 0, 1))
    bpy.context.object.name = 'QA_Export_Cube'
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.8, location=(2.5, 0, 0.8))
    bpy.context.object.name = 'QA_Export_Sphere'
    bpy.ops.object.light_add(type='SUN', location=(4, -4, 6))
    bpy.ops.object.camera_add(location=(8, -8, 6))
scene.camera = next(o for o in scene.objects if o.type == 'CAMERA')
from mathutils import Vector
scene.camera.rotation_euler = (Vector((1, 0, 1)) - scene.camera.location).to_track_quat('-Z', 'Y').to_euler()
scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 320, 240, 100
result = bpy.data.filepath
"""


def snap(qa, name):
    qa.cmd('snap', path=str(OUT / f'{name}.png'))


def open_card(qa):
    """Export on the Zen toolbar; on a narrow window the toolbar folds Export
    into its ▾ overflow popover (the rightmost header popover)."""
    if not qa.eval("result = bool(drv.find(op='MIXAR_OT_export_card', region_type='HEADER'))"):
        x, y = qa.eval("pops = [w for w in drv.find(region_type='HEADER') "
                       "if w.get('type') == 'Popover' and w.get('block') == 'VIEW3D_HT_header']\n"
                       "result = max(pops, key=lambda w: w['center'][0])['center']")
        qa.cmd('click_xy', x=x, y=y)
        qa.wait("bool(drv.find(op='MIXAR_OT_export_card'))", timeout=10)
    qa.click(op='MIXAR_OT_export_card')
    qa.wait("bool(drv.find(op='MIXAR_OT_export_card_pick'))", timeout=10)


def card(qa, attr):
    return qa.eval(f"result = {CARD}.{attr}")


def pick(qa, op, text, expr):
    """Click and wait for the operator's effect (it runs a tick after the release)."""
    qa.click(op=op, **({"text": text} if text else {}))
    qa.wait(expr, timeout=10)


def export_and_wait(qa, label, timeout=120):
    qa.click(op='MIXAR_OT_export_card_run')
    qa.wait(f"{CARD}.state in ('DONE', 'ERROR', 'CONFIRM')", timeout=timeout)
    state = card(qa, 'state')
    assert state == 'DONE', f"{label}: card ended in {state}"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    EXPORTS.mkdir(parents=True, exist_ok=True)
    for old in EXPORTS.iterdir():
        old.unlink()
    qa = QA(port=int(os.environ.get('QA_PORT', '4777')))
    verdict = {'passed': False, 'steps': []}
    try:
        try:
            qa.cmd('reset_state')
        except Exception as exc:  # noqa: BLE001
            # The harness proves a clean layout by the toolbar's Cinema Mode
            # button, which a narrow window folds away; the fixture below
            # replaces the scene either way. Anything else is a real failure.
            if 'clean startup layout' not in str(exc):
                raise
            verdict['reset_note'] = 'narrow toolbar: reset layout check skipped'
        open_file = qa.eval(FIXTURE)

        # Opens on the tiles, one lit.
        open_card(qa)
        tiles = qa.eval("result = len(drv.find(op='MIXAR_OT_export_card_pick'))")
        assert tiles == 10, tiles
        qa.eval(f"{CARD}.folder = {str(EXPORTS)!r}; {CARD}.file_name = 'qa_scene'; result = True")
        snap(qa, '00-card-gltf')
        verdict['steps'].append('Export opens the card with ten tiles')

        # glTF / GLB for three.js (the default), written and re-import checked.
        pick(qa, 'MIXAR_OT_export_card_pick', 'glTF', f"{CARD}.target == 'GLTF'")
        qa.wait(f"{CARD}.engine == 'web' and {CARD}.cameras_lights", timeout=10)
        export_and_wait(qa, 'GLB')
        assert (EXPORTS / 'qa_scene.glb').stat().st_size > 0
        assert qa.eval("from mixar.modules.export_card.core import state; "
                       "result = state.result().get('checked')") is True
        snap(qa, '01-done-glb')
        verdict['steps'].append('GLB written and checked by re-import')

        # Same name again: asks before replacing.
        pick(qa, 'MIXAR_OT_export_card_again', None, f"{CARD}.state == 'IDLE'")
        qa.click(op='MIXAR_OT_export_card_run')
        qa.wait(f"{CARD}.state == 'CONFIRM'", timeout=10)
        snap(qa, '02-confirm-replace')
        qa.click(op='MIXAR_OT_export_card_run', text='Replace')
        qa.wait(f"{CARD}.state == 'DONE'", timeout=120)
        verdict['steps'].append('Existing file asks before replacing')

        # FBX for Unity: the preset lands in the settings.
        pick(qa, 'MIXAR_OT_export_card_again', None, f"{CARD}.state == 'IDLE'")
        pick(qa, 'MIXAR_OT_export_card_pick', 'FBX', f"{CARD}.target == 'FBX'")
        qa.wait(f"{CARD}.target == 'FBX' and {CARD}.engine == 'unreal'", timeout=10)
        pick(qa, 'MIXAR_OT_export_card_engine', 'Unity', f"{CARD}.engine == 'unity'")
        qa.wait(f"{CARD}.engine == 'unity' and {CARD}.fbx_scale == 'FBX_SCALE_UNITS'", timeout=10)
        snap(qa, '03-fbx-unity')
        export_and_wait(qa, 'FBX')
        assert (EXPORTS / 'qa_scene.fbx').stat().st_size > 0
        verdict['steps'].append('FBX for Unity written with the Unity preset')

        # STL for printing.
        pick(qa, 'MIXAR_OT_export_card_again', None, f"{CARD}.state == 'IDLE'")
        pick(qa, 'MIXAR_OT_export_card_pick', 'STL', f"{CARD}.target == 'STL'")
        snap(qa, '04-stl')
        export_and_wait(qa, 'STL')
        assert (EXPORTS / 'qa_scene.stl').stat().st_size > 0
        snap(qa, '05-done-stl')
        verdict['steps'].append('STL written')

        # Blender file copy: the open file does not change.
        pick(qa, 'MIXAR_OT_export_card_again', None, f"{CARD}.state == 'IDLE'")
        pick(qa, 'MIXAR_OT_export_card_pick', '.blend', f"{CARD}.target == 'BLEND'")
        export_and_wait(qa, 'Blender file')
        assert (EXPORTS / 'qa_scene.blend').stat().st_size > 0
        assert qa.eval("result = bpy.data.filepath") == open_file
        verdict['steps'].append('Blender copy written; open file unchanged')

        # Image: a background render saved to the chosen file.
        pick(qa, 'MIXAR_OT_export_card_again', None, f"{CARD}.state == 'IDLE'")
        pick(qa, 'MIXAR_OT_export_card_pick', 'PNG', f"{CARD}.target == 'IMAGE'")
        snap(qa, '06-image-form')
        export_and_wait(qa, 'Image start')
        snap(qa, '07-rendering')
        qa.wait(f"__import__('os').path.isfile({str(EXPORTS / 'qa_scene.png')!r})", timeout=300)
        verdict['steps'].append('Render image saved the PNG in the background')

        # Failure path: no folder → actionable error → back to settings.
        pick(qa, 'MIXAR_OT_export_card_again', None, f"{CARD}.state == 'IDLE'")
        pick(qa, 'MIXAR_OT_export_card_pick', 'OBJ', f"{CARD}.target == 'OBJ'")
        qa.eval(f"{CARD}.folder = ''; result = True")
        qa.click(op='MIXAR_OT_export_card_run')
        qa.wait(f"{CARD}.state == 'ERROR'", timeout=10)
        snap(qa, '08-error')
        pick(qa, 'MIXAR_OT_export_card_again', None, f"{CARD}.state == 'IDLE'")
        qa.wait(f"{CARD}.state == 'IDLE'", timeout=10)
        verdict['steps'].append('Empty folder is an error that recovers')

        # Esc closes; Export reopens on the same tile.
        qa.cmd('press', key='ESC')
        qa.wait("not drv.find(op='MIXAR_OT_export_card_pick')", timeout=10)
        open_card(qa)
        qa.wait(f"{CARD}.target == 'OBJ'", timeout=10)
        snap(qa, '09-reopened')
        qa.cmd('press', key='ESC')
        verdict['steps'].append('Esc closes; Export reopens on the same tile')
        verdict['passed'] = True
    except Exception as exc:
        verdict['error'] = str(exc)
        snap(qa, '99-failure')
        raise
    finally:
        (OUT / 'verdict.json').write_text(json.dumps(verdict, indent=2))
    print(json.dumps(verdict, indent=2))


if __name__ == '__main__':
    main()
