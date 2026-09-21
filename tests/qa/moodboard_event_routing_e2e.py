#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Native keymap regression for mouse-leave and timer delivery in both hosts.

Use an isolated QA app and QA_HARNESS/MIXAR_QA_PORT/QA_SCENARIO_OUT.
A temporary PASS_THROUGH operator observes the real Mixie/View2D keymap
handlers. Pointer movement uses native events; timers come from the WM.
The observer, bindings and timer are removed even when an assertion fails.
No generation jobs, scene edits or user preference writes are performed.
"""

from moodboard_drawer_e2e import OUT, geometry, require, run_scenario, target, toggle
from moodboard_drawer_tools_e2e import resize
from moodboard_redesign_e2e import BOARD
from moodboard_template_drag_e2e import canvas_setup, region_kind


INSTALL = """
state={'events':[], 'host':'VIEW_3D', 'region':'TOOL_PROPS', 'bindings':[]}
bpy.app.driver_namespace['qa_moodboard_events']=state
class QA_OT_moodboard_event_probe(bpy.types.Operator):
    bl_idname='qa.moodboard_event_probe'
    bl_label='QA moodboard event probe'
    lane: bpy.props.StringProperty()
    def invoke(self, context, event):
        s=bpy.app.driver_namespace['qa_moodboard_events']
        if (context.area and context.region and context.area.type==s['host']
                and context.region.type==s['region']):
            s['events'].append([self.lane,event.type,event.mouse_x,event.mouse_y])
            s['events']=s['events'][-256:]
        return {'PASS_THROUGH'}
bpy.utils.register_class(QA_OT_moodboard_event_probe)
state['class']=QA_OT_moodboard_event_probe
kc=bpy.context.window_manager.keyconfigs.addon
for name,space in [('Mixie','MIXIE'),('View2D','EMPTY')]:
    km=kc.keymaps.get(name) or kc.keymaps.new(name=name,space_type=space,region_type='WINDOW')
    for event in ('MOUSEMOVE','TIMER','TIMER1','WINDOW_DEACTIVATE'):
        item=km.keymap_items.new('qa.moodboard_event_probe',event,'ANY',head=True)
        item.properties.lane=name
        state['bindings'].append((km,item))
state['timer']=bpy.context.window_manager.event_timer_add(.05,window=drv.main_window())
result=True
"""


def cleanup(qa):
    qa.eval("""
s=bpy.app.driver_namespace.pop('qa_moodboard_events',None)
if s:
    if s.get('timer'):
        bpy.context.window_manager.event_timer_remove(s['timer'])
    for km,item in s['bindings']:
        km.keymap_items.remove(item)
    bpy.utils.unregister_class(s['class'])
result=True
""")


def move(qa, host, xy, start=None):
    return qa.eval(canvas_setup(host) + f"""
def gesture():
    s=bpy.app.driver_namespace['qa_moodboard_events']
    s['host'],s['region']={host!r},{region_kind(host)!r}
    if {start!r}:
        drv.move_to(win,*{start!r})
        yield .2
    s['events']=[]
    drv.move_to(win,*{xy!r})
    yield .3
    return list(s['events'])
result=gesture()
""")


def delivered(events, lane, event):
    require(any(e[:2] == [lane, event] for e in events),
            f'{lane} did not receive {event}: {events}')


def canvas_baseline(qa, host):
    rect = target(qa, 'moodboard_canvas', area_type=host)['rect']
    center = (round((rect[0]+rect[2])/2), round((rect[1]+rect[3])/2))
    events = move(qa, host, center)
    delivered(events, 'Mixie', 'TIMER')
    if host == 'VIEW_3D':
        delivered(events, 'View2D', 'TIMER')
    return events


def timer_over_chrome(qa, host):
    button = qa.find(**BOARD, area_type=host)['widgets'][0]
    events = move(qa, host, tuple(button['center']))
    delivered(events, 'Mixie', 'MOUSEMOVE')
    delivered(events, 'Mixie', 'TIMER')
    if host == 'VIEW_3D':
        delivered(events, 'View2D', 'MOUSEMOVE')
        delivered(events, 'View2D', 'TIMER')
    return events


def leave_canvas(qa, host):
    rect = target(qa, 'moodboard_canvas', area_type=host)['rect']
    start = (round((rect[0]+rect[2])/2), round((rect[1]+rect[3])/2))
    # A single native move retains prev_xy inside the canvas mask.
    outside = (rect[0]-20, start[1]) if host == 'VIEW_3D' else (start[0], rect[3]+12)
    events = move(qa, host, outside, start)
    # Native routing sends standalone header motion to that separate region;
    # only the drawer gutter retains the original region for the leave event.
    # Both original canvas handlers must still receive timers while outside.
    delivered(events, 'Mixie', 'TIMER')
    if host == 'VIEW_3D':
        delivered(events, 'Mixie', 'MOUSEMOVE')
        delivered(events, 'View2D', 'MOUSEMOVE')
        delivered(events, 'View2D', 'TIMER')
    return events


def always_pass_outside(qa, host):
    events = qa.eval(canvas_setup(host) + """
def gesture():
    s=bpy.app.driver_namespace['qa_moodboard_events']
    s['events']=[]
    # The preceding leave step parked the pointer outside the canvas.
    drv._sim(win,type='TIMER1',value='NOTHING')
    drv._sim(win,type='WINDOW_DEACTIVATE',value='NOTHING')
    yield .3
    return list(s['events'])
result=gesture()
""")
    for lane in ('Mixie', 'View2D') if host == 'VIEW_3D' else ('Mixie',):
        for event in ('TIMER1', 'WINDOW_DEACTIVATE'):
            delivered(events, lane, event)
    return events


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    require(qa.eval("result=__import__('os').environ.get('MIXAR_QA')=='1'"), 'Use isolated QA')
    qa.cmd('wait_login', timeout=90)
    qa.eval('bpy.ops.mixar.agent_bubble_purge_windows();result=True')
    if geometry(qa)['amount'] < .98:
        toggle(qa, 1)
    resize(qa, 850)
    cleanup(qa)
    result = {}
    try:
        qa.eval(INSTALL)
        for host in ('VIEW_3D', 'MIXIE'):
            if host == 'MIXIE':
                qa.eval("next(a for a in drv.main_window().screen.areas if a.type=='VIEW_3D').type='MIXIE';result=True")
                qa.wait("bool(drv.find(area_type='MIXIE',surface='moodboard_canvas'))", timeout=5)
            for name, check in (('canvas_baseline', canvas_baseline),
                                ('timer_over_chrome', timer_over_chrome),
                                ('leave_canvas', leave_canvas),
                                ('always_pass_outside', always_pass_outside)):
                key = f'{host}-{name}'
                result[key] = qa.step(key, check, qa, host)
            qa.cmd('snap', path=str(OUT/f'{host}-event-routing.png'), area=host)
        return result
    finally:
        cleanup(qa)


if __name__ == '__main__':
    run_scenario('moodboard_event_routing_e2e', run)
