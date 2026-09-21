#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit native corner/padding regression in both hosts and UI scales.

Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT; requires Pillow. Reference
and completed-node images are explicit fixtures. Native clicks/type/wheel
exercise layout and caret placement; inspect the captured corners as well.
"""
import time
from PIL import Image, ImageChops

from moodboard_drawer_e2e import (
    OUT, SCENE, drop, geometry, png, require, run_scenario, target, toggle,
)
from moodboard_drawer_tools_e2e import resize
from moodboard_redesign_e2e import menu, add, LABELS, KINDS
from moodboard_node_position_e2e import center_fixture, card, context
from moodboard_media_chrome_e2e import center as center_media


def snap(qa, name, **query):
    path = OUT / f'{name}.png'
    qa.cmd('snap', path=str(path), **query)
    return Image.open(path).convert('RGB')


def pixel(image, x, y):
    return image.getpixel((round(x), image.height-1-round(y)))


def set_prompt(qa, text):
    qa.eval(f"""
n={SCENE}.mixie_moodboard_action_nodes[0]
n.prompt={text!r}
for a in drv.main_window().screen.areas:
    a.tag_redraw()
bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=2)
result=True
""")


def prompt_padding(qa, host, prefix):
    center_fixture(qa, host, True)
    set_prompt(qa, '')
    query = {'area_type':host, 'prop':'prompt',
             'region_type':'TOOL_PROPS' if host=='VIEW_3D' else 'WINDOW'}
    field = qa.find(**query)['widgets'][0]
    x0,y0,x1,y1 = field['layout_rect']
    settings = qa.find(area_type=host, op='MIXIE_OT_moodboard_node_settings')['widgets'][0]
    inset = settings['layout_rect'][0]-card(qa,host)[0]
    image = snap(qa,prefix+'-placeholder',target=query,margin=0)
    r,g,b = image.split()
    ink = ImageChops.darker(ImageChops.darker(r,g),b).point(lambda v:255 if v>65 else 0)
    bbox = ink.getbbox()
    require(bbox and bbox[0]>=inset-2 and bbox[1]>=inset-2,
            f'Placeholder crowds its rounded corner: {bbox}, inset={inset}')
    qa.click(**query)
    qa.cmd('type',text='Rounded corners keep text clear')
    qa.wait(f"{SCENE}.mixie_moodboard_action_nodes[0].prompt=='Rounded corners keep text clear'",timeout=5)
    qa.press('HOME')
    field = qa.find(**query)['widgets'][0]
    points = field['text_edit']['carets']
    first = next(p for p in points if p['byte']==0)
    require(abs(first['x']-x0-inset)<=3, 'Caret and placeholder use different left padding')
    require(y1-first['y']>=inset, 'Caret crowds the top curve')
    point = next(p for p in points if p['byte']==8)
    qa.cmd('click_xy',x=point['x']+1,y=point['y'])
    qa.cmd('type',text='X')
    require(qa.eval(f'result={SCENE}.mixie_moodboard_action_nodes[0].prompt') ==
            'Rounded Xcorners keep text clear', 'Inset text hit-test disagrees with the glyphs')
    snap(qa,prefix+'-editing')
    qa.press('ESC')
    # Native zoom must not collapse the outer curve around fixed-size controls.
    for i,key in enumerate(('WHEELUPMOUSE','WHEELDOWNMOUSE')):
        node = target(qa,'moodboard_node',area_type=host)
        qa.eval(f"drv.move_to(drv.main_window(),{node['center'][0]},{node['center'][1]});result=True")
        qa.press(key);qa.press(key)
        snap(qa,f'{prefix}-zoom-{i}',target={'surface':'moodboard_node','area_type':host},margin=40)
    return {'padding':inset}


def media_corners(qa, host, media_id, prefix):
    center_media(qa,host,initial=True)
    qa.eval(f"{SCENE}.mixie_moodboard_images[0].selected=False\n"
            f"{SCENE}.mixie_moodboard_action_nodes[0].position_x=-100000\n"
            "for a in drv.main_window().screen.areas:\n    a.tag_redraw()\n"
            "bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=2)\nresult=True")
    image=snap(qa,prefix+'-media')
    rect=target(qa,'moodboard_media',text=media_id,area_type=host)['rect']
    zoom=qa.eval(f"a=next(a for a in drv.main_window().screen.areas if a.type=={host!r}); "
                f"r=next(r for r in a.regions if r.type=={'TOOL_PROPS' if host=='VIEW_3D' else 'WINDOW'!r}); "
                "a=r.view2d.region_to_view(0,0);b=r.view2d.region_to_view(100,0);result=100/(b[0]-a[0])")
    offset=6*zoom*.5
    require(offset>=2, 'Fixture does not resolve the frame corner')
    for x,y,sx,sy in ((rect[0],rect[1],-1,-1),(rect[2],rect[1],1,-1),
                      (rect[0],rect[3],-1,1),(rect[2],rect[3],1,1)):
        color=pixel(image,x+sx*offset,y+sy*offset)
        require(max(color)-min(color)<5 and 35<=min(color)<=70,
                f'Frame pinches away beside a square image corner: {color}')
    # A finished-node preview uses the same square-content border rule.
    qa.eval(context(host)+"""
node.preview_image=win.scene.mixie_moodboard_images[0].image
win.scene.mixie_moodboard_images[0].position_x=-100000
node.state='SUCCESS'
node.edit_mode=False
node.selected=True
win.scene.mixie_moodboard_active_node_id=node.node_id
area.tag_redraw()
result=True
""")
    center_fixture(qa,host,True)
    snap(qa,prefix+'-result',target={'surface':'moodboard_node','area_type':host},margin=40)
    qa.eval(context(host)+"node.preview_image=None;node.state='DRAFT';area.tag_redraw();result=True")


def run(qa):
    OUT.mkdir(parents=True,exist_ok=True)
    require(qa.eval("result=__import__('os').environ.get('MIXAR_QA')=='1'"),'Use isolated QA')
    qa.cmd('wait_login',timeout=90)
    require(qa.eval(f'result=len({SCENE}.mixie_moodboard_action_nodes)')==0,'Use a fresh scene')
    if geometry(qa)['amount']<.98:
        toggle(qa,1)
    resize(qa,850)
    menu(qa);add(qa,LABELS[1],KINDS[1])
    path=png(OUT/'corner-reference.png',(170,80,55),320,180)
    media_id=drop(qa,path,target={'surface':'moodboard_drawer_panel'})
    scale=qa.eval('result=bpy.context.preferences.view.ui_scale')
    try:
        for host in ('VIEW_3D','MIXIE'):
            if host=='MIXIE':
                qa.eval("next(a for a in drv.main_window().screen.areas if a.type=='VIEW_3D').type='MIXIE';result=True")
            for ui_scale in (1.0,1.25):
                qa.eval(f'bpy.context.preferences.view.ui_scale={ui_scale};result=True')
                time.sleep(.3)
                qa.eval(f'n={SCENE}.mixie_moodboard_action_nodes[0];n.selected=True;'
                        f'{SCENE}.mixie_moodboard_active_node_id=n.node_id;result=True')
                prefix=f'{host}-{ui_scale}'
                qa.step(prefix+'-prompt',prompt_padding,qa,host,prefix)
                qa.step(prefix+'-media',media_corners,qa,host,media_id,prefix)
    finally:
        qa.eval(f'bpy.context.preferences.view.ui_scale={scale};result=True')
    return {'hosts':['VIEW_3D','MIXIE'],'ui_scales':[1,1.25],'backend_submissions':0}


if __name__=='__main__':
    run_scenario('moodboard_corner_padding_e2e',run)
