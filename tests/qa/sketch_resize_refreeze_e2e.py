# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Sketch re-freezes on a main-loop tick after its viewport is resized.

QA_HARNESS=/path/to/harness MIXAR_QA_PORT=4791 python3 tests/qa/sketch_resize_refreeze_e2e.py

Requires a fresh isolated app built from this checkout, because
``WindowManager.mixar_window_resizing`` is native. A 125% UI scale grows the
global bars and shrinks the frozen region, so the modal must take a NEW freeze
while the first mark keeps its own still. The scenario asserts that the flag
reads False on the main loop, that the re-freeze happens and the first freeze
survives, and that a second mark lands on the new view.

The harness cannot drive AppKit's live-resize loop
(``-[NSWindow _resizeWithEvent:]``), which is where the macOS crash happened.
Check that by hand on macOS: arm Sketch, draw, drag a window corner for a few
seconds, release, and draw again. The app must stay up and the ink must land
on the re-captured frame. No agent requests are made.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA  # noqa: E402
from scribble_send_scenario import draw, viewport  # noqa: E402

OUT = Path(os.environ.get('SKETCH_QA_OUT', '/tmp/mixar-sketch-resize'))


def freeze_state(qa):
    return qa.eval('''
s=bpy.context.scene
result={'frame':s.mixar_mark_frame_name,
        'views':[m.view_name for m in s.mixar_marks],
        'resizing':bpy.context.window_manager.mixar_window_resizing,
        'armed':bpy.context.window_manager.mixar_mark_armed}
''')


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.eval('''
import os
assert os.environ.get('MIXAR_QA') == '1'
assert not bpy.context.scene.mixar_marks, 'Use a fresh isolated QA scene'
result=True
''')
    try:
        assert qa.eval('result=bpy.context.window_manager.mixar_window_resizing') is False
        qa.eval('result=str(bpy.ops.mixar.bubble_restore())')
        qa.wait("bool(drv.find(op='MIXAR_OT_scribble_toggle'))", timeout=10)
        qa.step('start_sketch', qa.click, op='MIXAR_OT_scribble_toggle')
        qa.wait('bpy.context.window_manager.mixar_mark_armed', timeout=10)

        before = viewport(qa)
        qa.step('draw_before_resize', draw, qa, before, (.30, .40), (.55, .60))
        qa.wait('len(bpy.context.scene.mixar_marks)==1', timeout=10)
        first = freeze_state(qa)
        qa.cmd('snap', path=str(OUT / '01-before-resize.png'), area='VIEW_3D')

        qa.eval('bpy.context.preferences.view.ui_scale=1.25')
        qa.eval("bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=2)")
        after = viewport(qa)
        assert (after['w'], after['h']) != (before['w'], before['h']), (before, after)
        qa.wait('bpy.context.scene.mixar_mark_frame_name != ' + repr(first['frame']),
                timeout=10)
        second = freeze_state(qa)
        assert second['armed'] and second['resizing'] is False, second
        assert qa.eval('result=bpy.data.images.get(' + repr(first['frame']) + ') is not None')
        qa.cmd('snap', path=str(OUT / '02-refrozen.png'), area='VIEW_3D')

        qa.step('draw_after_resize', draw, qa, after, (.35, .45), (.60, .65))
        qa.wait('len(bpy.context.scene.mixar_marks)==2', timeout=10)
        views = freeze_state(qa)['views']
        assert views[0] == first['views'][0] and views[1] != views[0], views
        qa.cmd('snap', path=str(OUT / '03-second-mark.png'), area='VIEW_3D')
        return {'passed': True, 'paid_requests': 0, 'first': first, 'refrozen': second,
                'views': views, 'live_os_resize': 'manual macOS check', 'steps': qa.log}
    finally:
        qa.eval('''
from mixar.modules.scribble_mark.core import scribble_mode
scribble_mode.disarm(bpy.context.window_manager)
bpy.context.preferences.view.ui_scale=1.0
''')


if __name__ == '__main__':
    qa = QA()
    result = {'passed': False}
    try:
        result = run(qa)
    finally:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / 'verdict.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
