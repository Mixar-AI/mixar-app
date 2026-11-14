#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""No-credit live QA of island multi-image dispatch.

Run in a fresh isolated QA app:
QA_HARNESS=/path/to/mixar-qa-harness python this_file.py
Optional QA_SCENARIO_OUT selects the artifact directory.
Fixtures seed selection; the real native Generate button drives dispatch,
encoding and queue admission. Only the queue pump is held (no HTTP requests).
This does not verify provider generation or GLB download/import.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/mixar-multi-image-qa'))
    out.mkdir(parents=True, exist_ok=True)
    qa.step('isolate-and-hold-network-dispatch', qa.eval, '''
import os
assert os.environ.get('MIXAR_QA') == '1'
from mixar.modules.common.job_queue.core import queue_manager as qm
assert not any(q._jobs for q in qm.all_queues()), 'Needs empty QA queues'
assert not hasattr(qm, '_qa_original_pump')
qm._qa_original_pump = qm.FeatureQueue._pump
qm.FeatureQueue._pump = lambda self: None
result = True
''')
    try:
        qa.step('seed-three-selected-one-unselected', qa.eval, f'''
from mixar.modules.onboarding.core.tour import session
if session.is_running():
    session.current().stop('exited')
s = drv.main_window().scene
s.mixie_moodboard_images.clear()
for name, color in [('QA_Red', (1,0,0,1)), ('QA_Green', (0,1,0,1)),
                    ('QA_Blue', (0,0,1,1)), ('QA_Unselected', (1,1,0,1))]:
    previous = bpy.data.images.get(name)
    if previous:
        bpy.data.images.remove(previous)
    image = bpy.data.images.new(name, width=64, height=64)
    image.generated_color = color
    image.filepath_raw = {str(out)!r} + '/' + name + '.png'
    image.file_format = 'PNG'
    image.save()
    item = s.mixie_moodboard_images.add()
    item.image = image
    item.selected = name != 'QA_Unselected'
    item.node_id = name
    item.position = (len(s.mixie_moodboard_images)*220, 0)
tab = s.mixie_moodboard_sidebar.tab_image_to_3d
tab.use_selected_image = True
tab.prompt = ''
result = str(bpy.ops.mixar.agent_bubble_show_window())
''')
        if qa.eval("result=bpy.context.window_manager.mixar_bubble_tab") != 'THREE_D':
            qa.click(area_type='AGENT_BUBBLE', text='3D generation')
        qa.wait("bpy.context.window_manager.mixar_bubble_tab == 'THREE_D'", timeout=5)
        target = {'area_type': 'AGENT_BUBBLE', 'op': 'MIXIE_OT_moodboard_prompt_generate'}
        qa.cmd('snap', path=str(out/'references.png'), target=target, margin=1600)
        results = []
        for click_count in (1, 2):
            qa.step(f'native-generate-click-{click_count}', qa.click, **target)
            result = qa.step(f'assert-{3*click_count}-distinct-jobs', qa.eval, f'''
import base64, hashlib, io
from PIL import Image
from mixar.modules.common.job_queue.core.queue_manager import all_queues
jobs = [j for q in all_queues() for j in q._jobs]
assert len(jobs) == {3*click_count}, [(j.display_label,j.state.value) for j in jobs]
assert len({{j.label for j in jobs}}) == len(jobs)
expected = {{'QA_Red': 0, 'QA_Green': 1, 'QA_Blue': 2}}
rows = []
for j in jobs:
    assert j.state.value == 'PENDING' and not j.backend_job_id
    assert j.display_label in expected
    raw = base64.b64decode(j.payload['image_bytes_b64'])
    im = Image.open(io.BytesIO(raw)).convert('RGB')
    rgb = im.getpixel((im.width//2, im.height//2))
    # Build-specific view transforms/JPEG can shift exact RGB; identity is
    # the dominant channel, while the byte hashes prove distinct inputs.
    channel = expected[j.display_label]
    assert rgb[channel] > max(v for i,v in enumerate(rgb) if i != channel) + 80, (j.display_label,rgb)
    rows.append({{'label':j.display_label,'state':j.state.value,
                  'pixel':rgb,'image_sha256':hashlib.sha256(raw).hexdigest()}})
assert len({{r['image_sha256'] for r in rows}}) == 3
assert all(sum(r['label'] == name for r in rows) == {click_count} for name in expected)
result = rows
''')
            results.append(result)
            qa.cmd('snap', path=str(out/f'queued-{click_count}.png'), target=target, margin=1600)
        qa.click(area_type='AGENT_BUBBLE', text='Generation queue')
        qa.cmd('snap', path=str(out/'queue.png'), target={'area_type':'AGENT_BUBBLE', 'text':'Generation queue'}, margin=1800)
        return {'jobs_after_first_click':results[0], 'jobs_after_second_click':results[1],
                'scope':'Native UI through encoded real queue admission; network pump held',
                'screenshots':[str(out/name) for name in ('references.png','queued-1.png','queued-2.png','queue.png')]}
    finally:
        qa.eval('''
from mixar.modules.common.job_queue.core import queue_manager as qm
for q in qm.all_queues():
    q.cancel_all()
    q.clear_completed()
qm.FeatureQueue._pump = qm._qa_original_pump
del qm._qa_original_pump
result = True
''')


if __name__ == '__main__':
    run_scenario('image_to_3d_multi_image_e2e', run)
