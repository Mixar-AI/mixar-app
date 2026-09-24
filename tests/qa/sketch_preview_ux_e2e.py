# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Sketch → Done → inspect → Send, through the real native UI.

QA_HARNESS=/path/to/harness MIXAR_QA_PORT=4791 python3 tests/qa/sketch_preview_ux_e2e.py
Requires a fresh isolated app built from this checkout. Only agent transport
is replaced: no paid requests. Review the numbered screenshots alongside the
state assertions. This validates client UX, not model interpretation quality.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA
from scribble_send_scenario import draw, viewport
from sketch_controls import open_controls

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ.get('SKETCH_QA_OUT', '/tmp/mixar-sketch-preview-ux'))


def snap(qa, name):
    qa.cmd('snap', path=str(OUT / f'{name}.png'),
           target={'op': 'MIXAR_OT_scribble_toggle'}, margin=2500)


def preview_state(qa):
    return qa.eval('''
s = bpy.context.scene
result = [{'name':a.image_path, 'view':a.scribble_view, 'label':a.display_name,
           'packed':bool(bpy.data.images.get(a.image_path).packed_file)}
          for a in s.mixie_chat_pending_attachments]
''')


def assert_controls_fit(qa):
    controls = qa.find(area_type='AGENT_BUBBLE', region_type='TOOLS')['widgets']
    ops = {'MIXAR_OT_scribble_toggle', 'MIXIE_CHAT_OT_voice_toggle',
           'MIXIE_CHAT_OT_toggle_auto_mode', 'MIXIE_CHAT_OT_send_message',
           'MIXAR_OT_scribble_mark_clear', 'WM_OT_context_menu_enum',
           'MIXIE_CHAT_OT_add_image_from_file'}
    rects = [w['rect'] for w in controls if w.get('op') in ops]
    for i, a in enumerate(rects):
        for b in rects[i+1:]:
            assert min(a[2], b[2]) <= max(a[0], b[0]) or min(a[3], b[3]) <= max(a[1], b[1]), (a, b)


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.eval('''
import os, sys
assert os.environ.get('MIXAR_QA') == '1'
assert not bpy.context.scene.mixie_chat_messages, 'Use a fresh isolated QA scene'
sys.path.insert(0, QA_PATH)
import chat_send_probe
chat_send_probe.install()
'''.replace('QA_PATH', repr(str(ROOT / 'tests/qa'))))
    try:
        qa.eval('result=str(bpy.ops.mixar.bubble_restore())')
        qa.wait("bool(drv.find(op='MIXAR_OT_scribble_toggle'))", timeout=10)
        snap(qa, '01-composer')
        qa.step('start_sketch', qa.click, op='MIXAR_OT_scribble_toggle')
        qa.wait('bpy.context.window_manager.mixar_mark_armed', timeout=10)
        open_controls(qa)
        qa.step('choose_draw_to_build_before_drawing', qa.cmd, 'choose',
                widget={'op':'WM_OT_context_menu_enum', 'area_type':'AGENT_BUBBLE'},
                item='Draw to build')
        assert qa.eval('result=bpy.context.window_manager.mixar_mark_intent') == 'SKETCH'
        assert_controls_fit(qa)
        vp = viewport(qa)
        qa.step('draw_roof_left', draw, qa, vp, (.28,.57), (.40,.74))
        qa.wait('len(bpy.context.scene.mixar_marks)==1', timeout=10)
        # Done must include strokes that have not reached the idle commit timer.
        qa.eval('''
from mixar.modules.scribble_mark.ui.operators import mark_draw_ops
bpy.app.driver_namespace['sketch_qa_idle'] = mark_draw_ops.MARK_COMMIT_IDLE_S
mark_draw_ops.MARK_COMMIT_IDLE_S = 300.0
''')
        qa.step('draw_roof_right', draw, qa, vp, (.40,.74), (.52,.57))
        qa.step('draw_base', draw, qa, vp, (.28,.57), (.52,.57))
        qa.cmd('snap', path=str(OUT/'02-drawing.png'), area='VIEW_3D')
        snap(qa, '03-done-control')
        qa.step('done', qa.click, op='MIXAR_OT_scribble_toggle')
        qa.wait('not bpy.context.window_manager.mixar_mark_armed and '
                'len(bpy.context.scene.mixie_chat_pending_attachments)==1', timeout=10)
        first = preview_state(qa)
        assert first[0]['packed'] and 'annotated' in first[0]['name'], first
        assert qa.eval('result=len(bpy.context.scene.mixar_marks)') == 2
        assert_controls_fit(qa)
        snap(qa, '04-ready-to-send')
        qa.cmd('snap', path=str(OUT/'04-preview-target.png'),
               target={'op':'MIXAR_OT_scribble_toggle'}, margin=2500,
               annotate={'op':'MIXAR_OT_preview_sketch'})
        assert len(qa.find(surface='reference_preview')['widgets']) == 1
        qa.step('inspect_larger_preview', qa.click, op='MIXAR_OT_preview_sketch')
        qa.wait("any(a.type=='IMAGE_EDITOR' for w in bpy.context.window_manager.windows "
                "for a in w.screen.areas)", timeout=10)
        shown = qa.eval('''
result=[a.spaces.active.image.name for w in bpy.context.window_manager.windows
        for a in w.screen.areas if a.type=='IMAGE_EDITOR' and a.spaces.active.image]
''')
        assert first[0]['name'] in shown, shown
        # A newly opened OS window can have geometry before its first paint.
        # Advance its real redraws before capturing the visible image editor.
        qa.eval('''
w=next(w for w in bpy.context.window_manager.windows
       if any(a.type=='IMAGE_EDITOR' for a in w.screen.areas))
with bpy.context.temp_override(window=w):
    bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=2)
''')
        qa.cmd('snap', path=str(OUT/'05-larger-preview.png'),
               target={'area_type':'IMAGE_EDITOR', 'prop':'ui_mode'}, margin=2500)
        qa.eval('''
w=next(w for w in bpy.context.window_manager.windows
       if any(a.type=='IMAGE_EDITOR' for a in w.screen.areas))
with bpy.context.temp_override(window=w): bpy.ops.wm.window_close()
''')
        qa.eval('result=str(bpy.ops.mixar.bubble_restore())')
        qa.step('add_instructions', qa.cmd, 'set_text',
                widget={'prop':'mixie_chat_input', 'area_type':'AGENT_BUBBLE'},
                text='Build this triangular roof.', enter=False)
        qa.eval("drv.press(drv.find_one(prop='mixie_chat_input')['_win'], 'LEFT_SHIFT')")
        qa.eval('import chat_send_probe; chat_send_probe.connected=False')
        qa.step('disconnected_send_preserves_preview', qa.click, op='MIXIE_CHAT_OT_send_message')
        assert preview_state(qa) == first
        assert qa.eval('result=bpy.context.scene.mixie_chat_input') == 'Build this triangular roof.'
        assert qa.eval('import chat_send_probe; result=len(chat_send_probe.calls)') == 0
        # Native error reports are popups: dismiss before the next Send click.
        report = qa.find(popup=True, text='Not connected to server')['widgets'][0]
        qa.cmd('press', key='ESC', window=report['window'])
        qa.wait("not drv.find(popup=True)", timeout=5)
        qa.eval('import chat_send_probe; chat_send_probe.connected=True')
        qa.step('send_sketch', qa.click, op='MIXIE_CHAT_OT_send_message')
        qa.wait("len(__import__('chat_send_probe').calls)==1", timeout=10)
        payload = qa.eval('''
import chat_send_probe
p=chat_send_probe.calls[0]
s=bpy.context.scene
users=[m for m in s.mixie_chat_messages if m.sender=='USER']
result={'images':len(p.get('image_attachments') or []),
        'names':p.get('attachment_names'), 'intent':p['mark_context']['intent'],
        'strokes':p['mark_context']['sketch']['stroke_count'],
        'visible':[a.image_path for a in users[-1].attachments],
        'pending':len(s.mixie_chat_pending_attachments)}
''')
        assert payload['images'] == 2 and len(payload['names']) == 2, payload
        assert payload['visible'] == [first[0]['name']] and payload['pending'] == 0, payload
        assert payload['intent'] == 'sketch' and payload['strokes'] == 3, payload
        qa.eval('import chat_send_probe; chat_send_probe.settle(bpy.context.scene)')
        qa.eval('result=str(bpy.ops.mixar.bubble_restore())')
        snap(qa, '06-sent-one-image')
        # Another drawing must be discardable without deleting the sent sketch.
        qa.step('second_sketch', qa.click, op='MIXAR_OT_scribble_toggle')
        qa.wait('bpy.context.window_manager.mixar_mark_armed', timeout=10)
        open_controls(qa)
        qa.step('choose_point_to_edit', qa.cmd, 'choose',
                widget={'op':'WM_OT_context_menu_enum','area_type':'AGENT_BUBBLE'}, item='Point to edit')
        qa.eval('bpy.context.preferences.view.ui_scale=1.25')
        qa.eval("bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=2)")
        assert_controls_fit(qa)
        qa.step('draw_pointer', draw, qa, viewport(qa), (.35,.6), (.50,.7))
        qa.step('escape_to_preview', qa.cmd, 'press', key='ESC', window=viewport(qa)['window'])
        qa.wait('not bpy.context.window_manager.mixar_mark_armed and '
                'len(bpy.context.scene.mixie_chat_pending_attachments)==1', timeout=10)
        qa.eval('result=str(bpy.ops.mixar.bubble_restore())')
        second = preview_state(qa)
        assert_controls_fit(qa)
        snap(qa, '07-point-to-edit-125-percent')
        assert second[0]['name'] != first[0]['name']
        qa.step('remove_sketch_preview', qa.click, op='MIXIE_CHAT_OT_remove_attachment')
        qa.wait('not bpy.context.scene.mixie_chat_pending_attachments', timeout=10)
        assert qa.eval('result=bpy.context.window_manager.mixar_mark_intent') == 'AUTO'
        assert qa.eval("result=[m.state for m in bpy.context.scene.mixar_marks]") == ['SENT','SENT']
        assert qa.eval('result=bpy.data.images.get('+repr(first[0]['name'])+') is not None')
        assert qa.eval('from mixar.modules.scribble_mark.core import preview; '
                       'result=len(preview.outgoing_attachments(bpy.context.scene))') == 0
        snap(qa, '08-discarded')
        return {'passed':True, 'paid_requests':0, 'payload':payload,
                'previews':'annotated only', 'done_flushes_live_ink':True,
                'larger_preview':True, 'disconnected_retry':True,
                'discard_preserves_sent':True, 'steps':qa.log}
    finally:
        qa.eval('''
from mixar.modules.scribble_mark.ui.operators import mark_draw_ops
from mixar.modules.scribble_mark.core import scribble_mode
mark_draw_ops.MARK_COMMIT_IDLE_S=bpy.app.driver_namespace.pop('sketch_qa_idle',.6)
scribble_mode.disarm(bpy.context.window_manager)
bpy.context.preferences.view.ui_scale=1.0
import chat_send_probe
chat_send_probe.uninstall()
''')


if __name__ == '__main__':
    qa = QA()
    result = {'passed':False}
    try:
        result = run(qa)
    finally:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT/'verdict.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
