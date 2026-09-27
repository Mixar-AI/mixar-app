#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Magic Select against the REAL backend and SAM3 GPU service (spends credits).

Opt-in companion to ``moodboard_segmentation_e2e.py`` (which replaces the SAM manager with
a fixture): this one keeps the real ``SceneSegmentManager`` so the whole transport is
exercised — JPEG upload, ``/segment/point``, polling, mask download, compositing. It draws
its own reference (an apple and a mug on a table, rendered in-app with PIL so nothing
personal leaves the machine), clicks the apple, the mug and the bare wall, and records the
wall-clock time and state transitions of each click plus the toasts on screen.

Cost: three ``scene_segment_point`` credits on the account the build logs in with.
Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT; inspect ``probe.json`` and the PNGs.
"""

import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
sys.path.insert(0, str(Path(__file__).parent))
from moodboard_drawer_e2e import drop, geometry, toggle

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/moodboard-segmentation-live'))
SCENE = 'drv.main_window().scene'
STATE = f'{SCENE}.mixie_edit_tool_state'
IMAGES = f'{SCENE}.mixie_moodboard_images'
HOST = 'VIEW_3D'

# Rendered inside the app: its bundled Python ships PIL, the driver's may not.
REFERENCE = '''
from PIL import Image, ImageDraw
w, h = 1024, 768
im = Image.new('RGB', (w, h))
d = ImageDraw.Draw(im)
for y in range(h):
    t = y / h
    d.line([(0, y), (w, y)], fill=(int(200 - 60 * t), int(190 - 70 * t), int(170 - 80 * t)))
d.rectangle((0, int(h * .62), w, h), fill=(110, 80, 55))
cx, cy, r = 520, 430, 150
d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(190, 30, 35))
d.ellipse((cx - r * .55, cy - r * .75, cx - r * .15, cy - r * .35), fill=(235, 120, 120))
d.rectangle((cx - 8, cy - r - 40, cx + 8, cy - r + 10), fill=(70, 45, 20))
d.polygon([(cx + 8, cy - r - 20), (cx + 90, cy - r - 60), (cx + 60, cy - r + 5)], fill=(40, 140, 50))
d.rounded_rectangle((760, 300, 900, 470), radius=18, fill=(40, 80, 170))
d.ellipse((880, 340, 950, 430), outline=(40, 80, 170), width=16)
im.save(%r)
result = True
'''

TOASTS = '''
from mixar.modules.common.notifications import get_notification_store
result = [{'title': i.title, 'body': i.body} for i in get_notification_store()._items]
'''


def item(node_id):
    return f'next(i for i in {IMAGES} if i.node_id == {node_id!r})'


def snap(qa, name):
    time.sleep(.15)
    qa.cmd('snap', path=str(OUT / f'{name}.png'), area=HOST,
           annotate={'surface': 'moodboard_media'})


def activate(qa):
    qa.click(area_type=HOST, text='Image mask selection tools')
    qa.wait("bool(drv.find(popup=True, op='MIXIE_OT_moodboard_magic_select_tool'))", timeout=4)
    qa.click(popup=True, op='MIXIE_OT_moodboard_magic_select_tool')
    qa.wait(f"{STATE}.active_tool == 'MAGIC_SELECT'", timeout=4)


def click_rel(qa, node_id, fx, fy):
    """One real click at a fraction of the media target (fy measured from the bottom)."""
    return qa.eval(f'''
win = drv.main_window()
m = drv.find_one(surface='moodboard_media', text={node_id!r}, area_type={HOST!r})
x0, y0, x1, y1 = m['rect']
x = round(x0 + {fx} * (x1 - x0)); y = round(y0 + {fy} * (y1 - y0))
drv.move_to(win, x, y)
drv._sim(win, type='LEFTMOUSE', value='PRESS', x=x, y=y)
drv._sim(win, type='LEFTMOUSE', value='RELEASE', x=x, y=y)
result = (x, y)
''')


def observe(qa, node_id, label, want_segments, timeout=150):
    """Poll the tool's mirrored state until the click resolves; keep every transition."""
    t0 = time.time()
    log = []
    last = None
    while time.time() - t0 < timeout:
        s = qa.eval(f"result=dict(pending={STATE}.magic_select_pending, "
                    f"has_point={STATE}.magic_select_has_point, "
                    f"segments=len({item(node_id)}.segments), tool={STATE}.active_tool)")
        if s != last:
            log.append(dict(t=round(time.time() - t0, 2), **s))
            last = s
            if len(log) == 2:
                snap(qa, f'{label}-inflight')
        if s['segments'] >= want_segments and not s['pending']:
            break
        if not s['pending'] and not s['has_point'] and time.time() - t0 > 3:
            break  # terminal failure: the tool stays armed, the marker is gone
        time.sleep(.25)
    snap(qa, f'{label}-final')
    return dict(elapsed=round(time.time() - t0, 2), transitions=log,
                toasts=qa.eval(TOASTS))


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    assert qa.eval("import os; result=os.environ.get('MIXAR_QA') == '1'")
    qa.wait(f"{SCENE}.mixie_chat_state in ('IDLE', 'OFFLINE')", timeout=90)
    qa.dismiss_splash()
    if geometry(qa)['workspace'] != 'Zen Mode':
        qa.click(area_type='TOPBAR', op='MIXAR_OT_set_ui_mode_ai')
    if geometry(qa)['amount'] < .02:
        toggle(qa, 1)
    reference = OUT / 'apple.png'
    qa.eval(REFERENCE % str(reference))
    node_id = drop(qa, str(reference), target={'surface': 'moodboard_drawer_panel'})
    qa.click(surface='moodboard_media', text=node_id, area_type=HOST)
    qa.press('HOME')
    time.sleep(.4)
    snap(qa, '0-before')

    report = {}
    try:
        activate(qa)
        report['apple_xy'] = click_rel(qa, node_id, .508, .5)
        report['apple'] = observe(qa, node_id, '1-apple', 1)
        report['mug_xy'] = click_rel(qa, node_id, .81, .5)
        report['mug'] = observe(qa, node_id, '2-mug', 2)
        report['wall_xy'] = click_rel(qa, node_id, .1, .9)
        report['wall'] = observe(qa, node_id, '3-wall', 3, timeout=60)
        report['tool_after'] = qa.eval(f"result={STATE}.active_tool")
    finally:
        qa.press('ESC')
    qa.wait(f"{STATE}.active_tool == 'NONE'", timeout=4)
    report['segments'] = qa.eval(
        f"result=[(s.name, s.active, list(s.mask_image.size) if s.mask_image else None) "
        f"for s in {item(node_id)}.segments]")
    report['upload_ready'] = qa.eval(f'''
from mixar.modules.moodboard.core.scene_segment_manager import get_scene_segment_manager
result = get_scene_segment_manager().is_ready({item(node_id)}.image)
''')
    (OUT / 'probe.json').write_text(json.dumps(report, indent=1, default=str))

    assert report['apple']['transitions'][-1]['segments'] >= 1, report['apple']
    assert report['mug']['transitions'][-1]['segments'] >= 2, report['mug']
    assert report['tool_after'] == 'MAGIC_SELECT', 'the tool must stay armed between clicks'
    assert all(size == [1024, 768] for _, _, size in report['segments']), report['segments']
    return {'screenshots': str(OUT), 'probe': str(OUT / 'probe.json'),
            'seconds_per_click': [report[k]['elapsed'] for k in ('apple', 'mug', 'wall')]}


if __name__ == '__main__':
    run_scenario('moodboard_segmentation_live_e2e', run)
