#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit references, title-free panes and grouped tabs in the real island.

Uses native Upload Reference/file selectors, moodboard selection, removal and
scrolling. Run with QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT on a fresh Dev
QA app. Catalog access is needed for Splat; no generation is submitted.
"""
import json
import os
from pathlib import Path
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from reference_drop_ux_e2e import SCENE, batch_drop, pause
from moodboard_drawer_e2e import select
from attachment_column_e2e import wheel
from island_tab_alignment_e2e import assert_tab_alignment

TABS = {
    'AGENT': 'Agent chat', 'THREE_D': '3D generation',
    'IMAGE': 'Image generation', 'VIDEO': 'Video generation', 'SPLAT': 'Gaussian Splat world generation',
    'GENERATIONS': 'Your generations and connected asset libraries',
    'QUEUE': 'Generation queue',
}
OWNERS = {'THREE_D': 'tab_image_to_3d', 'IMAGE': 'tab_imagegen', 'SPLAT': 'tab_world_labs'}
UPLOAD = {'THREE_D': 'MIXIE_OT_image_to_3d_pick_image',
          'IMAGE': 'MIXIE_OT_imagegen_upload_reference', 'SPLAT': 'MIXIE_OT_world_labs_pick_image'}
FIELD = {'area_type': 'AGENT_BUBBLE', 'prop': 'prompt'}


def tab(qa, key):
    qa.eval('result=str(bpy.ops.mixar.bubble_restore())')
    qa.click(area_type='AGENT_BUBBLE', text=TABS[key])
    qa.wait(f"bpy.context.window_manager.mixar_bubble_tab=={key!r}", timeout=5)
    pause(qa)


def capture(qa, out, name):
    pause(qa, .3)
    qa.eval("h=drv.find(area_type='AGENT_BUBBLE',text='Agent chat')[0]\n"
            "w=h['_win']\nwith bpy.context.temp_override(window=w):\n"
            f"    result=w.mixar_qa_capture_frame(filepath={str(out/(name+'.png'))!r})")


def upload(qa, op, path):
    qa.click(area_type='AGENT_BUBBLE', op=op)
    qa.wait("bool(drv.find(area_type='FILE_BROWSER',prop='directory'))", timeout=8)
    # Seed the file selector's location/name, then confirm its native action.
    # Typing a slash path drives Blender's live autocomplete and can select a
    # parent directory before the simulated keystroke batch has drained.
    qa.eval("h=drv.find(area_type='FILE_BROWSER',prop='directory')[0]\n"
            "p=h['_area'].spaces.active.params\n"
            f"p.directory={str(path.parent).encode()!r}\np.filename={path.name!r}\nresult=True")
    pause(qa)
    qa.click(area_type='FILE_BROWSER', op='FILE_OT_execute')
    qa.wait("not drv.find(area_type='FILE_BROWSER')", timeout=8)
    pause(qa)


def inspect(qa, out, name):
    qa.wait("bool(drv.find(surface='reference_preview'))", timeout=5)
    col = qa.find(surface='reference_column')['widgets'][0]
    field = qa.find(**FIELD)['widgets'][0]
    assert field['rect'][2] < col['rect'][0], (field, col)
    assert not qa.find(area_type='AGENT_BUBBLE', op='MIXIE_CHAT_OT_send_message')['total']
    generates = qa.find(area_type='AGENT_BUBBLE', op='MIXIE_OT_moodboard_prompt_generate')['widgets']
    assert len(generates) == 1 and generates[0]['enabled'], generates
    previews = qa.find(surface='reference_preview')['widgets']
    assert previews[0]['rect'][2] - previews[0]['rect'][0] > 120, previews
    capture(qa, out, name)
    return previews


def agent_baseline(qa, out, path):
    tab(qa, 'AGENT')
    field = {'area_type': 'AGENT_BUBBLE', 'prop': 'mixie_chat_input'}
    qa.cmd('set_text', widget=field, text='Keep the Agent draft', enter=False)
    upload(qa, 'MIXIE_CHAT_OT_add_image_from_file', path)
    qa.wait("bool(drv.find(surface='reference_column'))", timeout=5)
    col = qa.find(surface='reference_column')['widgets'][0]
    assert qa.find(**field)['widgets'][0]['rect'][2] < col['rect'][0]
    send = qa.find(area_type='AGENT_BUBBLE', op='MIXIE_CHAT_OT_send_message')['widgets']
    assert len(send) == 1 and send[0]['region_type'] == 'UI', send
    capture(qa, out, 'agent-reference-baseline')
    qa.click(area_type='AGENT_BUBBLE', op='MIXIE_CHAT_OT_remove_attachment')
    qa.wait("not drv.find(surface='reference_column')", timeout=5)
    assert qa.eval(f'result={SCENE}.mixie_chat_input') == 'Keep the Agent draft'


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/generation-reference-column')).resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa.wait("bpy.types.Operator.bl_rna_get_subclass_py('MIXAR_OT_pane_remove_reference') is not None",
            timeout=30)
    qa.wait("bpy.context.window_manager.mixie_chat_is_logged_in", timeout=45)
    qa.wait("bpy.types.Operator.bl_rna_get_subclass_py('MIXIE_OT_world_labs_pick_image') is not None", timeout=30)
    qa.eval("import os\nassert os.environ.get('MIXAR_QA')=='1'\n"
            f"assert not {SCENE}.mixie_moodboard_images, 'Use a fresh isolated app'\nresult=True")
    image = Image.new('RGB', (640, 400), (51, 93, 77))
    draw = ImageDraw.Draw(image)
    draw.ellipse((230, 90, 410, 270), fill=(225, 153, 80))
    draw.rectangle((270, 250, 370, 350), fill=(175, 206, 180))
    direct = out / 'direct-reference.png'
    image.save(direct)
    board_path = out / 'moodboard-reference.png'
    image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).save(board_path)
    tab(qa, 'THREE_D')

    qa.step('left_navigation_and_right_utility_tabs', assert_tab_alignment, qa)
    capture(qa, out, 'grouped-tabs-no-title')

    # Direct native uploads, including their source-switch side effects.
    for key in OWNERS:
        tab(qa, key)
        if key == 'SPLAT':
            qa.wait("bool(drv.find(area_type='AGENT_BUBBLE',op='MIXIE_OT_world_labs_pick_image'))",
                    timeout=20)
        draft = f'Use this {key.lower()} reference'
        qa.cmd('set_text', widget=FIELD, text=draft, enter=False)
        before = qa.eval("h=drv.find(area_type='AGENT_BUBBLE',text='Agent chat')[0]; result=[h['_win'].width,h['_win'].height]")
        qa.step(key.lower() + '_native_upload', upload, qa, UPLOAD[key], direct)
        assert qa.eval("h=drv.find(area_type='AGENT_BUBBLE',text='Agent chat')[0]; result=[h['_win'].width,h['_win'].height]") == before
        qa.step(key.lower() + '_right_preview', inspect, qa, out, key.lower() + '-direct')
        qa.click(area_type='AGENT_BUBBLE', op='MIXAR_OT_pane_remove_reference')
        qa.wait("not drv.find(surface='reference_column')", timeout=5)
        owner = OWNERS[key]
        assert qa.eval(f'result={SCENE}.mixie_moodboard_sidebar.{owner}.prompt') == draft
        capture(qa, out, key.lower() + '-removed')

    # Drop onto the real canvas and select its semantic media target.
    qa.step('drop_reference_on_moodboard', batch_drop, qa, [board_path])
    qa.wait('bpy.context.window_manager.mixar_moodboard_drawer_amount>.998', timeout=8)
    node_id = qa.eval(f'result=next(i.node_id for i in {SCENE}.mixie_moodboard_images '
                      f'if i.image and i.image.filepath=={str(board_path)!r})')
    for key, owner in OWNERS.items():
        prop = 'use_reference_images' if key == 'IMAGE' else 'use_selected_image'
        # Source selection is existing sidebar state; the feature under test
        # is a real canvas click feeding that input's native column.
        qa.eval(f'{SCENE}.mixie_moodboard_sidebar.{owner}.{prop}=True; result=True')
        qa.step(key.lower() + '_select_moodboard', select, qa, node_id)
        tab(qa, key)
        previews = qa.step(key.lower() + '_board_preview', inspect, qa, out, key.lower() + '-board')
        assert any(p['text'] == board_path.name for p in previews), previews
        qa.click(area_type='AGENT_BUBBLE', op='MIXAR_OT_pane_remove_reference')
        qa.wait(f'not any(i.selected for i in {SCENE}.mixie_moodboard_images)', timeout=5)
        qa.wait("not drv.find(surface='reference_column')", timeout=5)

    tab(qa, 'VIDEO')
    qa.step('video_native_upload', upload, qa, 'MIXAR_OT_pane_video_upload_reference', direct)
    qa.step('video_direct_preview', inspect, qa, out, 'video-direct')
    qa.click(area_type='AGENT_BUBBLE', op='MIXAR_OT_pane_remove_reference')
    qa.wait("not drv.find(surface='reference_column')", timeout=5)
    qa.step('video_select_moodboard', select, qa, node_id)
    tab(qa, 'VIDEO')
    qa.step('video_board_preview', inspect, qa, out, 'video-board')
    qa.click(area_type='AGENT_BUBBLE', op='MIXAR_OT_pane_remove_reference')
    qa.wait("not drv.find(surface='reference_column')", timeout=5)
    tab(qa, 'IMAGE')

    # Multi-reference scrolling uses Media's real uploaded collection. The
    # batch is fixture setup through the production uploader; scrolling is UI.
    tab(qa, 'IMAGE')
    more = []
    for i in range(7):
        path = out / f'additional-{i}.png'
        image.save(path)
        more.append({'name': path.name})
    qa.eval(f"h=drv.find(**{FIELD!r})[0]\nwith bpy.context.temp_override(window=h['_win']):\n"
            f"    bpy.ops.mixie.imagegen_upload_reference(directory={str(out)+'/'!r},files={more!r})\n"
            'result=True')
    qa.wait("bool(drv.find(surface='reference_column'))", timeout=5)
    qa.click(**FIELD)
    qa.step('media_reference_wheel_while_editing', wheel, qa, True, 12)
    assert qa.eval('result=bpy.context.window_manager.mixar_reference_scroll') > 0, 'Generation text editor swallowed the reference wheel'
    assert qa.eval(f'result={SCENE}.mixie_moodboard_sidebar.tab_imagegen.prompt') == 'Use this image reference'
    capture(qa, out, 'media-scrolled')
    # The scrollbar takes the first press even while the prompt owns focus.
    wheel(qa, False, 30)
    qa.click(**FIELD)
    scroll = qa.find(area_type='AGENT_BUBBLE', prop='mixar_reference_scroll')['widgets'][0]
    x0, y0, x1, y1 = scroll['rect']
    qa.cmd('drag', **{'from': {'window': scroll['window'], 'x': (x0+x1)//2, 'y': y1-5},
                     'to': {'window': scroll['window'], 'x': (x0+x1)//2, 'y': y0+5}})
    assert qa.eval('result=bpy.context.window_manager.mixar_reference_scroll') > .9
    capture(qa, out, 'media-last-reference')

    tab(qa, 'QUEUE')
    qa.wait("not drv.find(surface='reference_column')", timeout=5)
    tab(qa, 'IMAGE')
    qa.wait("bool(drv.find(surface='reference_column'))", timeout=5)
    qa.step('agent_reference_baseline', agent_baseline, qa, out, direct)
    verdict = {'native_upload_modes': [*OWNERS, 'VIDEO'],
               'moodboard_modes': [*OWNERS, 'VIDEO'],
               'right_column': True, 'removal_and_drafts': True, 'media_scroll': True,
               'centered_spaced_tabs': True, 'agent_baseline': True, 'paid_requests': 0}
    (out / 'verdict.json').write_text(json.dumps(verdict, indent=2) + '\n')
    return verdict


if __name__ == '__main__':
    run_scenario('generation_reference_column_e2e', run)
