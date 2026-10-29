#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Real desktop Export -> UAT5 publication plus a rendered lighting reference.

Requires the existing signed-in Dev QA harness. Uses a dedicated disposable
scene and no generation jobs. Run the browser published-scene replays against
the slug in verdict.json, then compare the exported lights with source.json.
The source includes an area light and World on purpose: a successful upload
must not be mistaken for complete lighting fidelity.

QA_EXPECTED_BACKEND=https://uat5.mixar.app QA_HARNESS=/opt/qa-harness \
QA_SCENARIO_OUT=/tmp/uat5-lighting-e2e python3 web_publish_lighting_e2e.py
"""
import json
import os
from pathlib import Path

import web_publish_e2e as publish


LIGHTING = """
from mathutils import Vector
sun = next(o for o in scene.objects if o.type == 'LIGHT')
sun.name = 'QA_Sun'
sun.data.energy = 2.0
sun.rotation_euler = Vector((0.6, 0.4, -1)).to_track_quat('-Z', 'Y').to_euler()
with bpy.context.temp_override(window=win):
    for kind, name, location, color, power in [
        ('POINT', 'QA_Point', (-3, -2, 3), (0.15, 0.35, 1.0), 100),
        ('SPOT', 'QA_Spot', (3, -2, 4), (0.15, 1.0, 0.25), 250),
        ('AREA', 'QA_Area', (0, 3, 4), (1.0, 0.25, 0.1), 500),
    ]:
        bpy.ops.object.light_add(type=kind, location=location)
        light = bpy.context.object
        light.name = name
        light.data.color = color
        light.data.energy = power
        light.rotation_euler = (Vector((0, 0, 1)) - light.location).to_track_quat('-Z', 'Y').to_euler()
        if kind == 'AREA': light.data.size = 3
world = bpy.data.worlds.new('QA_World')
world.use_nodes = True
background = world.node_tree.nodes.get('Background')
background.inputs['Color'].default_value = (0.08, 0.12, 0.25, 1)
background.inputs['Strength'].default_value = 0.4
scene.world = world
scene.render.engine = 'BLENDER_EEVEE'
scene.render.resolution_x = 960
scene.render.resolution_y = 720
scene.render.resolution_percentage = 100
scene.view_settings.view_transform = 'AgX'
props.title = 'UAT5 Desktop Lighting E2E'
result = scene.name
"""


def main():
    qa = publish.QA(port=int(os.environ.get('QA_PORT', '4777')))
    expected = os.environ.get('QA_EXPECTED_BACKEND', 'https://uat5.mixar.app')
    actual = qa.eval("from mixar.config.config import get_server_url\nresult = get_server_url()")
    assert actual.rstrip('/') == expected.rstrip('/'), (actual, expected)
    publish.FIXTURE += LIGHTING
    publish.main()
    qa.press('ESC')
    out = publish.OUT
    source = qa.eval("""
scene = drv.main_window().scene
background = scene.world.node_tree.nodes.get('Background')
result = {
    'lights': [{'name': o.name, 'type': o.data.type, 'energy': o.data.energy,
                'color': list(o.data.color)} for o in scene.objects if o.type == 'LIGHT'],
    'world': {'color': list(background.inputs['Color'].default_value),
              'strength': background.inputs['Strength'].default_value},
    'view_transform': scene.view_settings.view_transform,
    'exposure': scene.view_settings.exposure,
}
""")
    (out / 'source.json').write_text(json.dumps(source, indent=2))
    render_path = str(out / 'source-render.png')
    result = qa.eval(f"""
win = drv.main_window()
scene = win.scene
scene.render.filepath = {render_path!r}
scene.render.image_settings.file_format = 'PNG'
with bpy.context.temp_override(window=win):
    result = sorted(bpy.ops.render.render('INVOKE_DEFAULT', write_still=True))
""")
    assert 'CANCELLED' not in result, result
    qa.wait(f"__import__('os').path.exists({render_path!r}) and not bpy.app.is_job_running('RENDER')", timeout=180)
    verdict_path = out / 'verdict.json'
    verdict = json.loads(verdict_path.read_text())
    verdict.update(backend=actual, source=source, reference_render=True)
    verdict_path.write_text(json.dumps(verdict, indent=2))
    print(json.dumps({'passed': verdict['passed'], 'published': verdict['published'], 'reference_render': True}))


if __name__ == '__main__':
    main()
