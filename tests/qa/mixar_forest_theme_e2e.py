#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit Mixar Forest replay in an isolated QA app.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4783 \
    QA_SCENARIO_OUT=/tmp/mixar-forest python3 tests/qa/mixar_forest_theme_e2e.py

Inspect the captured PNGs as well as the verdict. Never use a personal profile:
this scenario resets theme colors and changes workspace/editor presentation.
"""

import os
from pathlib import Path
import sys
import time

from PIL import Image

sys.path.insert(0, str(Path(os.environ["QA_HARNESS"]) / "scenarios"))
from lib import run_scenario

OUT = Path(os.environ.get("QA_SCENARIO_OUT", "/tmp/mixar-forest"))
THEME = "t=bpy.context.preferences.themes[0]; ui=t.user_interface\n"


def snap(qa, name, **kwargs):
    path = OUT / f"{name}.png"
    # Metal can return the previous presented frame after editor/layout changes.
    qa.cmd("snap", path=str(path), **kwargs)
    time.sleep(.5)
    qa.cmd("snap", path=str(path), **kwargs)
    return path


def state(qa):
    return qa.eval(THEME + """
def rgba(value):
    return ''.join(f'{round(v*255):02x}' for v in value)
result={p.identifier:rgba(getattr(ui,p.identifier))
        for p in ui.bl_rna.properties if p.identifier.startswith('mixar_')}
result['viewport']=rgba(t.view_3d.space.gradients.high_gradient)
result['moodboard']=rgba(t.mixie.space.back)
result['agent']=rgba(t.agent_bubble.agent_tab_active)
result['chat_user_bubble']=rgba(t.mixie_chat.chat_user_bubble)
""")


def defaults(qa):
    qa.wait("hasattr(bpy.types, 'MIXAR_OT_apply_forest_theme')", timeout=30)
    qa.eval("""
import os
assert os.environ.get('MIXAR_QA') == '1', 'Requires an isolated QA app'
from mixar.modules.onboarding.core.tour import session
if session.current():
    session.current().stop('theme-qa')
bpy.context.preferences.view.show_tooltips=False
for screen in bpy.data.screens:
    for area in screen.areas:
        for space in area.spaces:
            if space.type == 'VIEW_3D':
                space.shading.background_type='WORLD'
                space.shading.studiolight_background_alpha=1
bpy.ops.mixar.apply_forest_theme()
for screen in bpy.data.screens:
    for area in screen.areas:
        for space in area.spaces:
            if space.type == 'VIEW_3D':
                assert space.shading.background_type == 'THEME'
                assert space.shading.studiolight_background_alpha == 0
result=True
""")
    colors = state(qa)
    expected = {
        'viewport': '0f0f0f', 'moodboard': '1e1e1e', 'agent': '264515ff',
        'mixar_primary': '2f592fff', 'mixar_border': '3f4342ff',
        'mixar_border_strong': '6d6f6cff', 'mixar_toolbar_selected': '2f592fff',
        'mixar_gradient_start': '264515ff', 'mixar_gradient_end': '2f592fff',
        'mixar_glass_wash': '1e1e1e33',
    }
    for key, value in expected.items():
        assert colors[key] == value, (key, colors[key], value)
    assert len([k for k in colors if k.startswith('mixar_')]) == 85
    reset_colors = qa.eval(THEME + """
chat=t.mixie_chat
result={}
for field in ('chat_send_icon_gradient_start', 'chat_send_icon_gradient_end',
              'chat_send_arrow_color'):
    compiled=tuple(getattr(chat, field))
    reset=tuple(chat.bl_rna.properties[field].default_array)
    assert all(abs(a-b) < 1/255 for a,b in zip(compiled, reset)), field
    result[field]=''.join(f'{round(v*255):02x}' for v in reset)
