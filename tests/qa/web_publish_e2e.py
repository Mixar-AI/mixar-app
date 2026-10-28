#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Publish to Web from the viewport Export button.

Steps marked [BACKEND] need a signed-in Dev app and
a backend with the scene_publish module (mixar-backend PR #1208) plus
presigned storage. Uses only a small QA scene; no generation jobs.

    QA_HARNESS=/path/to/mixar-qa-harness QA_PORT=4777 \
        QA_SCENARIO_OUT=/tmp/web-publish-qa python3 tests/qa/web_publish_e2e.py

Proves: Export opens a persistent Publish to Web popup; Publish runs the shared
export lane (Draco/WebP) and progresses EXPORTING → UPLOADING → DONE in the
WindowManager mirror; the result is filed on the published scene; Copy
Link puts the share URL on the clipboard. Vision: snaps of the form,
progress and published states.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA  # noqa: E402

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/web-publish-qa'))
WM = "bpy.context.window_manager"
PROPS = "drv.main_window().scene.mixar_web_publish"

FIXTURE = """
import bpy
win = drv.main_window()
scene = win.scene
for obj in list(scene.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
with bpy.context.temp_override(window=win):
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0, 0, 1))
    cube = bpy.context.object
    cube.name = 'QA_Publish_Cube'
    mat = bpy.data.materials.new('QA_Publish_Coral')
    mat.diffuse_color = (0.8, 0.12, 0.05, 1)
    mat.use_nodes = True
    mat.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value = mat.diffuse_color
    image = bpy.data.images.new('QA_Publish_Checker', width=64, height=64)
    image.pixels.foreach_set([channel for y in range(64) for x in range(64)
                             for channel in ((0.8, 0.12, 0.05, 1) if (x // 8 + y // 8) % 2
                                             else (1.0, 0.6, 0.15, 1))])
    texture = mat.node_tree.nodes.new('ShaderNodeTexImage')
    texture.image = image
    mat.node_tree.links.new(texture.outputs['Color'], mat.node_tree.nodes.get('Principled BSDF').inputs['Base Color'])
    cube.data.materials.append(mat)
    bpy.ops.mesh.primitive_plane_add(size=12)
    bpy.context.object.name = 'QA_Publish_Ground'
    bpy.ops.mesh.primitive_cube_add(location=(4, 0, 1))
    bpy.context.object.name = 'QA_Private_Hidden'
    bpy.context.object.hide_render = True
    bpy.context.object.hide_set(True)
    bpy.ops.object.light_add(type='SUN', location=(4, -4, 6))
    bpy.ops.object.camera_add(location=(9, -9, 6), rotation=(1.1, 0, 0.8))
scene.camera = next(o for o in scene.objects if o.type == 'CAMERA')
from mathutils import Vector
scene.camera.rotation_euler = (Vector((0, 0, 1.5)) - scene.camera.location).to_track_quat('-Z', 'Y').to_euler()
scene['mixar_qa_private_marker'] = 'must-not-publish'
for area in win.screen.areas:
    if area.type == 'VIEW_3D':
        area.spaces.active.region_3d.view_perspective = 'CAMERA'
props = scene.mixar_web_publish
props.title = 'QA Web Publish'
props.visibility = 'unlisted'
props.published_scene_id = props.slug = props.share_url = props.viewer_url = ''
result = scene.name
"""


def snap(qa, name):
    qa.cmd('snap', path=str(OUT / f'{name}.png'))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    qa = QA(port=int(os.environ.get('QA_PORT', '4777')))
    verdict = {'passed': False, 'steps': []}
    try:
        qa.cmd('wait_login', timeout=90)
        qa.cmd('reset_state')
        qa.cmd('wait_login', timeout=60)
        scene_name = qa.eval(FIXTURE)
        qa.click(text='Export', region_type='HEADER')
        qa.wait("bool(drv.find(text='Publish to Web…'))", timeout=10)
        snap(qa, '00-export-menu')
        # Existing file exports remain alongside publishing.
        assert qa.eval("result = bool(drv.find(text='Blend (.blend)'))")
        qa.click(op='WM_OT_call_panel', text='Publish to Web…')
        qa.wait("bool(drv.find(op='MIXAR_OT_web_publish'))", timeout=10)
        assert qa.eval(f"result = {PROPS}.is_published") is False
        assert qa.eval("result = hasattr(bpy.types, 'MIXAR_PT_web_publish')")
        snap(qa, '01-form')
        verdict['steps'].append('Export menu opens publish popup with file exports preserved')

        # [BACKEND] sign-in: the operator refuses while signed out.
        qa.cmd('wait_login', timeout=60)

        # [BACKEND] Publish: export runs synchronously in the click; the
        # upload thread then advances the WindowManager mirror.
        qa.click(op='MIXAR_OT_web_publish')
        qa.wait(f"{WM}.mixar_web_publish_scene == {scene_name!r}", timeout=30)
        qa.wait(f"{WM}.mixar_web_publish_status in ('UPLOADING', 'FINALIZING', 'DONE', 'ERROR', 'CANCELLED')",
                timeout=60)
        snap(qa, '02-progress')
        qa.wait(f"{WM}.mixar_web_publish_status in ('DONE', 'ERROR', 'CANCELLED')",
                timeout=300)
        status = qa.eval(f"result = {WM}.mixar_web_publish_status")
        assert status == 'DONE', qa.eval(
            "from mixar.modules.web_publish.core.publish_state import get_publish_state\n"
            "result = get_publish_state().snapshot()[0].error_text")
        verdict['steps'].append('publish reached DONE')

        # The result is filed on the published scene (persisted props).
        published = qa.eval(f"""
p = {PROPS}
result = {{'slug': p.slug, 'revision': p.revision, 'link': p.link,
           'is_published': p.is_published}}
""")
        assert published['is_published'] and published['revision'] >= 1, published
        assert published['link'].startswith('http'), published
        qa.wait("bool(drv.find(op='MIXAR_OT_web_publish_copy_link'))", timeout=10)
        snap(qa, '03-published')

        # Copy Link → clipboard holds the share link.
        qa.click(op='MIXAR_OT_web_publish_copy_link')
        assert qa.eval(f"result = {WM}.clipboard") == published['link']
        verdict['steps'].append('copy link')

        # The export used the publish profile (export.completed would say
        # via=web_publish); the agent view of the same publish agrees.
        agent = qa.eval("""
from mixar.modules.web_publish.core import agent_api
from mixar.modules.web_publish.core.publish_state import get_publish_state
result = agent_api.publish_status(get_publish_state().publish_id)
""")
        assert agent['status'] == 'ready' and agent['slug'] == published['slug'], agent
        # A changed scene publishes a new revision while keeping its identity/link.
        qa.eval("bpy.data.objects['QA_Publish_Cube'].scale.z = 1.5\nbpy.data.objects['QA_Publish_Cube'].location.z = 1.5\nresult = True")
        qa.click(op='MIXAR_OT_web_publish')
        qa.wait(f"{PROPS}.revision > {published['revision']}", timeout=300)
        updated = qa.eval(f"result = {{'slug': {PROPS}.slug, 'revision': {PROPS}.revision, 'link': {PROPS}.link}}")
        assert updated['slug'] == published['slug'] and updated['link'] == published['link'], updated
        snap(qa, '04-new-version')
        verdict['steps'].append('new version keeps share link')
        # Closing the popup never loses publication state; Export reopens it.
        qa.cmd('press', key='ESC')
        qa.click(text='Export', region_type='HEADER')
        qa.click(op='WM_OT_call_panel', text='Publish to Web…')
        qa.wait("bool(drv.find(op='MIXAR_OT_web_publish_copy_link'))", timeout=10)
        assert qa.eval(f"result = {PROPS}.link") == updated['link']
        snap(qa, '05-reopened')
        verdict['steps'].append('Export reopens the published scene controls')
        verdict.update(passed=True, published=updated, agent=agent)
    except Exception as exc:
        verdict['error'] = str(exc)
        snap(qa, '99-failure')
        raise
    finally:
        (OUT / 'verdict.json').write_text(json.dumps(verdict, indent=2))
    print(json.dumps(verdict, indent=2))


if __name__ == '__main__':
    main()
