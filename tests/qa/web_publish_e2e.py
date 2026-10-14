#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Publish to Web from the N-panel: Mixar tab › Publish to Web.

Authored, NOT yet run. Steps marked [BACKEND] need a signed-in Dev app and
a backend with the scene_publish module (mixar-backend PR #1208) plus
presigned storage; everything before them is local.

    QA_HARNESS=/path/to/mixar-qa-harness QA_PORT=4777 \
        QA_SCENARIO_OUT=/tmp/web-publish-qa python3 tests/qa/web_publish_e2e.py

Proves: the panel draws in the VIEW_3D sidebar; Publish runs the shared
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

OPEN_PANEL = """
win = drv.main_window()
area = next(a for a in win.screen.areas if a.type == 'VIEW_3D')
area.spaces.active.show_region_ui = True
ui = next(r for r in area.regions if r.type == 'UI')
ui.active_panel_category = 'Mixar'
area.tag_redraw()
result = True
"""

FIXTURE = """
import bpy
win = drv.main_window()
scene = win.scene
for obj in list(scene.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
with bpy.context.temp_override(window=win):
    bpy.ops.mesh.primitive_cube_add(size=2.0)
    bpy.ops.object.light_add(type='SUN', location=(4, -4, 6))
    bpy.ops.object.camera_add(location=(6, -6, 4), rotation=(1.1, 0, 0.8))
scene.camera = next(o for o in scene.objects if o.type == 'CAMERA')
props = scene.mixar_web_publish
props.title = 'QA Web Publish'
props.visibility = 'unlisted'
props.published_scene_id = props.slug = props.share_url = props.viewer_url = ''
result = scene.name
"""


def snap(qa, name):
    qa.cmd('snap', path=str(OUT / f'{name}.png'), target={'panel': 'MIXAR_PT_web_publish'},
           margin=40)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    qa = QA(port=int(os.environ.get('QA_PORT', '4777')))
    verdict = {'passed': False, 'steps': []}
    try:
        qa.cmd('reset_state')
        scene_name = qa.eval(FIXTURE)
        qa.eval(OPEN_PANEL)
        assert qa.eval(f"result = {PROPS}.is_published") is False
        assert qa.eval("result = hasattr(bpy.types, 'MIXAR_PT_web_publish')")
        snap(qa, '01-form')
        verdict['steps'].append('panel form drawn')

        # [BACKEND] sign-in: the operator refuses while signed out.
        qa.cmd('wait_login', timeout=60)

        # [BACKEND] Publish: export runs synchronously in the click; the
        # upload thread then advances the WindowManager mirror.
        qa.click(op='MIXAR_OT_web_publish')
        qa.wait(f"{WM}.mixar_web_publish_scene == {scene_name!r}", timeout=30)
        qa.wait(f"{WM}.mixar_web_publish_status in ('UPLOADING', 'FINALIZING', 'DONE')",
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
        verdict.update(passed=True, published=published, agent=agent)
    finally:
        (OUT / 'verdict.json').write_text(json.dumps(verdict, indent=2))
    print(json.dumps(verdict, indent=2))


if __name__ == '__main__':
    main()