""")
    return {'slots': 85, 'palette': expected, 'send_reset_defaults': reset_colors}


def workspaces(qa):
    names = qa.eval('result=[w.name for w in bpy.data.workspaces]')
    checked = []
    for name in names:
        qa.eval(f"drv.main_window().workspace=bpy.data.workspaces[{name!r}]; result=True")
        qa.wait(f"drv.main_window().workspace.name == {name!r}", timeout=10)
        time.sleep(.6)
        path = snap(qa, 'workspace-' + name.lower().replace(' ', '-'))
        if name == 'Zen Mode':
            with Image.open(path).convert('RGB') as image:
                # Exclude chrome: the old whole-window check could pass on the
                # toolbar even when the actual viewport was the wrong shade.
                image = image.crop((0, image.height // 5, image.width, image.height * 4 // 5))
                count = sum(n for n, c in image.getcolors(image.width * image.height)
                            if max(abs(v - 15) for v in c) <= 1)
                assert count > image.width * image.height * .4, 'Viewport charcoal not visible'
        assert state(qa)['mixar_primary'] == '2f592fff'
        checked.append(name)
    qa.eval("drv.main_window().workspace=bpy.data.workspaces['Zen Mode']; result=True")
    return checked


def moodboard(qa):
    qa.click(surface='moodboard_drawer_grip')
    qa.wait('bpy.context.window_manager.mixar_moodboard_drawer_amount > .99', timeout=10)
    path = snap(qa, 'moodboard-drawer')
    with Image.open(path).convert('RGB') as image:
        count = sum(n for n, c in image.getcolors(image.width * image.height)
                    if max(abs(v - 30) for v in c) <= 1)
        assert count > image.width * image.height * .05, 'Moodboard charcoal not visible'
    qa.click(surface='moodboard_drawer_grip')
    qa.wait('bpy.context.window_manager.mixar_moodboard_drawer_amount < .01', timeout=10)
    qa.eval("a=next(a for a in drv.main_window().screen.areas if a.type=='VIEW_3D'); "
            "a.type='MIXIE'; result=True")
    time.sleep(.5)
    snap(qa, 'moodboard-editor')
    # Prove the editor background control changes pixels, rather than only RNA.
    qa.eval(THEME + "t.mixie.space.back=(.18,.23,.18); result=True")
    time.sleep(.3)
    path = snap(qa, 'moodboard-custom-background')
    with Image.open(path).convert('RGB') as image:
        edited = sum(n for n, c in image.getcolors(image.width * image.height)
                     if all(abs(a-b) <= 1 for a,b in zip(c,(46,59,46))))
        assert edited > image.width * image.height * .05, 'Custom background not rendered'
    qa.eval(THEME + "t.mixie.space.back=(30/255,)*3; "
            "next(a for a in drv.main_window().screen.areas if a.type=='MIXIE').type='VIEW_3D'; "
            "result=True")
    return {'drawer_charcoal_pixels': count, 'editor_color_edit': True}


def viewport_framebuffer(qa):
    """Check presented RGB before the screenshot writer can quantize it."""
    results = {}
    for mode in ('SOLID', 'MATERIAL'):
        qa.eval(f"""
import gpu
from collections import Counter
a=next(a for a in drv.main_window().screen.areas if a.type=='VIEW_3D')
a.spaces.active.shading.type={mode!r}
ns=bpy.app.driver_namespace
ns.pop('_forest_framebuffer', None)
def probe():
    if bpy.context.area != a:
        return
    rows=gpu.state.active_framebuffer_get().read_color(40,200,128,128,4,0,'UBYTE').to_list()
    counts=Counter(tuple(pixel[:3]) for row in rows for pixel in row)
    ns['_forest_framebuffer']=counts.most_common(1)[0]
ns['_forest_probe']=bpy.types.SpaceView3D.draw_handler_add(probe,(),'WINDOW','POST_PIXEL')
a.tag_redraw()
result=True
""")
        try:
            qa.wait("'_forest_framebuffer' in bpy.app.driver_namespace", timeout=15)
            # Allow Material Preview shader compilation and redraw to settle.
            time.sleep(1)
            color, count = qa.eval("result=bpy.app.driver_namespace['_forest_framebuffer']")
            assert color == [15, 15, 15] and count > 8192, (mode, color, count)
            results[mode] = color
        finally:
            qa.eval("bpy.types.SpaceView3D.draw_handler_remove("
                    "bpy.app.driver_namespace.pop('_forest_probe'),'WINDOW'); result=True")
    qa.eval("next(a for a in drv.main_window().screen.areas if a.type=='VIEW_3D')"
            ".spaces.active.shading.type='SOLID'; result=True")
    return results


def header_backgrounds(qa):
    """The mode bar and Cinema toolbar share the same opaque background."""
    results = {}
    for space, area_type in [('SpaceTopBar', 'TOPBAR'), ('SpaceView3D', 'VIEW_3D')]:
        qa.eval(f"""
import gpu
from collections import Counter
ns=bpy.app.driver_namespace
ns.pop('_forest_header',None)
def probe():
    r=bpy.context.region
    if bpy.context.area.type!={area_type!r} or r.type!='HEADER':
        return
    rows=gpu.state.active_framebuffer_get().read_color(0,0,r.width,r.height,4,0,'UBYTE').to_list()
    ns['_forest_header']=Counter(tuple(p[:3]) for row in rows for p in row).most_common(1)[0]
