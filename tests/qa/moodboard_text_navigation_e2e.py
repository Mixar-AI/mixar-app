#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit replay: zoom/pan over an active node prompt without losing its draft.

Run with QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT against an isolated QA
app. Both hosts use real text, wheel and trackpad events at semantic prompt
bounds. Local scene/node fixtures avoid login and catalog dependencies.
No generation is submitted. Inspect the saved PNGs.
"""

from moodboard_drawer_e2e import (
    OUT, SCENE, geometry, point, require, run_scenario, target, toggle,
)
from moodboard_drawer_tools_e2e import resize
from moodboard_template_drag_e2e import canvas_setup, region_kind
from moodboard_redesign_e2e import snapshot as capture


def snapshot(qa, name, area):
    qa.eval("bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP',iterations=2); result=True")
    return capture(qa,name,area=area)


def state(qa, host):
    return qa.eval(canvas_setup(host) + f"""
n={SCENE}.mixie_moodboard_action_nodes[0]
a=region.view2d.region_to_view(0,0)
b=region.view2d.region_to_view(region.width,region.height)
result={{'view':[*a,*b],'width':b[0]-a[0], 'prompt':n.prompt,
         'shape':[n.position_x,n.position_y,n.width,n.height], 'job':n.job_id}}
""")


def prompt(qa, host):
    widgets=qa.find(prop='prompt',area_type=host,region_type=region_kind(host))['widgets']
    require(len(widgets)==1, f'Expected a visible node prompt: {widgets}')
    return widgets[0]


def gesture(qa, host, event, delta=0):
    # Re-read the moving control after every navigation step. Never click it:
    # the existing text editor must retain focus throughout the gesture series.
    gesture_at(qa,prompt(qa,host)['center'],event,delta)


def gesture_at(qa,xy,event,delta=0):
    x,y=xy
    qa.eval(f"""
def send():
    win=drv.main_window()
    drv.move_to(win,{x},{y})
    yield .15
    if {event!r} in ('TRACKPADZOOM','TRACKPADPAN'):
        drv._sim(win,type={event!r},value='NOTHING',x={x+delta},y={y})
    else:
        drv._sim(win,type={event!r},value='PRESS',x={x},y={y})
    yield .25
    return True
result=send()
""")


def exercise(qa, host):
    qa.eval(canvas_setup(host) + f"""
{SCENE}=bpy.data.scenes.new('QA_TEXT_NAVIGATION')
n={SCENE}.mixie_moodboard_action_nodes.add()
n.node_id='qa-text-navigation'
n.action_type='IMAGE_GEN'
n.show_prompt=True
n.selected=True
x,y=region.view2d.region_to_view(region.width*.5,region.height*.5)
n.position_x=x-n.width*.5
n.position_y=y-n.height*.5
{SCENE}.mixie_moodboard_active_node_id=n.node_id
bpy.ops.mixie.moodboard_ensure_visible(x=n.position_x,y=n.position_y,
                                     width=n.width,height=n.height,margin=250)
[a.tag_redraw() for a in win.screen.areas]
result=True
""")
    qa.wait(f"len(drv.find(prop='prompt',area_type={host!r}))==1", timeout=5)
    # Start already zoomed in, matching the reported trap.
    for _ in range(2):
        gesture(qa,host,'WHEELUPMOUSE')
    qa.click(prop='prompt',area_type=host,region_type=region_kind(host))
    qa.cmd('type',text='Keep this draft')
    original=state(qa,host)
    require(original['prompt']=='Keep this draft','Prompt did not enter editing')
    qa.press('LEFT_ARROW')
    snapshot(qa,host+'-editing-before',area=host)
    evidence=[]
    for event,delta,direction in (
        ('WHEELDOWNMOUSE',0,1),('WHEELUPMOUSE',0,-1),
        ('TRACKPADZOOM',12,1),('TRACKPADZOOM',-12,-1),
        ('TRACKPADPAN',12,0),
    ):
        before=state(qa,host)
        gesture(qa,host,event,delta)
        after=state(qa,host)
        require(after['view']!=before['view'],f'{host}: {event} was trapped by text focus')
        if direction:
            require((after['width']-before['width'])*direction>0,
                    f'{host}: {event} zoomed in the wrong direction')
        require(after['shape']==original['shape'],'Navigation changed node geometry')
        require(after['prompt']==original['prompt'],'Navigation changed the draft')
        require(not after['job'],'Navigation submitted a generation')
        evidence.append({'event':event,'delta':delta,'width':after['width']})
        snapshot(qa,host+'-'+event+str(delta),area=host)
    # Insertion at the original caret proves that navigation did not just
    # terminate editing and commit the draft to make room for a zoom operator.
    qa.cmd('type',text='X')
    require(state(qa,host)['prompt']=='Keep this drafXt','Text focus or caret was lost')
    snapshot(qa,host+'-editing-after',area=host)
    qa.press('ESC')
    return {'host':host,'gestures':evidence,'focus_and_caret_preserved':True}



def textbox_state(qa,host):
    return qa.eval(canvas_setup(host) + f"""
