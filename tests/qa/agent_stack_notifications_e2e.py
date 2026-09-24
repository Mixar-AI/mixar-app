#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline stack/notification UX replay in an isolated Dev app.

Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT. Uses local fixture tasks,
native target bounds, real mouse events and framebuffer captures. No credits.
Inspect the screenshots alongside the state verdict.
"""
import os
from pathlib import Path
import socket
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

IMPORTS = '''from mixar.modules.agent_panel.core.cards import clear_cards, mirror_todo_items
from mixar.modules.common.notifications.store import get_notification_store, NotificationAction
from mixar.modules.common.notifications import toast_renderer as tr
store=get_notification_store()
'''
NAMES = ['Building the coastal village', 'Painting warm stone textures',
         'Shaping the wooden boardwalk', 'Lighting the evening scene',
         'Adding the final details']


def settle(qa):
    qa.eval('def settle():\n    yield 1.1\n    return True\nresult=settle()')


def mirror(qa, count, *, status='in_progress', clear=True):
    items = [dict(id=f'polish-{i}', text=name, status=status)
             for i, name in enumerate(NAMES[:count])]
    qa.eval(IMPORTS + ('clear_cards()\n' if clear else '') +
            f'mirror_todo_items({items!r})\nresult=True')
    settle(qa)


def capture(qa, out, name, hover=None):
    """Move using native targets, then capture the complete window."""
    path = str(out / (name + '.png'))
    qa.eval(f'''
def capture():
    win=drv.main_window()
    if {hover!r} is not None:
        target=drv.find_one(**{hover!r})
        x0,y0,x1,y1=target['rect']
        drv.move_to(win, (x0+x1)//2, (y0+y1)//2)
    else:
        area=next(a for a in win.screen.areas if a.type=='VIEW_3D')
        drv.move_to(win, area.x+area.width//2, area.y+area.height//2)
    yield .3
    return {path!r}
result=capture()
''')
    # This Windows build's cached-frame compositor produces a flattened image.
    # The screenshot operator reads the real complete window framebuffer.
    return qa.snap(path)


def assert_lane(qa, count):
    return qa.eval(IMPORTS + f'''
targets=drv.find(surface='toast')
assert targets, 'Notification is missing'
t=targets[0]
area=t['_area']
r=next(r for r in area.regions if r.type=='WINDOW')
cards=tr.toast_layouts_by_region[r.as_pointer()]
with bpy.context.temp_override(window=t['_win'], area=area, region=r):
    left,bottom,right,top,ceiling=r.mixar_agent_panel_bounds()
scale=bpy.context.preferences.system.ui_scale/2
expected=top+16*scale if top>bottom else bottom
assert abs(cards[0]['rect'][0]-left)<1
assert abs(cards[0]['rect'][1]-expected)<1, (cards[0]['rect'], expected)
assert abs(cards[0]['rect'][2]-(right-left))<1
for card in cards:
    x,y,w,h=card['rect']
    assert 0<=x<x+w<=r.width and 0<=y<y+h<=r.height
    assert y+h<=ceiling
for first,second in zip(cards,cards[1:]):
    assert second['rect'][1]>=first['rect'][1]+first['rect'][3]+16*scale-1
agents=drv.find(surface='agent_panel_card')
assert len(agents)=={count}, [(a['text'],a['rect']) for a in agents]
for agent in agents:
    assert agent['rect'][3] < t['rect'][1], (agent['rect'],t['rect'])
result={{'toast':t['rect'], 'cards':[a['rect'] for a in agents], 'visible_toasts':len(cards)}}
''')


def view_queue_over_short_stack(qa, out):
    """The queue toast over ONE card: its controls sit inside the panel band.

    That band used to claim every press over the card column (a bottom-aligned
    overlap clips X only), so View Queue and the close X did nothing.
    """
    qa.eval("wm=bpy.context.window_manager\nwm.mixar_bubble_tab='AGENT'\n"
            "result=str(bpy.ops.mixar.bubble_minimise())")
    qa.wait("any(w.get('value') for w in drv.find(surface='pill_cat'))", timeout=10)
    qa.eval(IMPORTS + "store.push('info','Generation in progress','marked_palm_TrunkAndFronds',"
            "id='qa-view-queue',ttl_ms=0,"
            "actions=[NotificationAction('View Queue','mixie.queue_view',style='primary')])\n"
            "result=True")
    settle(qa)
    qa.step('queue_toast_sits_in_the_panel_band', qa.eval, '''
hit=drv.find_one(surface='toast_action',value='qa-view-queue')
panel=next(r for r in hit['_area'].regions if r.type=='EXECUTE')
x0,y0,x1,y1=hit['rect']
band=[panel.x,panel.y,panel.x+panel.width,panel.y+panel.height]
assert band[0]<=x0 and x1<=band[2] and band[1]<=y0 and y1<=band[3], (hit['rect'],band)
result={'action':hit['rect'],'panel_band':band}
''')
    capture(qa, out, 'short-stack-view-queue-hover',
            {'surface': 'toast_action', 'value': 'qa-view-queue'})
    qa.click(surface='toast_action', value='qa-view-queue')
    qa.wait("bpy.context.window_manager.mixar_bubble_tab=='QUEUE' and "
            "not any(w.get('value') for w in drv.find(surface='pill_cat'))", timeout=10)
    qa.step('view_queue_opens_the_island_queue', lambda: True)
    # The island is its own OS window; the main-window capture cannot show it.
    qa.cmd('snap', path=str(out / 'short-stack-island-queue.png'),
           target={'area_type': 'AGENT_BUBBLE', 'text': 'Generation queue'}, margin=800)
    qa.click(surface='toast_close', value='qa-view-queue')
    qa.wait("not __import__('mixar.modules.common.notifications.store',fromlist=['get_notification_store'])"
            ".get_notification_store().contains('qa-view-queue')", timeout=10)
    qa.step('short_stack_toast_dismiss', lambda: True)
    qa.eval("bpy.ops.mixar.bubble_minimise()\n"
            "bpy.context.window_manager.mixar_bubble_tab='AGENT'\nresult=True")
    settle(qa)


def run(qa):
    out = Path(os.environ['QA_SCENARIO_OUT']).resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa.wait("hasattr(bpy.context.window_manager,'mixar_agent_cards_active') and "
            "hasattr(drv.main_window().scene,'mixie_chat_is_busy')", timeout=30)
    qa.eval("import os\nassert os.environ.get('MIXAR_QA')=='1'\n"
            "assert not drv.main_window().scene.mixie_chat_is_busy\nresult=True")
    qa.eval("area=next(a for a in drv.main_window().screen.areas if a.type=='VIEW_3D')\n"
            "area.spaces.active.shading.background_type='VIEWPORT'\n"
            "area.spaces.active.shading.background_color=(.015,.015,.015)\n"
            "area.tag_redraw()\nresult=True")
    mirror(qa, 5)
    qa.eval(IMPORTS + '''store.reset()
store.push('success', 'Your scene is coming together',
           'Five agents are working on the details. You can keep exploring while they create.',
           id='qa-polish', ttl_ms=0)
result=True''')
    settle(qa)
    five = qa.step('notifications_align_above_agents', assert_lane, qa, 3)
    qa.step('matching_close_size_and_alignment', qa.eval, '''
toast=drv.find_one(surface='toast_close',value='qa-polish')['rect']
task=drv.find_one(surface='agent_panel_dismiss',index=0)['rect']
assert abs((toast[2]-toast[0])-(task[2]-task[0]))<=1, (toast,task)
assert abs((toast[3]-toast[1])-(task[3]-task[1]))<=1, (toast,task)
assert abs((toast[0]+toast[2])-(task[0]+task[2]))<=2, (toast,task)
from mixar.modules.common.notifications.constants import TOAST_CORNER_RADIUS
assert TOAST_CORNER_RADIUS/2==12
result=True
''')
    capture(qa, out, 'after')
    capture(qa, out, 'notification-close-hover', {'surface':'toast_close','value':'qa-polish'})
    capture(qa, out, 'task-close-hover', {'surface':'agent_panel_dismiss','index':0})
    capture(qa, out, 'paging-hover', {'surface':'agent_panel_chevron'})
    qa.click(surface='agent_panel_chevron')
    settle(qa)
    qa.step('paging_reaches_last_agents', qa.eval,
            "assert drv.find_one(surface='agent_panel_chevron')['value']=='first'\n"
            "assert any(t['text']=='Adding the final details' for t in drv.find(surface='agent_panel_card'))\nresult=True")
    capture(qa, out, 'last-page')
    qa.click(surface='agent_panel_chevron')
    settle(qa)
    qa.step('paging_returns_to_first_agents', qa.eval,
            "assert drv.find_one(surface='agent_panel_chevron')['value']=='next'\n"
            "assert drv.find(surface='agent_panel_card')[0]['text']=='Building the coastal village'\nresult=True")

    # Only a trusted live workspace gets an eye, and its enlarged target opens it.
    qa.eval('''
main=drv.main_window().scene
main.mixie_session_id='stack-qa-main'
main.mixie_run_id='stack-qa-run'
scene=bpy.data.scenes.new('Stack QA workspace')
scene.mixie_session_id='agentlane:stack-qa-token'
scene['mixar_workspace_token']='stack-qa-token'
scene['mixar_workspace_task']='polish-0'
scene['mixar_workspace_run']=main.mixie_run_id
scene['mixar_workspace_main_session']=main.mixie_session_id
mesh=bpy.data.meshes.new('Stack QA preview mesh')
mesh.from_pydata([(x,y,z) for z in (-1,1) for y in (-1,1) for x in (-1,1)], [],
                 [(0,1,3,2),(4,6,7,5),(0,4,5,1),(2,3,7,6),(0,2,6,4),(1,5,7,3)])
obj=bpy.data.objects.new('Stack QA preview cube',mesh)
scene.collection.objects.link(obj)
result=True
''')
    qa.wait("bool(drv.find(surface='agent_panel_eye'))", timeout=10)
    capture(qa, out, 'workspace-eye', {'surface':'agent_panel_eye'})
    qa.click(surface='agent_panel_eye')
    qa.wait("bool(drv.find(surface='workspace_viewer_scene'))", timeout=10)
    qa.click(surface='workspace_viewer_close')
    qa.wait("not drv.find(surface='workspace_viewer_scene')", timeout=10)
    qa.step('workspace_eye_opens_and_closes', lambda: True)
    settle(qa)

    # A second notification grows upward, leaving the task controls reachable.
    qa.eval(IMPORTS + "store.push('warning','A little attention needed',"
            "'The texture is ready to review.',id='qa-second',ttl_ms=0)\nresult=True")
    settle(qa)
    qa.step('multiple_notifications_do_not_overlap', assert_lane, qa, 3)
    capture(qa, out, 'multiple-notifications')
    qa.click(surface='toast_close', value='qa-second')
    qa.wait("not __import__('mixar.modules.common.notifications.store',fromlist=['get_notification_store']).get_notification_store().contains('qa-second')")
    qa.step('real_toast_dismiss', lambda: True)

    mirror(qa, 2, status='failed')
    two = qa.step('short_stack_has_no_phantom_rows', assert_lane, qa, 2)
    assert two['toast'][1] < five['toast'][1]
    assert not qa.find(surface='agent_panel_chevron')['widgets']
    capture(qa, out, 'failed-agents')
    capture(qa, out, 'dismiss-hover', {'surface':'agent_panel_dismiss', 'index':0})
    qa.click(surface='agent_panel_dismiss', index=0)
    qa.wait('bpy.context.window_manager.mixar_agent_cards_active==1', timeout=10)
    settle(qa)
    qa.step('surviving_card_reflows', assert_lane, qa, 1)
    view_queue_over_short_stack(qa, out)
    qa.click(surface='agent_panel_dismiss', index=0)
    qa.wait('bpy.context.window_manager.mixar_agent_cards_active==0', timeout=10)
    settle(qa)
    qa.step('dismiss_releases_notification_anchor', assert_lane, qa, 0)
    capture(qa, out, 'no-agents')

    # Long notifications keep their close target fixed while content scrolls.
    mirror(qa, 5)
    qa.eval(IMPORTS + '''
class QA_OT_stack_action(bpy.types.Operator):
    bl_idname='wm.qa_stack_action'
    bl_label='Review details'
    def execute(self,context):
        context.window_manager['qa_stack_action']=True
        return {'FINISHED'}
bpy.utils.register_class(QA_OT_stack_action)
store.reset()
store.push('info','Review the scene details', 'A detailed update with every part preserved. '*100,
           id='qa-long',ttl_ms=0,actions=[NotificationAction('Review details','wm.qa_stack_action')])
result=True''')
    settle(qa)
    qa.step('overflow_stays_above_stack', assert_lane, qa, 3)
    capture(qa, out, 'overflow')
    qa.eval('''
def scroll():
    target=drv.find_one(surface='toast')
    win=target['_win']
    x0,y0,x1,y1=target['rect']
    x,y=(x0+x1)//2,(y0+y1)//2
    drv.move_to(win,x,y)
    yield .1
    for i in range(100):
        win.event_simulate(type='WHEELDOWNMOUSE',value='PRESS',x=x,y=y)
        yield .01
    return True
result=scroll()
''')
    qa.wait("bool(drv.find(surface='toast_action'))", timeout=10)
    capture(qa, out, 'overflow-action')
    qa.click(surface='toast_action')
    qa.wait("bool(bpy.context.window_manager.get('qa_stack_action'))")
    qa.step('overflow_action_reachable', lambda: True)

    qa.eval(IMPORTS + '''store.reset()
store.push('success','Ready when you are','The next detail is taking shape.',id='qa-final',ttl_ms=0)
area=next(a for a in drv.main_window().screen.areas if a.type=='VIEW_3D')
area.spaces.active.shading.background_type='VIEWPORT'
area.spaces.active.shading.background_color=(.8,.8,.8)
area.tag_redraw()
result=True''')
    settle(qa)
    capture(qa, out, 'bright-background')
    qa.step('bright_background_layout', assert_lane, qa, 3)
    qa.eval("bpy.utils.unregister_class(bpy.types.Operator.bl_rna_get_subclass_py('WM_OT_qa_stack_action'))\nresult=True")
    return {'backend_calls':0, 'snapshots':str(out), 'five_agents':five, 'two_agents':two}


if __name__ == '__main__':
    # The external launcher returns before the in-app server binds its socket.
    deadline = time.monotonic() + 30
    while True:
        try:
            with socket.create_connection(('127.0.0.1', int(os.environ.get('MIXAR_QA_PORT', '4777'))), timeout=1):
                break
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.1)
    run_scenario('agent_stack_notifications_e2e', run)