ns['_forest_header_probe']=bpy.types.{space}.draw_handler_add(probe,(),'HEADER','POST_PIXEL')
for a in drv.main_window().screen.areas: a.tag_redraw()
result=True
""")
        try:
            qa.wait("'_forest_header' in bpy.app.driver_namespace",timeout=10)
            color,count=qa.eval("result=bpy.app.driver_namespace['_forest_header']")
            assert color==[30,30,30] and count>1000, (area_type,color,count)
            results[area_type]=color
        finally:
            qa.eval(f"bpy.types.{space}.draw_handler_remove(bpy.app.driver_namespace.pop('_forest_header_probe'),'HEADER'); result=True")
    snap(qa,'matching-zen-bars')
    return results


def preferences(qa):
    qa.eval("bpy.context.preferences.active_section='THEMES'; "
            "bpy.ops.screen.userpref_show('INVOKE_DEFAULT'); result=True")
    qa.wait("bool(drv.find(op='MIXAR_OT_apply_forest_theme'))", timeout=15)
    query = {'area_type': 'PREFERENCES'}
    snap(qa, 'preferences', target={'op': 'MIXAR_OT_apply_forest_theme'}, margin=2000)
    for field in ('high_gradient', 'back'):
        assert qa.find(prop=field, **query)['widgets'], field
    qa.eval(THEME + "t.view_3d.space.gradients.high_gradient=(0,0,0); "
            "t.mixie.space.back=(0,0,0); result=True")
    qa.click(op='MIXAR_OT_apply_forest_backgrounds', **query)
    assert state(qa)['viewport'] == '0f0f0f'
    assert state(qa)['moodboard'] == '1e1e1e'
    for title, field in [('Selection & Feedback', 'mixar_primary'),
                         ('Actions & Generation', 'mixar_gradient_start'),
                         ('Toolbar & Account', 'mixar_toolbar_selected')]:
        qa.click(**query, text=title)
        qa.wait(f"bool(drv.find(prop={field!r}, area_type='PREFERENCES'))", timeout=5)
        snap(qa, 'preferences-' + field, target={'prop': field, 'area_type': 'PREFERENCES'}, margin=2000, annotate={'prop': field})
        qa.click(**query, prop=field)
        assert qa.find(popup=True)['widgets'], f'{field} color picker did not open'
        qa.press('ESC', window=qa.find(**query, prop=field)['widgets'][0]['window'])
        qa.click(**query, text=title)
    # Persist edits through Blender's actual theme serializer/importer.
    path = str(OUT / 'roundtrip.xml')
    qa.eval(THEME + f"""
import _rna_xml
from bl_ui.space_userpref import USERPREF_MT_interface_theme_presets as preset
ui.mixar_primary=(.2,.4,.25,1)
ui.mixar_gradient_start=(.1,.2,.1,1)
t.agent_bubble.agent_tab_active=(.2,.4,.25,1)
t.mixie_chat.chat_user_bubble=(.2,.4,.25,1)
t.mixie.space.back=(.2,.4,.25)
_rna_xml.xml_file_write(bpy.context, {path!r}, preset.preset_xml_map)
bpy.ops.mixar.apply_forest_theme()
_rna_xml.xml_file_run(bpy.context, {path!r}, preset.preset_xml_map,
                     secure_types=preset.preset_xml_secure_types)
result=True
""")
    colors = state(qa)
    assert colors['mixar_primary'] == '336640ff', colors['mixar_primary']
    assert colors['mixar_gradient_start'] == '1a331aff', colors['mixar_gradient_start']
    assert colors['agent'] == '336640ff', colors['agent']
    assert colors['chat_user_bubble'] == '336640ff', colors['chat_user_bubble']
    assert colors['moodboard'] == '336640', colors['moodboard']
    qa.eval("bpy.ops.mixar.apply_forest_theme(); result=True")
    snap(qa, 'preferences-restored', target={'op': 'MIXAR_OT_apply_forest_theme'}, margin=2000)
    qa.eval("""
for w in list(bpy.context.window_manager.windows):
    if any(a.type=='PREFERENCES' for a in w.screen.areas):
        with bpy.context.temp_override(window=w):
            bpy.ops.wm.window_close()
result=True
""")
    return {'color_pickers': 3, 'export_import_roundtrip': True}


def island(qa):
    qa.eval("bpy.context.window_manager.mixar_bubble_tab='AGENT'; "
            "bpy.ops.mixar.agent_bubble_show_window(); bpy.ops.mixar.bubble_restore(); result=True")
    qa.wait("bool(drv.find(prop='mixie_chat_input', area_type='AGENT_BUBBLE'))", timeout=10)
    time.sleep(.4)
    snap(qa, 'agent-island', target={'prop': 'mixie_chat_input', 'area_type': 'AGENT_BUBBLE'},
         margin=1500)
    qa.click(area_type='AGENT_BUBBLE', text='3D generation')
    qa.wait("bpy.context.window_manager.mixar_bubble_tab == 'THREE_D'", timeout=10)
    time.sleep(.3)
    snap(qa, 'generation-island', target={'text': '3D generation', 'area_type': 'AGENT_BUBBLE'},
         margin=1500)
    qa.eval("bpy.ops.mixar.bubble_minimise(); result=True")
    return {'agent_and_generation_visible': True, 'paid_requests': 0}


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    checks = {}
    for name, check in [('defaults', defaults), ('workspaces', workspaces),
                        ('viewport_framebuffer', viewport_framebuffer),
                        ('header_backgrounds', header_backgrounds),
                        ('moodboard', moodboard), ('preferences', preferences), ('island', island)]:
        checks[name] = qa.step(name, check, qa)
    snap(qa, 'final-zen')
    return {'checks': checks}


if __name__ == '__main__':
    run_scenario('mixar_forest_theme', run)
