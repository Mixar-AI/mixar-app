# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Free Windows workflow, compact layout and transcript navigation replay.

Run through windows_ui_capture.py for compositor proof at every snapshot.
Only this QA process's native window and disposable preferences are changed.
"""
import json
import os
from pathlib import Path
import time

import windows_glass_fixture as native
from blender53_visual_ui_e2e import run as visual_stage, FIELD
from chat_blocks_navigation import VIEW, scroll_code
from header_adaptive_e2e import check as header_check
from lib import ensure_scenes_drawer

MODE_ZEN = {'area_type': 'TOPBAR', 'op': 'MIXAR_OT_set_ui_mode_ai'}
MODE_ENGINE = {'area_type': 'TOPBAR', 'op': 'MIXAR_OT_set_ui_mode_pro'}


def capture(qa, folder, label, island=False):
    time.sleep(.5)
    args = {'target': FIELD, 'margin': 3000} if island else {}
    qa.cmd('snap', path=str(folder / (label + '.png')), **args)
    (folder / (label + '-widgets.json')).write_text(json.dumps(qa.find(limit=5000), indent=2))


def center(qa):
    left = qa.find(**MODE_ZEN)['widgets'][0]['rect']
    right = qa.find(**MODE_ENGINE)['widgets'][0]['rect']
    width = qa.eval('result=drv.main_window().width')
    midpoint = (left[0] + right[2]) / 2
    assert abs(midpoint - width / 2) <= 2, (left, right, width)
    return midpoint


def menu(qa, folder, label, **query):
    qa.click(**query)
    qa.wait('bool(drv.find(popup=True))', timeout=5)
    capture(qa, folder, label)
    qa.press('ESC')
    qa.wait('not drv.find(popup=True)', timeout=5)


def transcript(qa, folder):
    for stage in ('empty', 'populated', 'idle'):
        visual_stage(stage, qa)
    draft = qa.eval('result=drv.main_window().scene.mixie_chat_input')
    qa.eval("s=drv.main_window().scene\n"
            "for i in range(18):\n"
            " m=s.mixie_chat_messages.add(); m.sender='AGENT'; m.message_type='AGENT'\n"
            " m.bubble_id='qa-windows-scroll-'+str(i)\n"
            " m.content=m.text='Local UI item '+str(i)+' — readable wrapping, **bold text**, and scene controls.\\n'*3\n"
            "for w in bpy.context.window_manager.windows:\n"
            " for a in w.screen.areas:a.tag_redraw()\nresult=True")
    time.sleep(.7)
    results = {}
    for width, height in ((760, 480), (560, 370)):
        qa.eval(f'w=drv.find_one(**{FIELD!r})["_win"]\n'
                'with bpy.context.temp_override(window=w):\n'
                f' bpy.ops.mixar.bubble_set_size(width={width},height={height})\nresult=True')
        time.sleep(.5)
        before = qa.eval(VIEW)
        actual_scale = [(b - a) / size for a, b, size in
                        zip(before['lower'], before['upper'],
                            (before['rect'][2] - before['rect'][0], before['rect'][3] - before['rect'][1]))]
        assert all(abs(v - 1) < .01 for v in actual_scale), actual_scale
        capture(qa, folder, f'transcript-{width}-bottom', True)
        for _ in range(4):
            qa.eval(scroll_code(qa.eval(VIEW), True))
        after = qa.eval(VIEW)
        assert abs(after['lower'][1] - before['lower'][1]) > 5, (before, after)
        assert qa.eval('result=drv.main_window().scene.mixie_chat_input') == draft
        capture(qa, folder, f'transcript-{width}-scrolled', True)
        results[str(width)] = {'before': before, 'after': after, 'text_scale': actual_scale}
    return results


def fresh_tooltip(qa, folder, saved_scale):
    """Reopen a tooltip after scaling, rather than retaining its old bounds."""
    header = {'area_type': 'AGENT_BUBBLE', 'region_type': 'HEADER',
              'op': 'WM_OT_context_set_enum', 'text': 'Agent chat'}
    qa.click(**header)
    qa.eval('bpy.context.preferences.view.ui_scale=1.25\nresult=True')
    qa.eval(f"def hover():\n"
        f" h=drv.find_one(**{header!r});w=h['_win']\n"
        " x,y=drv.pick_click_point(h);drv.move_to(w,x,y)\n"
        " yield .4\n"
        f" f=drv.find_one(**{FIELD!r});x,y=drv.pick_click_point(f)\n"
        " drv.move_to(w,x-4,y)\n yield .2\n drv.move_to(w,x,y)\n yield 1.5\n"
        " return True\nresult=hover()")
    capture(qa, folder, 'fresh-chat-tooltip-125', True)
    qa.click(**header)
    qa.eval(f'bpy.context.preferences.view.ui_scale={saved_scale!r}\nresult=True')


def run(qa):
    folder = Path(os.environ['QA_SCENARIO_OUT'])
    saved = qa.eval("import os\nassert os.environ.get('MIXAR_QA')=='1'\n"
                    "result={'pid':os.getpid(),'scale':bpy.context.preferences.view.ui_scale,"
                    "'workspace':drv.main_window().workspace.name}")
    parent = max((w for w in native.windows(saved['pid']) if not w.get('role')),
                 key=lambda w: (w['rect'][2] - w['rect'][0]) * (w['rect'][3] - w['rect'][1]))
    user = native._api()
    # WS_MAXIMIZE is observed before a process-scoped SW_RESTORE.
    maximized = bool(parent['style'] & 0x01000000)
    user.ShowWindow(parent['hwnd'], 9)
    results = {}
    try:
        remaining = os.environ.get('QA_UI_REMAINING') == '1'
        if remaining:
            # Earlier captures already prove scrolling and compact toolbar
            # geometry. This focused continuation proves the corrected idle
            # draft contract and the three surfaces not reached previously.
            for stage in ('empty', 'populated', 'idle'):
                visual_stage(stage, qa)
                if stage == 'empty':
                    fresh_tooltip(qa, folder, saved['scale'])
            results['scope'] = 'idle draft and remaining workflow surfaces'
        else:
            results['transcript'] = transcript(qa, folder)
        qa.cmd('dismiss_chat')
        native.resize(parent['hwnd'], 1280, 900)
        time.sleep(.7)
        qa.cmd('set_mode', mode='zen')
        ensure_scenes_drawer(qa)
        results['zen_center'] = center(qa)
        capture(qa, folder, 'zen-wide')
        if not remaining:
            results['toolbar'] = {}
            for scale in (.8, 1., 1.25, 1.5, 2.):
                results['toolbar'][str(scale)] = header_check(qa, scale)
        qa.eval(f"bpy.context.preferences.view.ui_scale={saved['scale']!r}\nresult=True")
        time.sleep(.5)
        for label in (() if remaining else ('File', 'Edit', 'Render')):
            menu(qa, folder, 'zen-' + label.lower(), area_type='TOPBAR',
                 text=label, but_type='Pulldown')
        # Native button rows have no custom-surface index. Select by their
        # visible label, as a user does, rather than a list ordinal.
        menu(qa, folder, 'render-settings', area_type='VIEW_3D', region_type='HEADER',
             but_type='Popover', text='Render Settings')
        qa.cmd('set_mode', mode='engine')
        results['engine_center'] = center(qa)
        capture(qa, folder, 'engine-wide')
        native.resize(parent['hwnd'], 1024, 800)
        time.sleep(.7)
        center(qa)
        menu(qa, folder, 'engine-workspaces-compact', area_type='TOPBAR',
             text='Workspaces', but_type='Pulldown')
        qa.cmd('workspace', name='Texturing')
        qa.wait("drv.main_window().workspace.name=='Texturing'", timeout=10)
        capture(qa, folder, 'texturing-compact')
        qa.cmd('workspace', name='Layout')
        capture(qa, folder, 'layout-restored')
        qa.cmd('set_mode', mode='zen')
        results['paid_requests'] = 0
        (folder / 'checks.json').write_text(json.dumps(results, indent=2))
        return results
    finally:
        qa.eval(f"bpy.context.preferences.view.ui_scale={saved['scale']!r}\nresult=True")
        rect = parent['rect']
        native.move(parent['hwnd'], rect[0], rect[1])
        native.resize(parent['hwnd'], rect[2] - rect[0], rect[3] - rect[1])
        if maximized:
            user.ShowWindow(parent['hwnd'], 3)
        if saved['workspace'] == 'Zen Mode':
            qa.cmd('set_mode', mode='zen')
        else:
            qa.cmd('set_mode', mode='engine')
            qa.cmd('workspace', name=saved['workspace'])
        restored = qa.eval("result={'scale':bpy.context.preferences.view.ui_scale,"
                           "'workspace':drv.main_window().workspace.name}")
        assert restored['scale'] == saved['scale'] and restored['workspace'] == saved['workspace']
        (folder / 'restored.json').write_text(json.dumps(restored, indent=2))
