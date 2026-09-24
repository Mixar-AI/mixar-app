#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise Box, multi-loop Lasso and Magic Select from the shared mask popup.

No credits: replace only the SAM manager boundary with deterministic PNG replies,
restoring it in finally. Real toolbar clicks, canvas gestures, native mask creation,
packed segments and compositing run in the app. Both drawer and editor are covered.
Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT; inspect the resulting PNGs.
"""

import hashlib
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
sys.path.insert(0, str(Path(__file__).parent))
from moodboard_drawer_e2e import drop, geometry, png, point, target, toggle

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/moodboard-segmentation'))
SCENE = 'drv.main_window().scene'
STATE = f'{SCENE}.mixie_edit_tool_state'
IMAGES = f'{SCENE}.mixie_moodboard_images'

FIXTURE = '''
import io
from PIL import Image, ImageDraw
from mixar.modules.moodboard.core import scene_segment_manager as sam
drv._qa_original_sam = sam._scene_segment_manager
class FixtureSAM:
    def __init__(self):
        self.calls = []
        self.fail_next = False
    def is_ready(self, image): return True
    def is_uploading(self, image): return False
    def get_uploaded_image_size(self, image): return tuple(image.size)
    def queue_upload(self, image, img_item=None, on_complete=None):
        if on_complete: on_complete(True, 'QA fixture ready')
        return True
    def answer(self, kind, image, payload, callback):
        self.calls.append({'kind':kind, 'payload':payload if kind != 'lasso' else len(payload)})
        failed = self.fail_next
        self.fail_next = False
        if kind == 'lasso':
            data = payload
        else:
            mask = Image.new('L', tuple(image.size), 0)
            w,h = image.size
            ImageDraw.Draw(mask).rectangle((int(w*.25),int(h*.25),int(w*.7),int(h*.7)), fill=255)
            buffer = io.BytesIO()
            mask.save(buffer, format='PNG')
            data = buffer.getvalue()
        def done():
            callback(not failed, None if failed else data,
                     'No object detected in QA failure fixture' if failed else '')
            return None
        bpy.app.timers.register(done, first_interval=.35)
        return True
    def request_box_segmentation(self, image, box, on_complete=None):
        return self.answer('box', image, box, on_complete)
    def request_mask_segmentation(self, image, mask_bytes, on_complete=None):
        return self.answer('lasso', image, mask_bytes, on_complete)
    def request_segmentation(self, image, points, on_complete=None):
        return self.answer('point', image, points, on_complete)
sam._scene_segment_manager = FixtureSAM()
drv._qa_sam = sam._scene_segment_manager
result = True
'''


def image_expr(node_id):
    return f'next(i for i in {IMAGES} if i.node_id == {node_id!r})'


def snapshot(qa, name, host):
    time.sleep(.2)
    return qa.cmd('snap', path=str(OUT / f'{name}.png'), area=host,
                  annotate={'surface': 'moodboard_media'})


def image_pixels(qa, node_id, host, name):
    # Crop strictly to the image target so changing toolbars/labels cannot
    # disguise a stale cached texture. Successive completed masks must paint.
    path = OUT / f'{host}-{name}-image.png'
    qa.cmd('snap', path=str(path), margin=0,
           target={'surface':'moodboard_media', 'text':node_id, 'area_type':host})
    return hashlib.sha256(path.read_bytes()).hexdigest()


def activate(qa, tool, host):
    qa.click(area_type=host, text='Image mask selection tools')
    qa.wait(f"bool(drv.find(popup=True, op='MIXIE_OT_moodboard_{tool}_tool'))", timeout=4)
    qa.click(popup=True, op=f'MIXIE_OT_moodboard_{tool}_tool')
    expected = {'box_mask': 'BOX_MASK', 'lasso': 'LASSO', 'magic_select': 'MAGIC_SELECT'}[tool]
    qa.wait(f'{STATE}.active_tool == {expected!r}', timeout=4)
    qa.wait("not drv.find(popup=True, op='MIXIE_OT_moodboard_box_mask_tool')", timeout=4)


def gesture(qa, node_id, host, points, cancel=False):
    # Freeform gestures need a path; every point derives from the native media
    # target, and all actions remain real WM events with main-loop yields.
    return qa.eval(f'''
def draw():
    win=drv.main_window()
    media=drv.find_one(surface='moodboard_media', text={node_id!r}, area_type={host!r})
    x0,y0,x1,y1=media['rect']
    path=[(round(x0+fx*(x1-x0)),round(y0+fy*(y1-y0))) for fx,fy in {points!r}]
    x,y=path[0]
    drv.move_to(win,x,y)
    yield .08
    drv._sim(win,type='LEFTMOUSE',value='PRESS',x=x,y=y)
    yield .08
    for x,y in path[1:]:
        drv.move_to(win,x,y)
        yield .04
    if {cancel!r}:
        drv.press(win,'ESC')
        yield .08
    drv._sim(win,type='LEFTMOUSE',value='RELEASE',x=x,y=y)
    yield .2
    return True
result=draw()
''')


def assert_segments(qa, node_id, count):
    item = image_expr(node_id)
    qa.wait(f'len({item}.segments) == {count}', timeout=8)
    if count:
        assert qa.eval(f'result=all(s.mask_image and s.mask_image.packed_file for s in {item}.segments)')
        assert qa.eval(f'result=bool({item}.display_image)')


def exercise(qa, node_id, host):
    qa.click(surface='moodboard_media', text=node_id, area_type=host)
    qa.press('HOME')  # Native Frame All, with the pointer in this canvas host.
    time.sleep(.35)
    item = image_expr(node_id)
    original = qa.eval(f'import hashlib; result=hashlib.sha256(bytes(int(v*255) for v in {item}.image.pixels)).hexdigest()')
    count = qa.eval(f'result=len({item}.segments)')
    snapshot(qa, f'{host}-before', host)

    activate(qa, 'box_mask', host)
    gesture(qa, node_id, host, [(.2,.2),(.3,.3),(.45,.45),(.7,.7)])
    assert_segments(qa, node_id, count+1)
    qa.wait(f"{STATE}.active_tool == 'NONE'", timeout=4)
    box = qa.eval("result=drv._qa_sam.calls[-1]")
    assert box['kind'] == 'box', box
    snapshot(qa, f'{host}-box-result', host)
    box_pixels = image_pixels(qa, node_id, host, 'box')

    activate(qa, 'lasso', host)
    gesture(qa, node_id, host, [(.2,.2),(.4,.2),(.4,.4),(.2,.4),(.2,.2)])
    qa.wait(f'len({STATE}.lasso_loops) == 1', timeout=4)
    gesture(qa, node_id, host, [(.55,.55),(.8,.55),(.8,.8),(.55,.8),(.55,.55)])
    qa.wait(f'len({STATE}.lasso_loops) == 2', timeout=4)
    snapshot(qa, f'{host}-lasso-loops', host)
    qa.press('RET')
    assert_segments(qa, node_id, count+3)
    qa.wait(f"{STATE}.active_tool == 'NONE'", timeout=4)
    snapshot(qa, f'{host}-lasso-result', host)
    lasso_pixels = image_pixels(qa, node_id, host, 'lasso')
    assert lasso_pixels != box_pixels, 'Lasso masks exist but the canvas texture stayed stale'

    activate(qa, 'magic_select', host)
    qa.click(surface='moodboard_media', text=node_id, area_type=host)
    assert_segments(qa, node_id, count+4)
    qa.wait(f'not {STATE}.magic_select_pending', timeout=4)
    snapshot(qa, f'{host}-magic-result', host)
    magic_pixels = image_pixels(qa, node_id, host, 'magic')
    assert magic_pixels != lasso_pixels, 'Magic mask exists but the canvas texture stayed stale'
    qa.eval('drv._qa_sam.fail_next=True; result=True')
    qa.click(surface='moodboard_media', text=node_id, area_type=host)
    qa.wait(f'not {STATE}.magic_select_pending', timeout=4)
    assert_segments(qa, node_id, count+4)
    qa.press('ESC')
    qa.wait(f"{STATE}.active_tool == 'NONE'", timeout=4)

    activate(qa, 'box_mask', host)
    gesture(qa, node_id, host, [(.3,.3),(.5,.5)], cancel=True)
    assert_segments(qa, node_id, count+4)
    qa.wait(f"{STATE}.active_tool == 'NONE'", timeout=4)
    calls = qa.eval('result=len(drv._qa_sam.calls)')
    activate(qa, 'box_mask', host)
    qa.click(surface='moodboard_media', text=node_id, area_type=host)
    qa.wait(f"{STATE}.active_tool == 'NONE'", timeout=4)
    assert qa.eval('result=len(drv._qa_sam.calls)') == calls
    assert not qa.eval(f'result={STATE}.box_select_has_selection')
    after = qa.eval(f'import hashlib; result=hashlib.sha256(bytes(int(v*255) for v in {item}.image.pixels)).hexdigest()')
    assert after == original, 'Segmentation mutated the original artwork'


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    assert qa.eval("import os; result=os.environ.get('MIXAR_QA') == '1'")
    qa.dismiss_splash()
    qa.eval(FIXTURE)
    try:
        if geometry(qa)['workspace'] != 'Zen Mode':
            qa.click(area_type='TOPBAR', op='MIXAR_OT_set_ui_mode_ai')
        if geometry(qa)['amount'] < .02:
            toggle(qa, 1)
        path = png(OUT/'reference.png', (80,110,160), width=256, height=256)
        node_id = drop(qa, path, target={'surface':'moodboard_drawer_panel'})
        qa.step('drawer_mask_tools', exercise, qa, node_id, 'VIEW_3D')
        qa.cmd('ensure_moodboard', sidebar=False)
        qa.step('editor_mask_tools', exercise, qa, node_id, 'MIXIE')
        return {'screenshots':str(OUT), 'sam_boundary':'deterministic fixture; no provider call'}
    finally:
        qa.press('ESC')
        qa.eval('''
from mixar.modules.moodboard.core import scene_segment_manager as sam
sam._scene_segment_manager=drv._qa_original_sam
del drv._qa_original_sam
del drv._qa_sam
result=True
''')


if __name__ == '__main__':
    run_scenario('moodboard_segmentation_e2e', run)
