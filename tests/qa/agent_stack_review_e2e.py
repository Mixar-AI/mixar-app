#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline regression replay for fractional-scale paging and idle hover feedback.

Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT for an isolated Dev app.
Captures do not request redraws: mouse movement must repaint settled controls.
"""
import inspect
import os
from pathlib import Path
import sys

from PIL import Image, ImageChops, ImageStat

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from agent_stack_notifications_e2e import IMPORTS, mirror, settle


def setup(qa):
    qa.wait("hasattr(bpy.context.window_manager,'mixar_agent_cards_active')", timeout=30)
    qa.eval("import os\nassert os.environ.get('MIXAR_QA')=='1'\n"
            "assert not drv.main_window().scene.mixie_chat_is_busy\nresult=True")
    qa.eval(IMPORTS + '''store.reset()
area=next(a for a in drv.main_window().screen.areas if a.type=='VIEW_3D')
area.spaces.active.shading.background_type='VIEWPORT'
area.spaces.active.shading.background_color=(.015,.015,.015)
main=drv.main_window().scene
main.mixie_session_id='stack-hover-main'
main.mixie_run_id='stack-hover-run'
scene=bpy.data.scenes.new('Stack hover workspace')
scene.mixie_session_id='agentlane:stack-hover-token'
scene['mixar_workspace_token']='stack-hover-token'
scene['mixar_workspace_task']='polish-0'
scene['mixar_workspace_run']=main.mixie_run_id
scene['mixar_workspace_main_session']=main.mixie_session_id
result=True''')
    mirror(qa, 5, status='pending')


def paging(qa, out, scale):
    qa.eval(f'bpy.context.preferences.view.ui_scale={scale}\nresult=True')
    settle(qa)
    mirror(qa, 5, status='pending')
    first = qa.eval('''
cards=drv.find(surface='agent_panel_card')
assert len(cards)==3, cards
target=drv.find_one(surface='agent_panel_chevron')
assert target['detail']=='2 more agents', target
result={'scale':bpy.context.preferences.system.ui_scale, 'label':target['detail']}
''')
    qa.snap(str(out / f'scale-{scale}.png'))
    qa.eval('''def scroll():
    target=drv.find_one(surface='agent_panel_card',index=1)
    win=target['_win']
    x0,y0,x1,y1=target['rect']
    drv.move_to(win,(x0+x1)//2,(y0+y1)//2)
    yield .1
    for _ in range(2):
        drv._sim(win,type='WHEELDOWNMOUSE',value='PRESS')
        yield .1
    return True
result=scroll()''')
    qa.eval("target=drv.find_one(surface='agent_panel_chevron')\n"
            "assert target['detail']=='1 more agent', target\nresult=True")
    qa.click(surface='agent_panel_chevron')
    qa.eval("target=drv.find_one(surface='agent_panel_chevron')\n"
            "assert target['detail']=='Back to first', target\nresult=True")
    qa.click(surface='agent_panel_chevron')
    qa.eval("target=drv.find_one(surface='agent_panel_chevron')\n"
            "assert target['detail']=='2 more agents', target\nresult=True")
    return first


def _hover_frames(query, output):
    """Runs inside the app without a redraw request or an animation timer."""
    import qa_driver as drv
    import qa_vision

    target = drv.find_one(**query)
    win = target['_win']
    body = drv.find_one(surface='agent_panel_card', index=0)
    bx0, by0, bx1, by1 = body['rect']
    tx0, ty0, tx1, ty1 = target['rect']
    # All three positions stay in the same EXECUTE region.
    points = [((bx0+bx1)//2, (by0+by1)//2),
              ((tx0+tx1)//2, (ty0+ty1)//2),
              ((bx0+bx1)//2, (by0+by1)//2)]
    paths = []
    for name, (x, y) in zip(('idle', 'hover', 'leave'), points):
        drv.move_to(win, x, y)
        yield .3
        path = output + '-' + name + '.png'
        qa_vision._capture(win, path)
        paths.append(path)
    return {'paths': paths, 'rect': target['rect']}


def hover(qa, out, surface):
    query = {'surface': surface}
    if surface != 'agent_panel_chevron':
        query['index'] = 0
    frames = qa.eval(inspect.getsource(_hover_frames) +
                     f'\nresult=_hover_frames({query!r}, {str(out / surface)!r})')
    crops = []
    for path in frames['paths']:
        with Image.open(path) as image:
            x0, y0, x1, y1 = frames['rect']
            crops.append(image.convert('RGB').crop((x0, image.height-y1, x1, image.height-y0)))
    entered = sum(ImageStat.Stat(ImageChops.difference(crops[0], crops[1])).mean) / 3
    left = sum(ImageStat.Stat(ImageChops.difference(crops[0], crops[2])).mean) / 3
    assert entered > 3, f'{surface}: hover did not repaint ({entered:.2f})'
    assert left < .5, f'{surface}: hover did not clear ({left:.2f})'
    sheet = Image.new('RGB', (crops[0].width * 3, crops[0].height))
    for index, crop in enumerate(crops):
        sheet.paste(crop, (index * crop.width, 0))
    sheet.save(out / f'{surface}-sequence.png')
    return {'hover_pixel_delta': round(entered, 2), 'leave_pixel_delta': round(left, 2)}


def run(qa):
    out = Path(os.environ['QA_SCENARIO_OUT']).resolve()
    out.mkdir(parents=True, exist_ok=True)
    saved = qa.eval('result=bpy.context.preferences.view.ui_scale')
    try:
        setup(qa)
        scales = [qa.step(f'paging_at_scale_{scale}', paging, qa, out, scale)
                  for scale in (1.0, 1.1, 1.2, 1.25, 1.5)]
        qa.eval('bpy.context.preferences.view.ui_scale=1.0\nresult=True')
        settle(qa)
        states = {surface: qa.step(f'idle_hover_{surface}', hover, qa, out, surface)
                  for surface in ('agent_panel_eye', 'agent_panel_dismiss', 'agent_panel_chevron')}
        return {'backend_calls': 0, 'scales': scales, 'hover': states}
    finally:
        qa.eval(f'bpy.context.preferences.view.ui_scale={saved}\nresult=True')


if __name__ == '__main__':
    run_scenario('agent_stack_review_e2e', run)
