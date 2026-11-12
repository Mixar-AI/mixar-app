#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Free native CUDA render replay in an isolated Blender 5.3 QA app.

Requires an NVIDIA GPU, Pillow, QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT.
Builds a disposable fixture, presses F12, verifies rendered pixels and saves
the result for visual review. No backend generation or provider calls.
"""
import json
import os
from pathlib import Path
import sys

from PIL import Image

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario


def run(qa):
    out = Path(os.environ['QA_SCENARIO_OUT'])
    out.mkdir(parents=True, exist_ok=True)
    qa.cmd('reset_state')
    qa.cmd('dismiss_splash')
    qa.cmd('dismiss_chat')
    devices = qa.eval('''
import os
assert os.environ.get('MIXAR_QA') == '1'
assert bpy.app.version[:2] == (5, 3)
prefs = bpy.context.preferences.addons['cycles'].preferences
prefs.compute_device_type = 'CUDA'
prefs.refresh_devices()
for device in prefs.devices:
    device.use = device.type == 'CUDA'
assert any(d.type == 'CUDA' and d.use for d in prefs.devices)
w = drv.main_window()
s = w.scene
for obj in list(s.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
with bpy.context.temp_override(window=w, scene=s, view_layer=w.view_layer):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16)
    sphere = bpy.context.object
material = bpy.data.materials.new('QA CUDA orange')
material.use_nodes = True
bsdf = material.node_tree.nodes.get('Principled BSDF')
bsdf.inputs['Base Color'].default_value = (1, .05, .01, 1)
bsdf.inputs['Roughness'].default_value = .4
sphere.data.materials.append(material)
camera = bpy.data.objects.new('QA camera', bpy.data.cameras.new('QA camera'))
s.collection.objects.link(camera)
camera.location = (0, -6, 1)
camera.rotation_euler = (-camera.location).to_track_quat('-Z', 'Y').to_euler()
s.camera = camera
light = bpy.data.objects.new('QA key', bpy.data.lights.new('QA key', 'AREA'))
s.collection.objects.link(light)
light.location = (-3, -4, 5)
light.rotation_euler = (-light.location).to_track_quat('-Z', 'Y').to_euler()
light.data.energy = 1200
light.data.shape = 'DISK'
light.data.size = 4
s.world = bpy.data.worlds.new('QA dark world')
s.world.use_nodes = True
s.world.node_tree.nodes['Background'].inputs['Color'].default_value = (.01, .01, .01, 1)
s.render.engine = 'CYCLES'
s.cycles.device = 'GPU'
s.cycles.samples = 8
s.cycles.use_denoising = False
s.render.resolution_x = s.render.resolution_y = 128
s.render.resolution_percentage = 100
s.render.image_settings.media_type = 'IMAGE'
s.render.image_settings.file_format = 'PNG'
s.render.film_transparent = False
bpy.context.preferences.view.render_display_type = 'NONE'
drv._qa53_render_done = False
def completed(scene, *args):
    drv._qa53_render_done = True
drv._qa53_render_callback = completed
bpy.app.handlers.render_complete.append(completed)
area = next(a for a in w.screen.areas if a.type == 'VIEW_3D')
region = next(r for r in area.regions if r.type == 'WINDOW')
drv.move_to(w, region.x + region.width // 2, region.y + region.height // 2)
result = [{'name': d.name, 'type': d.type, 'use': d.use} for d in prefs.devices]
''')
    try:
        qa.step('native_render_key', qa.press, 'F12')
        qa.step('render_completed', qa.wait, 'drv._qa53_render_done', timeout=180)
        path = str(out / 'cuda-render.png')
        qa.eval(f"bpy.data.images['Render Result'].save_render({path!r}, scene=drv.main_window().scene)\nresult=True")
        image = Image.open(path).convert('RGB')
        center = image.getpixel((64, 64))
        corner = image.getpixel((0, 0))
        assert center[0] > 100 and center[0] > center[2] * 1.5, center
        assert max(corner) < 80, corner
        qa.snap(str(out / 'after-render.png'))
    finally:
        qa.eval('''
callback = drv._qa53_render_callback
if callback in bpy.app.handlers.render_complete:
    bpy.app.handlers.render_complete.remove(callback)
result = True
''')
    result = {'devices': devices, 'engine': 'CYCLES', 'device': 'GPU',
              'center': center, 'corner': corner, 'backend_turns': 0}
    (out / 'render.json').write_text(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    run_scenario('blender53_cuda_render_e2e', run)
