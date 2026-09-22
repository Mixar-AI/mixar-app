#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""No-credit native glass/progress replay. Requires an isolated QA app.

QA_HARNESS=/path/to/harness QA_SCENARIO_OUT=/tmp/task-card-glass \
    python3 tests/qa/agent_panel_glass_progress_e2e.py

Inspect running.png, bright.png, completed.png and progress.gif alongside the
verdict. The fill is observed from real redraws, never a forced repaint loop.
"""

import inspect
import json
import os
from pathlib import Path
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

SPACE = "space=next(a.spaces.active for a in drv.main_window().screen.areas if a.type=='VIEW_3D')\n"
HELPERS = "ns=bpy.app.driver_namespace['task_card_glass_qa']\n"

ITEMS = [
    {'id': 'glass-a', 'text': 'Playing around with textures.', 'status': 'in_progress'},
    {'id': 'glass-b', 'text': 'Working on stone block.', 'status': 'in_progress'},
    {'id': 'glass-c', 'text': 'Working on wooden fence.', 'status': 'pending'},
]


def _capture(path):
    """In-app: crop the native framebuffer using the actual pane targets."""
    import bpy
    import qa_driver as drv
    targets = drv.find(surface='agent_panel_progress')
    assert targets
    win = targets[0]['_win']
    x0 = max(0, min(t['rect'][0] for t in targets) - 12)
    y0 = max(0, min(t['rect'][1] for t in targets) - 12)
    x1 = max(t['rect'][2] for t in targets) + 13
    y1 = max(t['rect'][3] for t in targets) + 13
    with bpy.context.temp_override(window=win):
        assert win.mixar_qa_capture_frame(
            filepath=path, x=x0, y=y0, width=x1-x0, height=y1-y0)
    return {'path': path, 'bounds': [x0, y0, x1, y1],
            'progress': {t['text']: float(t['value']) for t in targets},
            'rects': {t['text']: t['rect'] for t in targets}}


def _record(output):
    import time
    from pathlib import Path
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    frames = []
    while time.monotonic() - start < 18:
        frame = _capture(str(out / f'frame-{len(frames):03}.png'))
        frame['time'] = time.monotonic() - start
        frames.append(frame)
        yield .3
    return frames


def settle(qa, seconds=.7):
    qa.eval(f'def settle():\n    yield {seconds!r}\n    return True\nresult=settle()')


def mirror(qa, items, clear=False):
    qa.eval('from mixar.modules.agent_panel.core.cards import clear_cards, mirror_todo_items\n'
            + ('clear_cards()\n' if clear else '')
            + f'result=mirror_todo_items({items!r})')


def progress(qa):
    return qa.eval("result={t['text']:float(t['value']) "
                   "for t in drv.find(surface='agent_panel_progress')}")


def capture(qa, path):
    return qa.eval(HELPERS + f"result=ns['_capture']({str(path)!r})")


def verify_motion(frames, out):
    for task in ('glass-a', 'glass-b'):
        values = [f['progress'][task] for f in frames]
        assert all(.08 <= v <= .901 for v in values), values
        assert all(a <= b for a, b in zip(values, values[1:])), values
        assert values[-1] - values[0] > .2, values
    assert all(f['progress']['glass-c'] == 0 for f in frames)
    images = [Image.open(f['path']).convert('RGB') for f in frames]
    try:
        assert len({im.size for im in images}) == 1
        # Compare lower interior of the running card, excluding cat and text.
        a, b = frames[0], frames[-1]
        rect = a['rects']['glass-a']
        x = int((rect[0]+rect[2])*.5) - a['bounds'][0]
        y = a['bounds'][3] - (rect[1] + 12)
        assert images[-1].getpixel((x, y))[1] > images[0].getpixel((x, y))[1] + 8
        images[-1].save(out/'running.png')
        images[0].save(out/'progress.gif', save_all=True, append_images=images[1:],
                       duration=300, loop=0)
    finally:
        for im in images:
            im.close()


def verify_transparency(dark, bright):
    rect = dark['rects']['glass-c']
    x = int((rect[0]+rect[2])*.5) - dark['bounds'][0]
    y = dark['bounds'][3] - (rect[1] + 12)
    with Image.open(dark['path']) as a, Image.open(bright['path']) as b:
        old, new = a.convert('RGB').getpixel((x, y)), b.convert('RGB').getpixel((x, y))
    assert sum(new) > sum(old) + 60, (old, new)
    return {'dark_pixel': old, 'bright_pixel': new}


def verify_labels(frame):
    """Every running/pending pane must retain visible neutral task lettering."""
    counts = {}
    with Image.open(frame['path']) as image:
        for task, rect in frame['rects'].items():
            width, height = rect[2] - rect[0], rect[3] - rect[1]
            left = int(rect[0] + width * .2) - frame['bounds'][0]
            right = int(rect[0] + width * .85) - frame['bounds'][0]
            top = frame['bounds'][3] - int(rect[1] + height * .75)
            bottom = frame['bounds'][3] - int(rect[1] + height * .25)
            pixels = image.convert('RGB').crop((left, top, right, bottom)).getdata()
            counts[task] = sum(min(p) > 150 and max(p) - min(p) < 45 for p in pixels)
            assert counts[task] > 20, (task, 'task label missing', counts[task])
    return counts


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/task-card-glass')).resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa.step('panel_registered', qa.wait,
            "hasattr(bpy.context.window_manager,'mixar_agent_cards_active')", timeout=20)
    qa.eval("import os\nassert os.environ.get('MIXAR_QA') == '1'\n"
            "assert not bpy.context.window_manager.mixar_agent_cards_active, 'Use a clean QA app'")
    source = inspect.getsource(_capture) + '\n' + inspect.getsource(_record)
    qa.eval(f"ns={{}}\nexec({source!r},ns)\nbpy.app.driver_namespace['task_card_glass_qa']=ns")
    saved = qa.eval(SPACE +
                    "result=[space.shading.background_type,list(space.shading.background_color)]\n"
                    "space.shading.background_type='VIEWPORT'\nspace.shading.background_color=(.025,.025,.025)")
    try:
        qa.step('seed_tasks', mirror, qa, ITEMS, clear=True)
        qa.wait("len(drv.find(surface='agent_panel_progress'))==3", timeout=15)
        settle(qa)
        qa.step('running_and_pending_have_x', qa.eval,
                "assert len(drv.find(surface='agent_panel_dismiss'))==3\nresult=True")
        frames = qa.step('record_progress', qa.eval,
                         HELPERS + f"result=ns['_record']({str(out / 'frames')!r})")
        qa.step('verify_progress_pixels_and_state', verify_motion, frames, out)
        qa.step('running_and_pending_labels_visible', verify_labels, frames[-1])
        dark = capture(qa, out/'dark.png')
        qa.eval(SPACE + "space.shading.background_color=(.8,.8,.8)\n"
                "for a in drv.main_window().screen.areas: a.tag_redraw()")
        settle(qa, .2)
        bright = capture(qa, out/'bright.png')
        transparency = qa.step('viewport_visible_through_glass', verify_transparency, dark, bright)
        qa.eval(SPACE + "space.shading.background_color=(.025,.025,.025)\n"
                "for a in drv.main_window().screen.areas: a.tag_redraw()")

        before = progress(qa)
        mirror(qa, [ITEMS[1], ITEMS[0], ITEMS[2]])
        settle(qa)
        reordered = progress(qa)
        assert all(reordered[t] >= before[t] for t in before), (before, reordered)
        qa.step('main_tasks_have_no_eyes', qa.eval,
                "assert not drv.find(surface='agent_panel_eye')\nresult=True")

        failed = [dict(ITEMS[0], status='failed'), ITEMS[1], ITEMS[2]]
        mirror(qa, failed)
        settle(qa)
        assert progress(qa)['glass-a'] == 0
        capture(qa, out/'failed.png')
        qa.step('failed_x_click', qa.click, surface='agent_panel_dismiss', index=0)
        qa.wait("'glass-a' not in [c.task_id for c in bpy.context.window_manager.mixar_agent_cards]", timeout=5)
        # Explicitly reset this fixture fan-out so a dismissed id can be retried.
        mirror(qa, failed, clear=True)
        settle(qa)
        mirror(qa, ITEMS)
        settle(qa, .2)
        assert .08 <= progress(qa)['glass-a'] < .15, 'Retry inherited its old progress'

        # Capture during the existing completion dwell, before auto-dismiss.
        mirror(qa, [dict(ITEMS[0], status='done'), ITEMS[1], ITEMS[2]])
        settle(qa, .15)
        completed = capture(qa, out/'completed.png')
        assert completed['progress']['glass-a'] == 1
        qa.wait("'glass-a' not in [c.task_id for c in bpy.context.window_manager.mixar_agent_cards]", timeout=5)
        # Removal starts the surviving rows' 200ms reflow. Resolve the click
        # target after that move, so an old rectangle cannot race the gesture.
        settle(qa)
        qa.step('running_x_click', qa.click, surface='agent_panel_dismiss', index=0)
        # A fan-out already on screen retains its last card until dismissed;
        # the two-task threshold applies to incoming todo snapshots.
        qa.wait("[c.task_id for c in bpy.context.window_manager.mixar_agent_cards]==['glass-c']", timeout=5)
        settle(qa)
        qa.step('pending_x_click', qa.click, surface='agent_panel_dismiss', index=0)
        qa.wait("not drv.find(surface='agent_panel_card')", timeout=5)

        mirror(qa, ITEMS, clear=True)
        settle(qa)
        reset = progress(qa)
        assert all(.08 <= reset[t] < .15 for t in ('glass-a', 'glass-b')), reset
        helper = ROOT/'tests/qa/liquid_glass_pixels.py'
        pixels = qa.step('shared_gpu_material', qa.eval,
                         f"ns={{}}\nexec(compile(open({str(helper)!r}).read(),{str(helper)!r},'exec'),ns)\n"
                         f"result=ns['run']({str(ROOT)!r},{str(out/'gpu')!r})")
        result = {'frames': len(frames), 'progress_start': frames[0]['progress'],
                  'progress_end': frames[-1]['progress'], 'transparency': transparency,
                  'reorder': True, 'retry': True, 'completion': True, 'dismiss': True,
                  'new_turn': True, 'gpu': pixels, 'paid_requests': 0}
        (out/'verdict.json').write_text(json.dumps(result, indent=2)+'\n')
        return result
    finally:
        qa.eval(SPACE + 'from mixar.modules.agent_panel.core.cards import clear_cards\nclear_cards()\n'
                f'space.shading.background_type={saved[0]!r}\n'
                f'space.shading.background_color={saved[1]!r}\n'
                'bpy.app.driver_namespace.pop("task_card_glass_qa",None)\n'
                'for a in drv.main_window().screen.areas: a.tag_redraw()')


if __name__ == '__main__':
    run_scenario('agent_panel_glass_progress_e2e', run)
