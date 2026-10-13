#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""No-credit backend publication/geometry checks in an isolated real GUI app.

Set QA_HARNESS, MIXAR_QA_PORT, MIXAR_BACKEND_REPO and QA_SCENARIO_OUT.
The backend checkout supplies the actual trusted script templates/fixtures.
This leaves only QA-named objects/scenes for visual inspection; it requires
MIXAR_QA=1 and does not call a remote model or alter an existing project.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario


def run(qa):
    backend = Path(os.environ['MIXAR_BACKEND_REPO']).resolve()
    output = Path(os.environ['QA_SCENARIO_OUT']).resolve()
    output.mkdir(parents=True, exist_ok=True)
    qa.step('isolated_profile', qa.eval,
            "import os\nassert os.environ.get('MIXAR_QA') == '1'\nresult = True")
    verdict = {}
    client = Path(__file__).resolve().parents[2]
    verdict['retention'] = qa.step('retention', qa.eval, f'''
import importlib.util
import sys
name = 'mixar.modules.space_mixie_chat.core.lane_scene_sweep'
spec = importlib.util.spec_from_file_location(name, {str(client / 'src/scripts/mixar/modules/space_mixie_chat/core/lane_scene_sweep.py')!r})
sweep = importlib.util.module_from_spec(spec)
sys.modules[name] = sweep
spec.loader.exec_module(sweep)
spec = importlib.util.spec_from_file_location('qa_retention', {str(client / 'tests/qa/blender_workspace_retention.py')!r})
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
result = fixture.run(sweep)
''')
    for key, path, call in (
        ('publication', 'tests/agent/execution/blender_workspace_publication.py',
         f"fixture.run({str(backend / 'modules/agent/tools/scripts/scene_tasks')!r})"),
        ('geometry', 'tests/qa/geometry_precision_fixture.py',
         f'fixture.run_fixture({str(backend)!r})'),
    ):
        code = ('import importlib.util\n'
                f'spec = importlib.util.spec_from_file_location("qa_{key}", {str(backend / path)!r})\n'
                'fixture = importlib.util.module_from_spec(spec)\n'
                'spec.loader.exec_module(fixture)\n'
                f'result = {call}\n')
        verdict[key] = qa.step(key, qa.eval, code)
    qa.step('frame_contact', qa.eval, '''
w = drv.main_window()
area = next(a for a in w.screen.areas if a.type == 'VIEW_3D')
region = next(r for r in area.regions if r.type == 'WINDOW')
objects = [o for o in w.scene.objects if o.name.startswith('QA_Geometry_')]
assert len(objects) == 2
for obj in w.scene.objects:
    obj.select_set(obj in objects)
for obj in objects:
    obj.color = (0.12, 0.5, 0.85, 1) if obj.name.endswith('Part') else (0.65, 0.35, 0.08, 1)
w.view_layer.objects.active = objects[-1]
area.spaces.active.shading.type = 'SOLID'
area.spaces.active.shading.color_type = 'OBJECT'
area.spaces.active.overlay.show_floor = False
with bpy.context.temp_override(window=w, area=area, region=region):
    bpy.ops.view3d.view_selected(use_all_regions=False)
result = {'visible_objects': [o.name for o in objects]}
''')
    snap = str(output / 'geometry-contact.png')
    qa.step('contact_vision', qa.cmd, 'snap', path=snap, area='VIEW_3D')
    verdict['contact_image'] = snap
    (output / 'verdict.json').write_text(json.dumps(verdict, indent=2), encoding='utf-8')
    return verdict


if __name__ == '__main__':
    run_scenario('session_robustness', run)