t={SCENE}.mixie_moodboard_textboxes[0]
a=region.view2d.region_to_view(0,0)
b=region.view2d.region_to_view(region.width,region.height)
p=region.view2d.view_to_region(t.position_x+t.width*.5,t.position_y+t.height*.5,clip=False)
result={{'view':[*a,*b],'width':b[0]-a[0],'text':t.text,
         'center':[p[0]+region.x,p[1]+region.y],
         'size':[t.width,t.height,t.font_size]}}
""")


def exercise_textbox(qa,host):
    qa.click(op='MIXIE_OT_moodboard_add_textbox',area_type=host)
    xy=point(target(qa,'moodboard_canvas',area_type=host),.5,.5)
    before=textbox_state(qa,host)
    gesture_at(qa,(xy['x'],xy['y']),'WHEELUPMOUSE')
    require(textbox_state(qa,host)['width']<before['width'],
            'Text placement blocked wheel zoom')
    qa.cmd('click_xy',**xy)
    # Simulated events do not classify double-clicks; invoke the same editor
    # through a temporary keymap item, then exercise real typing/navigation.
    qa.eval("km=bpy.context.window_manager.keyconfigs.addon.keymaps['Mixie']; "
            "k=km.keymap_items.new('mixie.moodboard_edit_textbox','F19','PRESS'); "
            "k.properties.index=0; result=True")
    try:
        qa.press('F19')
        qa.cmd('type',text='Inline draft')
        before=textbox_state(qa,host)
        require(before['text']=='Inline draft|','Inline editor did not activate')
        snapshot(qa,host+'-textbox-before',area=host)
        for event,delta,direction in (
            ('WHEELDOWNMOUSE',0,1),('WHEELUPMOUSE',0,-1),
            ('TRACKPADZOOM',12,1),('TRACKPADZOOM',-12,-1),
        ):
            before=textbox_state(qa,host)
            gesture_at(qa,before['center'],event,delta)
            after=textbox_state(qa,host)
            require((after['width']-before['width'])*direction>0,
                    f'Inline text trapped {event}')
            require(after['text']==before['text'] and after['size']==before['size'],
                    'Navigation changed inline text or its size')
        qa.cmd('type',text=' retained')
        qa.press('RET')
        require(textbox_state(qa,host)['text']=='Inline draft retained',
                'Inline editing could not continue after zoom')
        snapshot(qa,host+'-textbox-after',area=host)
    finally:
        qa.press('ESC')
        qa.eval("km=bpy.context.window_manager.keyconfigs.addon.keymaps['Mixie']; "
                "[km.keymap_items.remove(k) for k in list(km.keymap_items) "
                "if k.type=='F19' and k.idname=='mixie.moodboard_edit_textbox']; result=True")
    return {'placement_and_inline_zoom':True,'continued_typing':True}

def run(qa):
    OUT.mkdir(parents=True,exist_ok=True)
    require(qa.eval("result=__import__('os').environ.get('MIXAR_QA')=='1'"),'Use an isolated QA app')
    qa.dismiss_splash()
    qa.eval("next(a for a in drv.main_window().screen.areas "
            "if a.type in {'VIEW_3D','MIXIE'}).type='VIEW_3D'; result=True")
    if geometry(qa)['amount']<.02:
        toggle(qa,1)
    resize(qa,720)
    evidence=[]
    for host in ('VIEW_3D','MIXIE'):
        if host=='MIXIE':
            qa.eval("next(a for a in drv.main_window().screen.areas if a.type=='VIEW_3D').type='MIXIE'; result=True")
        evidence.append(qa.step(host+'_text_navigation',exercise,qa,host))
        evidence.append(qa.step(host+'_textbox_navigation',exercise_textbox,qa,host))
    return {'hosts':evidence,'backend_submissions':0,'screenshots':str(OUT)}


if __name__=='__main__':
    run_scenario('moodboard_text_navigation_e2e',run)
