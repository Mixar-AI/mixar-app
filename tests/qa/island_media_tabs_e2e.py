#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Image/Video header tabs, separate drafts/references, and no Settings shortcut.

Run with QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT on an isolated Dev app.
Reference datablocks are local fixtures; tab switches and draft edits use real
native controls. This works offline and never invokes Generate.
"""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from island_tab_alignment_e2e import AGENT, TABS, assert_tab_alignment

FIELD = {'area_type': 'AGENT_BUBBLE', 'prop': 'prompt'}
OWNERS = {'IMAGE': 'tab_imagegen', 'VIDEO': 'tab_video_gen'}


def select(qa, key):
    qa.click(area_type='AGENT_BUBBLE', text=TABS[key])
    qa.wait(f'bpy.context.window_manager.mixar_bubble_tab=={key!r}', timeout=5)
    time.sleep(.2)
    assert not qa.find(area_type='AGENT_BUBBLE', op='MIXAR_OT_pane_generation_settings')['total']
    # Header tooltips match these labels case-insensitively. Restrict the
    # supported region filter to the pane; the driver has no block filter.
    for label in ('Image Generation', 'Video Generation'):
        assert not qa.find(area_type='AGENT_BUBBLE', region_type='WINDOW', text=label)['total']
    assert_tab_alignment(qa)


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/island-media-tabs'))
    out.mkdir(parents=True, exist_ok=True)
    qa.eval('result=str(bpy.ops.mixar.agent_bubble_show_window())')
    qa.eval(f'h=drv.find_one(**{AGENT!r}); w=h["_win"]\n'
            'with bpy.context.temp_override(window=w):\n'
            '    bpy.ops.mixar.bubble_set_size(width=678,height=407)\n'
            'result=True')
    qa.eval("s=drv.main_window().scene; sidebar=s.mixie_moodboard_sidebar\n"
            "image=bpy.data.images.new('QA Image Reference',width=32,height=32)\n"
            "video=bpy.data.images.new('QA Video Reference',width=32,height=32)\n"
            "image.generated_color=(.1,.5,.8,1); video.generated_color=(.7,.2,.1,1)\n"
            "r=sidebar.tab_imagegen.reference_images.add(); r.image=image\n"
            "sidebar.tab_imagegen.use_reference_images=False\n"
            "r=s.mixie_moodboard_images.add(); r.image=video; r.selected=True\n"
            'result=True')
    try:
        for key, owner in OWNERS.items():
            qa.step(f'open-{key.lower()}', select, qa, key)
            qa.cmd('set_text', widget=FIELD, text=f'My {key.lower()} draft', enter=False)
            qa.wait(f'drv.main_window().scene.mixie_moodboard_sidebar.{owner}.prompt'
                    f'=={f"My {key.lower()} draft"!r}', timeout=5)
            previews = qa.find(surface='reference_preview')['widgets']
            assert len(previews) == 1 and f'QA {key.title()} Reference' in previews[0]['text'], previews
            upload = ('MIXIE_OT_imagegen_upload_reference' if key == 'IMAGE' else
                      'MIXAR_OT_pane_video_upload_reference')
            assert qa.find(area_type='AGENT_BUBBLE', op=upload)['total'] == 1
            generate = qa.find(area_type='AGENT_BUBBLE', op='MIXIE_OT_moodboard_prompt_generate')['widgets'][0]
            if key == 'VIDEO' and not generate['enabled']:
                # An unavailable catalog gets the strip to itself; a stale
                # model chip must not cover the explanation.
                assert not qa.find(area_type='AGENT_BUBBLE', region_type='WINDOW',
                                   op='WM_OT_context_menu_enum')['total']
            qa.cmd('snap', path=str(out / f'{key.lower()}.png'), target=AGENT, margin=2000)
        for key, owner in OWNERS.items():
            select(qa, key)
            assert qa.eval(f'result=drv.main_window().scene.mixie_moodboard_sidebar.{owner}.prompt') == f'My {key.lower()} draft'
        for key in ('THREE_D', 'SPLAT', 'AGENT', 'GENERATIONS', 'QUEUE'):
            qa.step(f'open-{key.lower()}', select, qa, key)
        return {'backend_calls': 0, 'tabs': list(TABS), 'screenshots': str(out)}
    finally:
        qa.eval("s=drv.main_window().scene; s.mixie_moodboard_sidebar.tab_imagegen.reference_images.clear()\n"
                "for i in reversed(range(len(s.mixie_moodboard_images))):\n"
                "    item=s.mixie_moodboard_images[i]\n"
                "    if item.image and item.image.name=='QA Video Reference':\n"
                "        s.mixie_moodboard_images.remove(i)\n"
                "for name in ('QA Image Reference','QA Video Reference'):\n"
                "    image=bpy.data.images.get(name)\n"
                "    if image: bpy.data.images.remove(image)\nresult=True")


if __name__ == '__main__':
    run_scenario('island_media_tabs_e2e', run)
