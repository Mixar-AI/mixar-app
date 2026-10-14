# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit regression: message fills must not erase the native island bed.

Run on an isolated Windows QA app with QA_HARNESS, MIXAR_QA_PORT,
QA_SCENARIO_OUT. QA_MESSAGE_BASELINE=1 records the unfixed appearance.
"""
import json
import os
from pathlib import Path
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
import windows_transcript_opacity_e2e as shared


def run(qa):
    out = Path(os.environ['QA_SCENARIO_OUT'])
    out.mkdir(parents=True, exist_ok=True)
    qa.dismiss_splash()
    state = qa.eval("import os\nassert os.environ.get('MIXAR_QA')=='1'\n"
                    "assert not drv.main_window().scene.mixie_chat_messages\n"
                    "from mixar.modules.agent_bubble.ui.operators import hover_ops\n"
                    "result={'pid':os.getpid(), 'hover':bpy.app.timers.is_registered(hover_ops._hover_tick)}\n"
                    "hover_ops.unregister()")
    wash = qa.eval(f'result=list({shared.THEME})')
    fixture = str(Path(__file__).with_name('windows_transcript_fixture.py'))
    try:
        shared.native.foreground(state['pid'])
        qa.eval('result=str(bpy.ops.mixar.bubble_restore())')
        qa.eval(f'ns={{}}\nexec(compile(open({fixture!r}).read(), {fixture!r}, "exec"), ns)\n'
                "bpy.app.driver_namespace['qa_message_fixture']=ns\nresult=ns['install']()")
        count = qa.eval("s=drv.main_window().scene\n"
                "for i, text in enumerate(['First response', 'I will build a wooden dining table with four matching chairs.', 'Rendering viewport...']):\n"
                "    m=s.mixie_chat_messages.add()\n"
                "    m.bubble_id='qa-message-'+str(i)\n"
                "    m.sender='AGENT'\n    m.message_type='AGENT'\n"
                "    m.content=m.text=text\n"
                "result=len(s.mixie_chat_messages)")
        assert count == 3
        shared.redraw(qa)
        visible = shared.native.windows(state['pid'])
        island = next(w for w in visible if w.get('role') == 'island')
        host = next(w for w in visible if not w.get('role'))
        # Fixed physical capture size makes background comparisons independent of DPI settings.
        shared.native.resize(island['hwnd'], 1057, 508)
        shared.native.move(island['hwnd'], host['client'][0]+150, host['client'][1]+120)
        results = {}
        for label, value in [('bright', 1.0), ('dark', 0.0)]:
            metrics = shared.capture(qa, state['pid'], out, label, value, (.118, .118, .118, .20))
            pixels = np.asarray(Image.open(metrics['path']).convert('RGB'), dtype=float)
            geo = metrics['geometry']
            x, y, width, height = geo['region']
            top = geo['height']-y-height
            # A low row percentile removes glyphs while retaining broad message holes.
            interior = pixels[top+12:top+height-12, x+int(width*.15):x+int(width*.30)]
            row_beds = np.percentile(interior, 20, axis=1)
            error = float(np.max(np.abs(row_beds-np.asarray(metrics['rgb']))))
            results[label] = {'max_message_bed_error':error, 'path':metrics['path']}
        (out/'metrics.json').write_text(json.dumps(results, indent=2))
        if os.environ.get('QA_MESSAGE_BASELINE') != '1':
            for label, result in results.items():
                assert result['max_message_bed_error'] < 10, (label, result)
        return results
    finally:
        qa.eval("ns=bpy.app.driver_namespace.pop('qa_message_fixture', None)\n"
                "if ns: ns['remove']()\n"
                f'{shared.THEME}={wash!r}\n'
                "s=drv.main_window().scene\n"
                "for i in range(len(s.mixie_chat_messages)-1,-1,-1):\n"
                "    if s.mixie_chat_messages[i].bubble_id.startswith('qa-message-'): s.mixie_chat_messages.remove(i)\n"
                "result=True")
        if state['hover']:
            qa.eval('from mixar.modules.agent_bubble.ui.operators import hover_ops\n'
                    'hover_ops.register()\nresult=True')


if __name__ == '__main__':
    run_scenario('windows_message_opacity_e2e', run)
