#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline notification glass, wrapping, native font parity and input replay.

Run on an isolated macOS Dev app with QA_HARNESS, MIXAR_QA_PORT and
QA_SCENARIO_OUT. Resizes only the QA process's window; no backend requests.
Screenshots and result files must remain local.
"""
import math
import os
from pathlib import Path
import sys
from PIL import Image

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario, ensure_tab
from zen_bubble_text_size_e2e import capture_label, QUEUE
from compact_agent_bubble_e2e import _hover_off, _hover_on
from zen_ui_fixes_e2e import native

TOAST = {'surface': 'toast'}
IMPORTS = ('from mixar.modules.common.notifications import toast_renderer as tr\n'
           'from mixar.modules.common.notifications.store import get_notification_store, NotificationAction\n'
           'store=get_notification_store()\n')


def settle(qa):
    qa.eval('def settle():\n    yield .3\n    return True\nresult=settle()')


def push(qa, title, body, *, actions=False, url=None, ttl=0):
    qa.eval(IMPORTS + 'store.reset()\n' +
            f'actions=[NotificationAction("Review generation options", "wm.qa_toast_review"), '
            'NotificationAction("Continue with selected settings", "wm.qa_toast_continue", "primary")]\n' +
            f'store.push("warning", {title!r}, {body!r}, id="qa-toast", ttl_ms={ttl}, '
            f'actions=actions if {actions!r} else [], action_url={url!r})\nresult=True')
    # Reusing an id must not accept the previous card's cached paint geometry.
    qa.wait(f'bool(drv.find(surface="toast", text={title!r}))', timeout=8)
    settle(qa)


def capture_text(qa, out, name, query, dark=False):
    if not dark:
        return capture_label(qa, out, name, query)
    path=out/(name+'.png')
    qa.cmd('snap',path=str(path),target=query,margin=0)
    with Image.open(path) as image:
        rgb=image.convert('RGB')
        mask=Image.new('L',rgb.size)
        pixels=rgb.get_flattened_data() if hasattr(rgb,'get_flattened_data') else rgb.getdata()
        # Dark ink on brand green: 140 is approximately the same linear-light
        # coverage as the white-label helper's 175 cutoff (sRGB is nonlinear).
        mask.putdata([255 if max(pixel)<140 else 0 for pixel in pixels])
        box=mask.getbbox()
    assert box is not None,path
    return [box[2]-box[0],box[3]-box[1]]


def ink_area(path, dark=False):
    with Image.open(path) as image:
        rgb=image.convert('RGB')
        pixels=rgb.get_flattened_data() if hasattr(rgb,'get_flattened_data') else rgb.getdata()
        return sum(max(pixel)<140 if dark else min(pixel)>=175 for pixel in pixels)


def snapshot(qa, out, name):
    qa.cmd('snap', path=str(out / (name+'.png')), target=TOAST, margin=30)


def assert_bright_contrast(qa, out):
    title=qa.find(surface='toast_title_text')['widgets'][0]['text']
    path=out/'bright-text.png'
    qa.cmd('snap',path=str(path),target={'surface':'toast_title_text','text':title},margin=0)
    def linear(value):
        value/=255
        return value/12.92 if value<=.04045 else ((value+.055)/1.055)**2.4
    with Image.open(path) as image:
        rgb=image.convert('RGB')
        pixels=rgb.get_flattened_data() if hasattr(rgb,'get_flattened_data') else rgb.getdata()
        luminance=sorted(sum(linear(c)*weight for c,weight in zip(pixel,(.2126,.7152,.0722)))
                         for pixel in pixels)
    # Most of a text target is its background; solid glyph ink supplies the peak.
    contrast=(luminance[-1]+.05)/(luminance[len(luminance)//2]+.05)
    assert contrast>=4.5,contrast
    return contrast


def assert_layout(qa):
    return qa.eval(IMPORTS + '''import blf
h=drv.find_one(surface='toast')
r=next(r for r in h['_area'].regions if r.type=='WINDOW')
card=tr.toast_layouts_by_region[r.as_pointer()][0]
x,y,w,height=card['rect']
assert 0 <= x < x+w <= r.width and 0 <= y < y+height <= r.height, card['rect']
layout=card['layout']
from mixar.modules.common.notifications.core.typography import emphasis_font_id
bold_font=emphasis_font_id()
assert bold_font>0, 'Bundled bold font did not load'
for block in layout['blocks']:
    assert block['font_id']==(bold_font if block['kind']=='title' else 0)
    blf.size(block['font_id'],layout['font_size'])
    assert all(blf.dimensions(block['font_id'],line)[0] <= layout['content_width']+.01 for line in block['lines'])
for button in layout['buttons']:
    assert button['font_id']==bold_font
    blf.size(button['font_id'],layout['font_size'])
    assert button['x'] >= 0 and button['x']+button['width'] <= layout['content_width']+.01
    assert all(blf.dimensions(button['font_id'],line)[0] <= button['width'] for line in button['lines'])
assert layout['font_size']==bpy.context.preferences.ui_styles[0].widget.points*bpy.context.preferences.system.ui_scale
assert all(sample['font_size']==layout['font_size'] for sample in card['samples'])
for target in drv.find(surface='toast_close')+drv.find(surface='toast_action'):
    a,b,c,d=target['rect']
    assert r.x+x <= a < c <= r.x+x+w+1 and r.y+y <= b < d <= r.y+y+height+1
result={'width':w,'height':height,'font_size':layout['font_size'],
        'max_scroll':card['max_scroll'],'scroll':card['scroll'],
        'title_lines':len(layout['blocks'][0]['lines']),
        'action_rows':len({b['top'] for b in layout['buttons']})}
''')


def scroll(qa, *, pan=0, count=1):
    qa.eval('def events():\n'
            '    h=drv.find_one(surface="toast"); w=h["_win"]; x,y=h["center"]\n'
            '    w.cursor_warp(x,y)\n'
            f'    for _ in range({count}):\n' +
            (f'        drv._sim(w,type="MOUSEMOVE",value="NOTHING",x=x,y=y-{pan})\n'
             '        yield .04\n' if pan else '') +
            f'        drv._sim(w,type={"TRACKPADPAN" if pan else "WHEELDOWNMOUSE"!r}, '
            f'value={"NOTHING" if pan else "PRESS"!r},x=x,y=y)\n'
            '        yield .04\n    return True\nresult=events()')
    settle(qa)


def agent_font_reference(qa, out, name):
    # The island is the requested reference. An N-panel can be independently
    # zoomed, so its font raster is not a reliable reference for overlay text.
    native(qa,'host',size=(1100,700))
    qa.eval('bpy.context.window_manager.mixar_bubble_tab="AGENT"; '
            'bpy.ops.mixar.agent_bubble_show_window(); result=True')
    qa.wait(f'bool(drv.find(**{QUEUE!r}))',timeout=8)
    settle(qa)
    expected=capture_label(qa,out,name+'-agent-queue',QUEUE)
    qa.eval('bpy.ops.mixar.agent_bubble_purge_windows(); result=True')
    return expected


def run(qa):
    out=Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/notification-glass'))
    out.mkdir(parents=True, exist_ok=True)
    qa.wait("'mixar_draw_glass' in bpy.types.Region.bl_rna.functions", timeout=30)
    qa.eval(f'import sys; sys.path.insert(0, {str(Path(__file__).parent)!r}); '
            'import toast_font_fixture as f; f.install(); result=True')
    saved=qa.eval(IMPORTS + '''w=drv.main_window()
a=next(a for a in w.screen.areas if a.type=='VIEW_3D')
drv._toast_qa_area=a
result=[bpy.context.preferences.view.ui_scale, bpy.context.preferences.ui_styles[0].widget.points,
        a.spaces.active.show_region_ui, bpy.context.preferences.view.show_tooltips,
        a.spaces.active.shading.background_type, list(a.spaces.active.shading.background_color)]
bpy.context.preferences.view.show_tooltips=False
a.spaces.active.show_region_ui=True
bpy.ops.mixar.agent_bubble_purge_windows()
''')
    host=native(qa,'host')
    metrics={}
    try:
        _hover_off(qa)
        ensure_tab(qa,'Toast QA')
        for scale in (1.0,1.25):
            for points in (12,15):
                qa.eval(f'bpy.context.preferences.view.ui_scale={scale}; '
                        f'bpy.context.preferences.ui_styles[0].widget.points={points}; result=True')
                expected=agent_font_reference(qa,out,f'font-{scale}-{points}')
                samples=[]
                font_sizes=[]
                for width in (1100,560):
                    native(qa,'host',size=(width,700))
                    qa.eval(IMPORTS + 'store.reset(); store.push("info", "Queue", "Queue", id="qa-font", '
                            'actions=[NotificationAction("Queue", "wm.qa_toast_review", "primary")]); result=True')
                    qa.wait('bool(drv.find(surface="toast"))',timeout=8)
                    settle(qa)
                    name=f'font-{scale}-{points}-{width}'
                    state=assert_layout(qa)
                    font_sizes.append(state['font_size'])
                    ink={}
                    for kind in ('title','body','action'):
                        label='Queue'
                        # A narrow card may wrap even one action word. Check
                        # its layout and fixed font; compare regular body to Agent.
                        surface='toast_'+kind+'_text'
                        fragments=qa.find(surface=surface)['widgets']
                        assert fragments,(kind,state)
                        ink[kind]=[]
                        for i,fragment in enumerate(fragments):
                            text=fragment['text']
                            actual=capture_text(qa,out,f'{name}-{kind}-{i}',{'surface':surface,'text':text},dark=kind=='action')
                            if text==label and kind=='body':
                                reference=expected
                                assert all(abs(a-b)<=1 for a,b in zip(actual,reference)),(name,text,actual,reference)
                            ink[kind].append(actual)
                    if width==1100:
                        body_ink=ink_area(out/f'{name}-body-0.png')
                        for kind in ('title','action'):
                            bold_ink=ink_area(out/f'{name}-{kind}-0.png',dark=kind=='action')
                            assert bold_ink>body_ink*1.2,(name,kind,bold_ink,body_ink)
                    samples.append(ink)
                    snapshot(qa,out,name)
                    metrics[name]=state
                assert font_sizes[0]==font_sizes[1],font_sizes
                qa.step(f'native-size-and-bold-emphasis-{scale}-{points}',lambda: samples)

        qa.eval('bpy.context.preferences.view.ui_scale=1.0; '
                'bpy.context.preferences.ui_styles[0].widget.points=12; result=True')
        native(qa,'host',size=(760,700))
        push(qa,'Your generation needs attention before it can continue',
             'A long notification stays readable beside the sidebar.\n\n'
             'averylongidentifierthatcannotbewrappedonspaces '*3,actions=True,
             url='https://example.invalid/'+'generation-reference/'*8)
        state=qa.step('long-title-url-and-action-wrapping',assert_layout,qa)
        assert state['title_lines']>1 and state['action_rows']>1,state
        snapshot(qa,out,'wrapped')
        qa.eval('a=drv._toast_qa_area; a.spaces.active.shading.background_type="VIEWPORT"; '
                'a.spaces.active.shading.background_color=(1,1,1); result=True')
        settle(qa)
        snapshot(qa,out,'bright-background')
        qa.step('readable-over-white-viewport',assert_bright_contrast,qa,out)
        push(qa,'Scrollable notification', '\n'.join(f'Line {i}: every detail remains accessible.' for i in range(80)),actions=True)
        before=assert_layout(qa)
        assert before['max_scroll']>0,before
        scroll(qa,pan=-10)
        state=assert_layout(qa)
        assert state['scroll']>0,state
        scroll(qa,pan=10)
        state=assert_layout(qa)
        assert state['scroll']==0,state
        snapshot(qa,out,'scroll-top')
        ui_scale=qa.eval('result=bpy.context.preferences.system.ui_scale')
        scroll(qa,count=math.ceil(before['max_scroll']/(40*ui_scale))+1)
        after=qa.step('scroll-long-content-to-actions',assert_layout,qa)
        assert abs(after['scroll']-after['max_scroll'])<1,after
        snapshot(qa,out,'scroll-bottom')
        qa.click(surface='toast_action',text='Continue with selected settings')
        qa.wait('__import__("toast_font_fixture").calls["continue"]==1',timeout=5)
        qa.click(surface='toast_close',text='Dismiss notification')
        qa.wait('not drv.find(surface="toast")',timeout=5)
        qa.step('actions-and-fixed-dismiss-control-work',lambda: True)
        push(qa,'Finished','A readable notification fades away.',ttl=1200)
        snapshot(qa,out,'fade-start')
        qa.wait('not __import__("mixar.modules.common.notifications.store",fromlist=["get_notification_store"]).get_notification_store().get_visible()',timeout=5)
        qa.wait('not drv.find(surface="toast")',timeout=5)
        qa.step('expiry-clears-paint-and-click-targets',lambda: True)
        return {'font_layouts':metrics,'backend_calls':0,'screenshots':str(out)}
    finally:
        qa.eval(IMPORTS + 'store.reset(); import toast_font_fixture as f; f.uninstall(); '
                f'bpy.context.preferences.view.ui_scale={saved[0]}; '
                f'bpy.context.preferences.ui_styles[0].widget.points={saved[1]}; '
                f'drv._toast_qa_area.spaces.active.show_region_ui={saved[2]}; '
                f'bpy.context.preferences.view.show_tooltips={saved[3]}; '
                f'drv._toast_qa_area.spaces.active.shading.background_type={saved[4]!r}; '
                f'drv._toast_qa_area.spaces.active.shading.background_color={saved[5]!r}; '
                'bpy.ops.mixar.agent_bubble_purge_windows(); result=True')
        native(qa,'host',size=host[2:])
        _hover_on(qa)


if __name__=='__main__':
    run_scenario('notification_glass_e2e',run)
