#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit regression: collection instances must remain framed in the viewer.

Run with QA_HARNESS and MIXAR_QA_PORT against an isolated Dev app, using a
Python environment with Pillow. Compare native preview pixels before/after
replacing direct geometry with a translated, nested collection instance.
"""
import inspect
import os
from pathlib import Path
import sys

from PIL import Image

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from workspace_scene_viewer_e2e import seed


def geometry_pixels(path, rect):
    with Image.open(path).convert('RGB') as image:
        x0, y0, x1, y1 = rect
        preview = image.crop((x0, image.height - y1, x1, image.height - y0))
        # The fixture's green material is distinct from the grey floor/grid.
        return sum(g > 60 and g > r * 1.08 and g > b * 1.02
                   for r, g, b in preview.getdata())


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/workspace-viewer-instances'))
    out.mkdir(parents=True, exist_ok=True)
    qa.dismiss_splash()
    qa.wait("hasattr(bpy.context.window_manager, 'mixar_agent_cards_active')", timeout=30)
    qa.eval('import os\n' + inspect.getsource(seed) + '\nresult=seed()')
    qa.wait("len(drv.find(surface='agent_panel_eye'))==2", timeout=15)
    # Click settled geometry, not a card still sliding into the viewport.
    qa.eval('def settle():\n    yield 1\n    return True\nresult=settle()')
    qa.click(surface='agent_panel_eye', value='viewer-0')
    qa.wait("any(t['value']!='unavailable' for t in drv.find(surface='workspace_viewer_scene'))",
            timeout=15)
    target = qa.eval("result=drv.find(surface='workspace_viewer_scene')[0]")
    qa.snap(str(out / 'direct.png'))
    before = geometry_pixels(out / 'direct.png', target['rect'])
    assert before > 1000, f'Fixture geometry not visible: {before}'
    qa.step('replace_with_nested_instance', qa.eval,
            "scene=next(s for s in bpy.data.scenes if s.get('mixar_workspace_task')=='viewer-0')\n"
            "source=bpy.data.collections.new('Viewer QA source')\n"
            "for obj in list(scene.objects):\n"
            "    source.objects.link(obj)\n"
            "    scene.collection.objects.unlink(obj)\n"
            "outer=bpy.data.collections.new('Viewer QA outer')\n"
            "nested=bpy.data.objects.new('Viewer QA nested', None)\n"
            "nested.instance_type='COLLECTION'\nnested.instance_collection=source\n"
            "outer.objects.link(nested)\n"
            "instance=bpy.data.objects.new('Viewer QA instance', None)\n"
            "instance.instance_type='COLLECTION'\ninstance.instance_collection=outer\n"
            "instance.location=(100,100,20)\nscene.collection.objects.link(instance)\n"
            "result=True")
    qa.wait(f"int(drv.find(surface='workspace_viewer_scene')[0]['value'])>{int(target['value'])}",
            timeout=10)
    qa.snap(str(out / 'instanced.png'))
    after = geometry_pixels(out / 'instanced.png', target['rect'])
    assert after > before * .7, f'Instanced geometry disappeared: {before} -> {after}'
    qa.click(surface='workspace_viewer_close')
    qa.wait("not drv.find(surface='workspace_viewer_scene')")
    qa.eval("from mixar.modules.agent_panel.core.cards import clear_cards\nclear_cards()\n"
            "main=drv.main_window().scene\nmain.mixie_run_open=False\n"
            "main.mixie_run_id=''\nmain.mixie_session_id=''\n"
            "for scene in list(bpy.data.scenes):\n"
            "    if scene.name.startswith('Viewer QA'): bpy.data.scenes.remove(scene)\n"
            "for obj in list(bpy.data.objects):\n"
            "    if obj.name.startswith('Viewer QA'): bpy.data.objects.remove(obj, do_unlink=True)\n"
            "for collection in list(bpy.data.collections):\n"
            "    if collection.name.startswith('Viewer QA'): bpy.data.collections.remove(collection)\n"
            "result=True")
    return {'paid_requests': 0, 'geometry_pixels': [before, after], 'screenshots': str(out)}


if __name__ == '__main__':
    run_scenario('workspace_viewer_instances', run)
