#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit Cinema/menu/checkbox replay. Requires an isolated QA app.

Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT. Inspect the captured PNGs.
"""
import os
from pathlib import Path
import sys
import time

from PIL import Image

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/chrome-theme-polish'))


def snap(qa, name, query):
    path = OUT / f'{name}.png'
    # Metal may expose the previously presented frame after layout changes.
    for _ in range(2):
        qa.cmd('snap', path=str(path), target=query, margin=0)
        time.sleep(.3)
    return path


def hover(qa, query):
    qa.eval(f"w=drv.find_one(**{query!r}); drv.move_to(drv.main_window(),*w['center']); result=True")
    time.sleep(.4)


def cinema(qa):
    for mode, op in [('Zen', 'ai'), ('Engine', 'pro')]:
        qa.click(op=f'MIXAR_OT_set_ui_mode_{op}')
        qa.wait("bool(drv.find(text='Cinema Mode'))", timeout=10)
        time.sleep(.5)
        path = snap(qa, f'cinema-{mode}', {'text':'Cinema Mode'})
        with Image.open(path).convert('RGB') as image:
            green = sum(n for n,c in image.getcolors(image.width*image.height)
                        if c[1] > c[0]+5 and c[1] > c[2]+5)
            assert green > image.width*image.height*.15, 'Cinema lost its green'
        assert qa.eval("result=drv.main_window().workspace.name=='Zen Mode'") == (mode=='Zen')
    return {'modes':['Zen','Engine']}


def workspace_pills(qa):
    qa.click(op='MIXAR_OT_set_ui_mode_pro')
    qa.wait("len(drv.find(area_type='TOPBAR',but_type='Tab'))>=2",timeout=10)
    tabs=qa.find(area_type='TOPBAR',but_type='Tab')['widgets']
    tabs=sorted(tabs,key=lambda w:w['rect'][0])
    expected={'Layout','Modelling','UV Editing','Texturing'}
    assert expected <= {w['text'] for w in tabs}, tabs
    assert all(a['rect'][2] <= b['rect'][0] for a,b in zip(tabs,tabs[1:])), tabs
    widths={w['text']:w['rect'][2]-w['rect'][0] for w in tabs}
    for tab in tabs[:2]:
        query={'area_type':'TOPBAR','but_type':'Tab','text':tab['text']}
        qa.click(**query)
        qa.wait(f"drv.main_window().workspace.name=={tab['text']!r}",timeout=10)
        hover(qa,query)
        snap(qa,'workspace-'+tab['text'],query)
    return {'visible_widths':widths,'switches_verified':2}


def menus(qa):
    qa.click(text='File', area_type='TOPBAR')
    query = {'op':'WM_OT_open_mainfile','popup':True}
    hover(qa, query)
    path = snap(qa, 'menu-full-row', query)
    with Image.open(path).convert('RGB') as image:
        # The blank left edge should carry the highlight even near the corners.
        colors = [image.getpixel((4,y)) for y in (4,image.height//2,image.height-5)]
        assert max(colors[1]) > 40, colors
        assert all(max(abs(a-b) for a,b in zip(c,colors[1])) <= 2 for c in colors), colors
    qa.press('ESC')
    # Exercise the same custom option adapter used by Director/model dropdowns.
    qa.eval("""
class QA_MT_theme_options(bpy.types.Menu):
    bl_label='Theme QA Options'
    def draw(self, context):
        for value, label in ((True,'Transparent'),(False,'Opaque')):
            op=self.layout.operator('wm.context_set_boolean',text=label)
            op.data_path='scene.render.film_transparent'
            op.value=value
            self.layout.mixar_cinema_row(kind='ACTIVE' if context.scene.render.film_transparent==value else 'OPTION')
bpy.utils.register_class(QA_MT_theme_options)
w=drv.main_window()
a=next(a for a in w.screen.areas if a.type=='VIEW_3D')
r=next(r for r in a.regions if r.type=='WINDOW')
with bpy.context.temp_override(window=w,area=a,region=r):
    bpy.ops.wm.call_menu(name='QA_MT_theme_options')
result=True
""")
    hover(qa, {'text':'Transparent','popup':True})
    snap(qa, 'custom-option-row', {'text':'Transparent','popup':True})
    qa.click(text='Transparent', popup=True)
    qa.wait('drv.main_window().scene.render.film_transparent',timeout=5)
    qa.eval("bpy.utils.unregister_class(bpy.types.QA_MT_theme_options); drv.main_window().scene.render.film_transparent=False; result=True")
    return {'native_row':'square, full width','custom_option':'click verified'}


def checkboxes(qa):
    qa.eval("""
a=next(a for a in drv.main_window().screen.areas if a.type=='VIEW_3D')
a.type='PREFERENCES'
bpy.context.preferences.active_section='INTERFACE'
# Exercise compatibility with the old fully rounded theme preference too.
bpy.context.preferences.themes[0].user_interface.wcol_option.roundness=1
result=True
""")
    query = {'prop':'show_tooltips','area_type':'PREFERENCES'}
    qa.wait("bool(drv.find(prop='show_tooltips',area_type='PREFERENCES'))",timeout=10)
    for enabled in (False,True):
        current = qa.eval('result=bpy.context.preferences.view.show_tooltips')
        if current != enabled:
            qa.click(**query)
        assert qa.eval('result=bpy.context.preferences.view.show_tooltips') == enabled
        hover(qa, query)
        snap(qa, f'checkbox-{enabled}', query)
    qa.eval("bpy.context.preferences.view.show_tooltips=False; bpy.context.preferences.themes[0].user_interface.wcol_option.roundness=.15; next(a for a in drv.main_window().screen.areas if a.type=='PREFERENCES').type='VIEW_3D'; result=True")
    return {'checked':True,'unchecked':True,'legacy_roundness':1}


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.wait("hasattr(bpy.types, 'MIXAR_OT_apply_forest_theme')", timeout=30)
    qa.eval("""
import os
assert os.environ.get('MIXAR_QA')=='1'
from mixar.modules.onboarding.core.tour import session
if session.current(): session.current().stop('chrome-theme-qa')
bpy.context.preferences.view.show_tooltips=False
bpy.ops.mixar.apply_forest_theme()
result=True
""")
    return {name:qa.step(name,fn,qa) for name,fn in
            [('cinema',cinema),('workspace_pills',workspace_pills),
             ('menus',menus),('checkboxes',checkboxes)]}


if __name__=='__main__':
    run_scenario('chrome_theme_polish',run)
