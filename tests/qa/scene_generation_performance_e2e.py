#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Paid live-backend scene generation and responsiveness replay.

Launch an isolated Dev QA app against the intended UAT backend first. This
replaces its scene through a real agent prompt; never use a user's work file.
The prompts incur real agent-token costs. No provider generation is requested.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4785 \
 QA_SCENARIO_OUT=/tmp/scene-performance \
 python3 tests/qa/scene_generation_performance_e2e.py

Every prompt is typed into the Agent island with real events. Polls and probes
only observe state. Review the saved viewport AND island PNGs before accepting
visual quality. An idle turn alone is not a successful scene assertion.
"""
import json
import os
from pathlib import Path
import socket
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA, ScenarioFail  # noqa: E402

PROMPTS = {
    'baseline': (
        'Create a small furnished cafe scene using native Blender geometry: a floor, '
        'two walls, three round wooden tables, two chairs per table, a counter, and '
        'warm lighting. Add a camera framing the whole cafe. Use simple materials '
        'and no external generated assets. Make reasonable choices and finish the scene.'
    ),
    'large': (
        'Replace the cafe with a detailed, large isometric city neighborhood built '
        'from native Blender geometry. Make an 8 by 8 grid of varied mid-rise '
        'buildings, with visible window grids on all facades, sidewalks and '
        'intersecting streets, a central park, 80 street trees, 40 parked cars, '
        'streetlights and benches. Use distinct simple materials, warm afternoon '
        'lighting and a camera that frames the full neighborhood. Keep the '
        'buildings and props individually editable. Make reasonable choices, '
        'complete the whole scene, and show a final preview. Do not use external '
        'AI-generated assets.'
    ),
}
FIELD = {'area_type': 'AGENT_BUBBLE', 'prop': 'mixie_chat_input'}
STATE = """
sc = drv.main_window().scene
result = dict(state=sc.mixie_chat_state, busy=sc.mixie_chat_is_busy,
              objects=len(sc.objects), all_objects=len(bpy.data.objects),
              session=sc.mixie_session_id,
              messages=[dict(sender=m.sender, text=m.content or m.text)
                        for m in sc.mixie_chat_messages][-4:])
"""


def send(qa, prompt):
    if not qa.find(**FIELD)['total']:
        qa.press('M', shift=True)
    qa.wait("bool(drv.find(prop='mixie_chat_input', area_type='AGENT_BUBBLE'))", timeout=8)
    count = qa.eval('result=len(drv.main_window().scene.mixie_chat_messages)')
    # set_text uses semantic geometry, native text events and Enter submission.
    qa.cmd('set_text', widget=FIELD, text=prompt, enter=True)
    qa.wait("any(m.sender=='USER' and m.text==" + repr(prompt) +
            f" for m in list(drv.main_window().scene.mixie_chat_messages)[{count}:])",
            timeout=15)


def run_case(qa, out, name, prompt):
    (out / f'{name}-prompt.txt').write_text(prompt)
    start = time.time()
    send(qa, prompt)
    records = []
    timeout = float(os.environ.get('QA_TURN_TIMEOUT', '1800'))
    while time.time() - start < timeout:
        tick = time.monotonic()
        try:
            state = qa.cmd('eval', code=STATE, _sock_timeout=7)
        except (socket.timeout, TimeoutError):
            records.append(dict(elapsed=time.time()-start, stalled=True))
            (out / f'{name}-states.json').write_text(json.dumps(records, indent=2))
            continue
        state.update(elapsed=time.time()-start, poll_seconds=time.monotonic()-tick)
        records.append(state)
        (out / f'{name}-states.json').write_text(json.dumps(records, indent=2))
        print(json.dumps({k: v for k, v in state.items() if k != 'messages'}), flush=True)
        if state['state'] == 'AWAITING_INPUT':
            raise ScenarioFail('Unexpected choice gate; inspect and record its answer before replaying')
        if state['state'] == 'IDLE' and not state['busy'] and time.time()-start > 8:
            break
        time.sleep(5)
    else:
        raise ScenarioFail(f'{name}: generation timeout')
    scene = qa.eval("""
sc = drv.main_window().scene
result = dict(objects=[dict(name=o.name, type=o.type) for o in sc.objects],
              camera=sc.camera.name if sc.camera else None,
              mesh_polygons=sum(len(o.data.polygons) for o in sc.objects if o.type=='MESH'),
              lights=sum(o.type=='LIGHT' for o in sc.objects))
""")
    (out / f'{name}-scene.json').write_text(json.dumps(scene, indent=2))
    minimum = 40 if name == 'baseline' else 300
    assert len(scene['objects']) >= minimum, scene
    assert scene['camera'] and scene['lights'] > 0, scene
    assert scene['mesh_polygons'] > (100 if name == 'baseline' else 5000), scene
    qa.snap(str(out / f'{name}-viewport.png'))
    if qa.find(**FIELD)['total']:
        qa.cmd('snap', path=str(out / f'{name}-island.png'), target=FIELD, margin=1600)
    return dict(seconds=time.time()-start, objects=len(scene['objects']),
                session=state['session'], camera=scene['camera'])


if __name__ == '__main__':
    out = Path(os.environ['QA_SCENARIO_OUT'])
    out.mkdir(parents=True, exist_ok=True)
    qa = QA()
    assert qa.status()['logged_in'] and not qa.status()['busy']
    probe = Path(__file__).with_name('scene_generation_performance_probe.py')
    qa.eval(f'exec(compile(open({str(probe)!r}).read(), {str(probe)!r}, "exec"), {{}}); result=True')
    verdict = {}
    try:
        for name, prompt in PROMPTS.items():
            verdict[name] = run_case(qa, out, name, prompt)
    finally:
        (out / 'verdict.json').write_text(json.dumps(verdict, indent=2))
