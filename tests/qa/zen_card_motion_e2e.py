#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Actual native card arrivals/reflow without forced redraws or credit spend.

QA_HARNESS=/path/to/harness QA_SCENARIO_OUT=/tmp/zen-cards \
    python3 tests/qa/zen_card_motion_e2e.py
Inspect the generated contact sheets/GIFs with the temporal state verdict.
"""

import inspect
import json
import os
from pathlib import Path
import sys

from PIL import Image

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from agent_panel_cards_e2e import _click_at, _centre
from zen_motion_capture import contact_sheet, preview


ITEMS = [dict(id=name.lower(), text=f'Motion {name}.', status='pending')
         for name in ('Alpha', 'Beta', 'Gamma')]


def _capture_in_app(output, items, dismiss_point):
    import time
    from pathlib import Path
    import bpy
    import qa_driver as drv
    from mixar.modules.agent_panel.core.cards import mirror_todo_items

    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    existing = drv.find(surface='agent_panel_card')
    assert existing, 'Panel must be settled before recording'
    win = existing[0]['_win']
    region = next(r for r in existing[0]['_area'].regions
                  if r.type == existing[0]['region_type'])
    # Native region origin includes the full slot band below the existing
    # rows. Only the already-exported right/top card edges bound the crop.
    # Cropping BEFORE PNG avoids full-window encoding consuming the motion.
    x0, y0 = region.x, region.y
    x1 = max(target['rect'][2] for target in existing) + 4
    y1 = max(target['rect'][3] for target in existing) + 4
    bounds = [x0, y0, x1, y1]
    frames = []
    began = time.monotonic()

    def record():
        targets = drv.find(surface='agent_panel_card')
        path = out / f'frame-{len(frames):03}.png'
        with bpy.context.temp_override(window=win):
            assert win.mixar_qa_capture_frame(
                filepath=str(path), x=x0, y=y0, width=x1-x0, height=y1-y0,
            ), 'Unable to observe native frame'
        frames.append({'time': time.monotonic()-began, 'path': str(path),
                       'capture_bounds': bounds,
                       'rects': {target['text']: target['rect'] for target in targets},
                       'mirror': [c.task_id for c in bpy.context.window_manager.mixar_agent_cards]})

    record()
    if dismiss_point is None:
        mirror_todo_items(items)
    else:
        # Same atomic native gesture as the harness's _click_at helper;
        # coordinates came from the currently exported dismiss target.
        x, y = dismiss_point
        drv.move_to(win, x, y)
        drv._sim(win, type='LEFTMOUSE', value='PRESS', x=x, y=y)
        drv._sim(win, type='LEFTMOUSE', value='RELEASE', x=x, y=y)
    while time.monotonic()-began < 0.85:
        yield 0.02
        record()
    # The last two frames are sampled after both motion windows have elapsed.
    yield 0.3
    record()
    yield 0.15
    record()
    return frames


def capture(qa, output, *, append=False, dismiss_point=None):
    frames = qa.eval(inspect.getsource(_capture_in_app) +
                     f'\nresult=_capture_in_app({str(output)!r},'
                     f'{ITEMS if append else None!r},{dismiss_point!r})')
    preview(frames, Path(output)/'motion.gif')
    contact_sheet(frames, Path(output)/'frames.png')
    (Path(output)/'frames.json').write_text(json.dumps(frames, indent=2)+'\n')
    return frames


def coordinates(frames, name, axis):
    return [frame['rects'][name][axis] for frame in frames if name in frame['rects']]


def assert_settled(frames):
    assert frames[-1]['rects'] == frames[-2]['rects'], 'Layout kept moving after settling'
    with Image.open(frames[-1]['path']) as a, Image.open(frames[-2]['path']) as b:
        assert a.tobytes() == b.tobytes(), 'Pending cards kept repainting a changing pose'


def verify_arrival(frames):
    assert 'Motion Gamma' not in frames[0]['rects']
    xs = coordinates(frames, 'Motion Gamma', 0)
    assert len(set(xs)) >= 3, f'Late arrival had no intermediate native positions: {xs}'
    assert all(a <= b for a, b in zip(xs, xs[1:])), xs
    for name in ('Motion Alpha', 'Motion Beta'):
        rects = [tuple(frame['rects'][name]) for frame in frames]
        assert len(set(rects)) == 1, f'{name} replayed its arrival on append'
    assert frames[-1]['mirror'] == ['alpha', 'beta', 'gamma']
    assert_settled(frames)
    return {'frames': len(frames), 'arrival_x': xs, 'existing_rows_stable': True}


def verify_dismissal(frames):
    xs = coordinates(frames, 'Motion Alpha', 0)
    assert len(set(xs)) >= 2, f'Dismissal popped without sliding: {xs}'
    assert all(a >= b for a, b in zip(xs, xs[1:])), xs
    reflow = {}
    for name in ('Motion Beta', 'Motion Gamma'):
        ys = coordinates(frames, name, 1)
        assert ys[-1] > ys[0], f'{name} did not move into the free row: {ys}'
        assert len(set(ys)) >= 3, f'{name} reflow snapped: {ys}'
        assert all(a <= b for a, b in zip(ys, ys[1:])), ys
        reflow[name] = ys
    assert 'Motion Alpha' not in frames[-1]['rects']
    assert frames[-1]['mirror'] == ['beta', 'gamma']
    assert_settled(frames)
    return {'frames': len(frames), 'departure_x': xs, 'reflow_y': reflow}


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/zen-card-motion'))
    out.mkdir(parents=True, exist_ok=True)
    qa.step('ready', qa.cmd, 'wait_login', timeout=60)
    qa.step('seed_two_pending_cards', qa.eval,
            'from mixar.modules.agent_panel.core.cards import clear_cards, mirror_todo_items\n'
            f'clear_cards()\nresult=mirror_todo_items({ITEMS[:2]!r})')
    try:
        qa.step('panel_visible', qa.wait,
                "len(drv.find(surface='agent_panel_card')) == 2", timeout=15)
        qa.eval('def settle():\n    yield .7\n    return True\nresult=settle()')
        arriving = qa.step('record_late_arrival', capture, qa, out/'arrival', append=True)
        arrival = qa.step('verify_late_arrival', verify_arrival, arriving)
        point = qa.step('native_dismiss_target', _centre, qa, 'agent_panel_dismiss', 0)
        departing = qa.step('record_dismiss_and_reflow', capture, qa, out/'dismissal',
                            dismiss_point=point)
        dismissal = qa.step('verify_dismiss_and_reflow', verify_dismissal, departing)
        # The surviving card's actual hit target remains usable after reflow.
        point = qa.step('survivor_eye_target', _centre, qa, 'agent_panel_eye', 0)
        qa.step('survivor_eye_click', _click_at, qa, *point)
        qa.step('survivor_eye_expanded', qa.wait,
                "any(w['text']=='Motion Beta.' for w in drv.find(surface='agent_panel_card'))",
                timeout=8)
        results = {'arrival': arrival, 'dismissal': dismissal, 'paid_requests': 0}
        (out/'verdict.json').write_text(json.dumps(results, indent=2)+'\n')
        return results
    finally:
        qa.eval('from mixar.modules.agent_panel.core.cards import clear_cards\nclear_cards()\nresult=True')


if __name__ == '__main__':
    run_scenario('zen_card_motion_e2e', run)
