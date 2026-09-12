#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Main cat follows real chat/voice/queue RNA; local fixtures, zero credits.

QA_HARNESS=/path/to/harness QA_SCENARIO_OUT=/tmp/cat-activity \
    python3 tests/qa/cat_activity_e2e.py
Inspect contact sheets/GIFs with verdict. No claim of measured display vsync.
"""

import inspect
import json
import os
from pathlib import Path
import sys
from PIL import Image

sys.path.insert(0, str(Path(os.environ['QA_HARNESS'])/'scenarios'))
from lib import run_scenario
from compact_agent_bubble_e2e import _hover_off, _hover_on
from zen_motion_capture import contact_sheet, preview


def _record(output, activity):
    import time
    from pathlib import Path
    import bpy
    import qa_driver as drv

    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    wm = bpy.context.window_manager
    scene = drv.main_window().scene
    agent = next(m for m in scene.mixie_chat_messages if m.bubble_id == 'qa-cat-agent')
    scene.mixie_chat_state = 'IDLE'
    scene.mixie_chat_is_busy = False
    wm.mixie_chat_voice_listening = False
    agent.thinking_active = False
    agent.content = ''
    agent.step_items.clear()
    for index in reversed(range(len(wm.mixie_queue.items))):
        if wm.mixie_queue.items[index].job_id == 'qa-cat-generation':
            wm.mixie_queue.items.remove(index)
    if activity in ('Thinking', 'Reading', 'Working', 'Responding'):
        scene.mixie_chat_state = 'BUSY'
        scene.mixie_chat_is_busy = True
        agent.thinking_active = activity == 'Thinking'
        if activity in ('Reading', 'Working'):
            step = agent.step_items.add()
            step.kind = 'READ' if activity == 'Reading' else 'COMMAND'
            step.status = 'RUNNING'
            step.label = 'Read scene' if activity == 'Reading' else 'Build scene'
        if activity == 'Responding':
            agent.content = 'The scene is ready.'
    elif activity == 'Waiting for you':
        scene.mixie_chat_state = 'AWAITING_INPUT'
        scene.mixie_chat_is_busy = True
        # Waiting must override old running/thinking slots and a busy flag.
        agent.thinking_active = True
    elif activity == 'Listening':
        wm.mixie_chat_voice_listening = True
    elif activity in ('Offline', 'Connecting'):
        scene.mixie_chat_state = activity.upper()
    elif activity == 'Generating':
        item = wm.mixie_queue.items.add()
        item.job_id = 'qa-cat-generation'
        item.state = 'RUNNING'
    elif activity == 'Idle':
        # Stale completed transcript signals must not keep the mascot active.
        agent.thinking_active = True
        step = agent.step_items.add()
        step.kind = 'COMMAND'
        step.status = 'RUNNING'
    yield .05
    target = drv.find_one(surface='pill_cat')
    win = target['_win']
    bounds = target['rect']
    x0,y0,x1,y1 = bounds
    frames=[]
    began=time.monotonic()
    while time.monotonic()-began < 2.0:
        current = drv.find_one(surface='pill_cat')
        path=out/f'frame-{len(frames):03}.png'
        with bpy.context.temp_override(window=win):
            assert win.mixar_qa_capture_frame(filepath=str(path), x=max(0,x0-2),
                y=max(0,y0-2), width=x1-x0+4, height=y1-y0+4)
        frames.append(dict(time=time.monotonic()-began, path=str(path),
                           rect=current['rect'], activity=current['value']))
        yield .04
    with bpy.context.temp_override(window=win):
        assert win.mixar_qa_capture_frame(filepath=str(out/'pill.png'))
    return frames


def capture(qa, out, activity):
    frames=qa.eval(inspect.getsource(_record)+f'\nresult=_record({str(out)!r},{activity!r})')
    assert all(frame['activity']==activity for frame in frames), frames
    assert len({tuple(frame['rect']) for frame in frames}) == 1
    signatures=[]
    for frame in frames:
        with Image.open(frame['path']) as image:
            signatures.append(image.convert('RGB').tobytes())
    assert len(set(signatures)) >= 8, 'Mascot did not animate visibly'
    preview(frames, out/'motion.gif')
    contact_sheet(frames, out/'frames.png')
    (out/'samples.json').write_text(json.dumps(frames, indent=2)+'\n')
    return dict(activity=activity, frames=len(frames), appearances=len(set(signatures)),
                rect=frames[-1]['rect'])


def run(qa):
    out=Path(os.environ.get('QA_SCENARIO_OUT','/tmp/cat-activity'))
    out.mkdir(parents=True,exist_ok=True)
    qa.step('ready',qa.cmd,'wait_login',timeout=60)
    _hover_off(qa)
    saved=qa.eval('''
scene=drv.main_window().scene
wm=bpy.context.window_manager
result=dict(state=scene.mixie_chat_state, busy=scene.mixie_chat_is_busy,
            voice=wm.mixie_chat_voice_listening)
user=scene.mixie_chat_messages.add()
user.bubble_id='qa-cat-user'
user.sender='USER'
user.text='Build a welcoming little scene'
agent=scene.mixie_chat_messages.add()
agent.bubble_id='qa-cat-agent'
agent.sender='AGENT'
bpy.ops.mixar.bubble_minimise()
''')
    try:
        qa.wait("bool(drv.find(surface='pill_cat'))",timeout=10)
        qa.eval('def settle():\n    yield .4\n    return True\nresult=settle()')
        results={}
        for activity in ('Idle','Thinking','Reading','Working','Generating','Responding',
                         'Waiting for you','Listening','Connecting','Offline','Idle'):
            name=activity.lower().replace(' ','-')
            results[name]=qa.step(name,capture,qa,out/name,activity)
        qa.eval("scene=drv.main_window().scene\nscene.mixie_chat_state='IDLE'\n"
                "scene.mixie_chat_is_busy=False\nresult=True")
        # Real pill click must still open the island; native rectangle comes from QA.
        qa.step('cat_click_opens_island',qa.click,surface='pill_cat')
        qa.wait("bool(drv.find(area_type='AGENT_BUBBLE',text='Agent chat'))",timeout=10)
        results['paid_requests']=0
        (out/'verdict.json').write_text(json.dumps(results,indent=2)+'\n')
        return results
    finally:
        qa.eval(f'''
scene=drv.main_window().scene
wm=bpy.context.window_manager
scene.mixie_chat_state={saved['state']!r}
scene.mixie_chat_is_busy={saved['busy']!r}
wm.mixie_chat_voice_listening={saved['voice']!r}
for i in reversed(range(len(scene.mixie_chat_messages))):
    if scene.mixie_chat_messages[i].bubble_id in ('qa-cat-user','qa-cat-agent'):
        scene.mixie_chat_messages.remove(i)
for i in reversed(range(len(wm.mixie_queue.items))):
    if wm.mixie_queue.items[i].job_id=='qa-cat-generation':
        wm.mixie_queue.items.remove(i)
result=True
''')
        _hover_on(qa)


if __name__=='__main__':
    run_scenario('cat_activity_e2e',run)
