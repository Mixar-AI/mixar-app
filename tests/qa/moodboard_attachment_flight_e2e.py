#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""No-credit moodboard selection -> native minimize ribbon -> chat reference.

Requires a fresh isolated Dev QA app. Saves actual frames plus motion samples.
QA_HARNESS=/path/to/harness QA_SCENARIO_OUT=/tmp/attachment-flight python3 tests/qa/moodboard_attachment_flight_e2e.py
"""
import inspect
import json
import os
from pathlib import Path
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from compact_agent_bubble_e2e import _hover_off, _hover_on
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reference_drop_ux_e2e import SCENE, batch_drop, board, attachments, pause
from zen_motion_capture import preview


def capture_selection(node_id, directory, expected=True, remove=False, minimized=False, scripted=False):
    import time
    import bpy
    import qa_driver as drv

    win = drv.main_window()
    hit = drv.find_one(surface='moodboard_media', text=node_id)
    if scripted:
        # Backend/script selection uses the same sync while preserving the open island.
        next(i for i in win.scene.mixie_moodboard_images if i.node_id == node_id).selected = True
    else:
        yield from drv.click_steps(hit)
    started = time.monotonic()
    frames = []
    removed = False
    while time.monotonic() - started < 1.2:
        matches = drv.find(surface='moodboard_attachment_flight')
        path = directory + '/frame-%03d.png' % len(frames)
        with bpy.context.temp_override(window=win):
            assert win.mixar_qa_capture_frame(filepath=path)
        # During native collapse no pill is painted until it reaches its seat.
        targets = drv.find(surface='pill_cat') if minimized else drv.find(
            area_type='AGENT_BUBBLE', prop='mixie_chat_input')
        target_path = None
        destination_bounds = None
        if targets:
            destination = targets[0]['_win']
            target_path = directory + '/target-%03d.png' % len(frames)
            with bpy.context.temp_override(window=destination):
                assert destination.mixar_qa_capture_frame(filepath=target_path)
            destination_bounds = [destination.x, destination.y, destination.width, destination.height]
        frames.append({'time': time.monotonic()-started, 'path': path,
                       'target_path': target_path,
                       'cat': {'activity': targets[0]['value'], 'rect': targets[0]['rect']}
                              if minimized and targets else None,
                       'main': [win.x, win.y, win.width, win.height],
                       'destination': destination_bounds,
                       'flights': [{'rect': t['rect'], 'progress': float(t['value']),
                                    'image': t['text']} for t in matches]})
        if remove and matches and not removed:
            # Cancel through the same X-button operator as the live reference.
            with bpy.context.temp_override(window=win):
                bpy.ops.mixie_chat.remove_attachment(index=0)
            removed = True
        yield .025
    assert not drv.find(surface='moodboard_attachment_flight'), 'Flight did not retire'
    return frames


def clear_selection(qa):
    qa.eval(f"scene={SCENE}\n"
            "for item in scene.mixie_moodboard_images: item.selected=False\n"
            "for node in scene.mixie_moodboard_action_nodes: node.selected=False\n"
            "for group in scene.mixie_moodboard_groups: group.selected=False\n"
            "if scene.mixie_chat_pending_attachments: bpy.ops.mixie_chat.clear_attachments()\n"
            "from mixar.modules.moodboard.core.chat_sync import force_resync\n"
            "force_resync(scene)\nresult=True")
    qa.wait(f'not {SCENE}.mixie_chat_pending_attachments', timeout=5)
    pause(qa, .3)


def record(qa, node, out, *, expected=True, remove=False, minimized=False, scripted=False):
    out.mkdir(parents=True, exist_ok=True)
    samples = qa.eval(inspect.getsource(capture_selection) +
                      f'\nresult=capture_selection({node!r},{str(out)!r},{expected!r},{remove!r},{minimized!r},{scripted!r})')
    (out/'samples.json').write_text(json.dumps(samples, indent=2)+'\n')
    values = [f for s in samples for f in s['flights']]
    if expected:
        assert len(values) >= (1 if remove else 3), 'No intermediate native flight poses'
        if not remove:
            assert max(v['progress'] for v in values) - min(v['progress'] for v in values) > .3
            assert len({tuple(v['rect']) for v in values}) >= 3
    else:
        assert not values, 'Unchanged selection replayed the animation'
    # Keep preview sizes reviewable while retaining full-resolution source frames.
    rendered = []
    for i, sample in enumerate(samples):
        frame = Image.open(sample['path']).convert('RGB')
        # Composite the actual cached window pixels at their real OS positions.
        # Floating windows are separate swap chains and absent from a main-window capture.
        if sample['target_path']:
            target = Image.open(sample['target_path']).convert('RGBA')
            mx, my, mw, mh = sample['main']
            tx, ty, tw, th = sample['destination']
            scale = frame.width / mw
            target = target.resize((round(tw*scale), round(th*scale)))
            frame.paste(target, (round((tx-mx)*scale), round((my+mh-ty-th)*scale)), target)
        frame.thumbnail((1000, 680))
        dest = out/f'preview-{i:03}.png'
        frame.save(dest)
        rendered.append({'time': sample['time'], 'path': str(dest)})
    preview(rendered, out/'motion.gif')
    selected = [rendered[round(i*(len(rendered)-1)/5)] for i in range(6)]
    with Image.open(selected[0]['path']) as first:
        width, height = first.size
    sheet = Image.new('RGB', (width*3, height*2))
    for i, sample in enumerate(selected):
        with Image.open(sample['path']) as frame:
            sheet.paste(frame, ((i%3)*width, (i//3)*height))
    sheet.save(out/'frames.png')
    return {'samples': len(samples), 'flight_poses': len(values)}


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/moodboard-attachment-flight')).resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa.wait("hasattr(drv.main_window().scene,'mixie_moodboard_images')", timeout=30)
    qa.eval("assert __import__('os').environ.get('MIXAR_QA')=='1'\nresult=True")
    assert not board(qa), 'Use a fresh isolated QA app'
    # A recognizable reference makes the source, deformation and original easy to inspect.
    photo = Image.new('RGB', (420, 280), '#25435a')
    draw = ImageDraw.Draw(photo)
    draw.ellipse((210, 25, 310, 125), fill='#eaba66')
    draw.polygon([(0, 280), (120, 60), (240, 280)], fill='#69baa9')
    draw.polygon([(120, 280), (290, 110), (420, 280)], fill='#42978c')
    draw.text((18, 18), 'MOODBOARD REFERENCE', fill='white')
    path = out/'landscape.png'
    photo.save(path)
    qa.step('import_reference_into_drawer', batch_drop, qa, [str(path)])
    qa.wait('bpy.context.window_manager.mixar_moodboard_drawer_amount>.998', timeout=8)
    item = board(qa)[0]
    original = qa.eval(f'result=[(i.position_x,i.position_y,i.scale) for i in {SCENE}.mixie_moodboard_images]')
    results = {}
    _hover_off(qa)
    try:
        clear_selection(qa)
        qa.eval('bpy.ops.mixar.bubble_minimise(); result=True')
        pause(qa, .4)
        results['pill'] = qa.step('selection_flies_to_resting_pill', record, qa, item['id'], out/'pill', minimized=True)
        assert len(attachments(qa)) == 1
        assert attachments(qa)[0]['path'] == item['name']
        results['repeat'] = qa.step('repeated_selection_is_quiet', record, qa, item['id'], out/'repeat', expected=False, minimized=True)
        clear_selection(qa)
        qa.eval('bpy.ops.mixar.bubble_restore(); result=True')
        qa.wait("bool(drv.find(area_type='AGENT_BUBBLE',prop='mixie_chat_input'))", timeout=10)
        pause(qa, .4)
        results['collapse'] = qa.step('outside_selection_waits_for_resting_pill', record,
                                      qa, item['id'], out/'collapse', minimized=True)
        clear_selection(qa)
        qa.eval('bpy.ops.mixar.bubble_restore(); result=True')
        pause(qa, .4)
        results['composer'] = qa.step('script_selection_flies_to_open_composer', record,
                                      qa, item['id'], out/'composer', scripted=True)
        assert len(attachments(qa)) == 1
        assert qa.find(surface='reference_preview')['total'] >= 1
        qa.eval("hit=drv.find_one(area_type='AGENT_BUBBLE',prop='mixie_chat_input')\n"
                "win=hit['_win']\nwith bpy.context.temp_override(window=win):\n"
                f"    result=win.mixar_qa_capture_frame(filepath={str(out/'attached.png')!r})")
        assert qa.eval(f'result=[(i.position_x,i.position_y,i.scale) for i in {SCENE}.mixie_moodboard_images]') == original
        clear_selection(qa)
        results['remove'] = qa.step('removal_during_flight_cancels', record, qa, item['id'], out/'remove', remove=True, scripted=True)
        assert not attachments(qa)
        assert len(board(qa)) == 1, 'The original reference was removed'
    finally:
        _hover_on(qa)
    return {'captures': results, 'output': str(out), 'credits_used': 0}


if __name__ == '__main__':
    run_scenario('moodboard_attachment_flight_e2e', run)
