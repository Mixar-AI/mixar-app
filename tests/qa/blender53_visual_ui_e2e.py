#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""UI-only upgrade capture replay against an already owned QA app.

Run stages sequentially: empty, populated, idle, tab:<enum>, zen,
moodboard, engine, texturing. No chat or generation requests are submitted.
QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT select the existing harness.
QA_DESKTOP_URL optionally captures the isolated Linux desktop through its
local sandbox API tunnel. Mac glass additionally needs native OS captures;
framebuffer images alone must never be counted as a translucency pass.
"""
import json
import os
from pathlib import Path
import sys
import subprocess
import time
from urllib.request import Request, urlopen

HARNESS = Path(os.environ['QA_HARNESS'])
sys.path[:0] = [str(HARNESS), str(HARNESS / 'scenarios')]
from lib import QA, ensure_scenes_drawer


class SandboxQA(QA):
    def cmd(self, cmd, _sock_timeout=None, **args):
        payload = {'args': ['raw', json.dumps({'cmd': cmd, 'args': args})]}
        request = Request(os.environ['QA_DRIVER_URL'], data=json.dumps(payload).encode(),
                          headers={'Content-Type': 'application/json'})
        response = json.load(urlopen(request, timeout=150))
        if not response.get('ok'):
            raise RuntimeError(f'{cmd}: {response}')
        return response['result']

FIELD = {'area_type': 'AGENT_BUBBLE', 'prop': 'mixie_chat_input'}
TABS = {'AGENT': 'Agent chat', 'THREE_D': '3D generation',
        'IMAGE': 'Image generation', 'VIDEO': 'Video generation',
        'SPLAT': 'Gaussian Splat world generation',
        'ADDON': 'Build a Blender add-on with the agent',
        'GENERATIONS': 'Your generations and connected asset libraries',
        'QUEUE': 'Generation queue'}


def draft(qa, lines):
    qa.cmd('set_text', text=lines[0], widget=FIELD, enter=False)
    window = qa.find(**FIELD)['widgets'][0]['window']
    for line in lines[1:]:
        qa.cmd('press', key='RET', shift=True, window=window)
        qa.cmd('type', text=line, window=window)


def blur(qa):
    # A header click commits the current edit. Escape intentionally cancels
    # back to the draft at focus entry, so it cannot represent idle text.
    qa.click(area_type='AGENT_BUBBLE', region_type='HEADER',
             op='WM_OT_context_set_enum', text=TABS['AGENT'])


def capture(qa, out, label, island=False):
    time.sleep(.7)
    state = qa.eval("import os,gpu\n"
                    "result={'pid':os.getpid(),'version':list(bpy.app.version),"
                    "'gpu':gpu.platform.backend_type_get(),'profile':os.environ.get('MIXAR_USER_RESOURCES'),"
                    "'input':drv.main_window().scene.mixie_chat_input,"
                    "'messages':len(drv.main_window().scene.mixie_chat_messages),"
                    "'tab':bpy.context.window_manager.mixar_bubble_tab,"
                    "'workspace':drv.main_window().workspace.name}")
    widgets = qa.find(area_type='AGENT_BUBBLE', limit=2000) if island else qa.find(limit=3000)
    (out / (label + '-state.json')).write_text(json.dumps({'state': state, 'widgets': widgets}, indent=2))
    if os.environ.get('QA_X_DISPLAY'):
        subprocess.run(['import', '-display', os.environ['QA_X_DISPLAY'], '-window', 'root',
                        str(out / (label + '-desktop.png'))], check=True, timeout=20)
    elif os.environ.get('QA_DESKTOP_URL'):
        data = urlopen(os.environ['QA_DESKTOP_URL'], timeout=45).read()
        assert data.startswith(b'\x89PNG'), 'sandbox desktop did not return PNG'
        (out / (label + '-desktop.png')).write_bytes(data)
    elif sys.platform == 'darwin' and island:
        # Capture the live region textures. The full-window snap tags every
        # region and can invalidate its own island-header target on Metal.
        from chat_refine_lifecycle_e2e import capture as region_capture
        region_capture(qa, out, label + '-buffer')
    else:
        args = {'path': str(out / (label + '-buffer.png'))}
        if island:
            args.update(target={'area_type': 'AGENT_BUBBLE', 'region_type': 'HEADER'}, margin=2000)
        qa.cmd('snap', **args)
    print(json.dumps({'capture': label, 'messages': state['messages'], 'tab': state['tab'],
                      'workspace': state['workspace']}), flush=True)
    return state


def run(stage, qa=None):
    qa = qa or (SandboxQA() if os.environ.get('QA_DRIVER_URL') else QA())
    out = Path(os.environ['QA_SCENARIO_OUT']); out.mkdir(parents=True, exist_ok=True)
    identity = qa.eval("import os\nassert os.environ.get('MIXAR_QA')=='1'\n"
                       "assert bpy.app.version[:2] == (5,3)\nresult=True")
    assert identity
    if stage == 'empty':
        qa.cmd('wait_login', timeout=60)
        qa.dismiss_splash()
        ensure_scenes_drawer(qa)
        assert qa.eval('result=len(drv.main_window().scene.mixie_chat_messages)') == 0
        qa.open_chat()
        draft(qa, ['UI audit — first line', 'Second line'])
        qa.wait("drv.main_window().scene.mixie_chat_input=='UI audit — first line\\nSecond line'", timeout=5)
        capture(qa, out, 'empty-focused', True)
    elif stage == 'populated':
        blur(qa)
        qa.eval("s=drv.main_window().scene\ns.mixie_chat_input=''\n"
                "assert len(s.mixie_chat_messages)==0\n"
                "m=s.mixie_chat_messages.add()\nm.sender='USER'\nm.message_type='USER'\n"
                "m.bubble_id='qa-ui-user'\nm.content=m.text='Show the scene controls.'\n"
                "m=s.mixie_chat_messages.add()\nm.sender='AGENT'\nm.message_type='AGENT'\n"
                "m.bubble_id='qa-ui-agent'\n"
                "m.content=m.text='## UI preview\\nThis is a local visual fixture.\\n\\n- **Lighting** controls\\n- Camera and object controls\\n\\nNo generation was submitted.'\n"
                "m.steps_summary='Checked scene controls'\nm.steps_collapsed=True\n"
                "step=m.step_items.add()\nstep.item_id='qa-ui-step'\nstep.kind='COMMAND'\n"
                "step.label='Inspect scene'\nstep.status='DONE'\n"
                "for w in bpy.context.window_manager.windows:\n"
                "    for a in w.screen.areas:a.tag_redraw()\nresult=True")
        qa.wait("bool(drv.find(prop='mixie_chat_input',area_type='AGENT_BUBBLE',region_type='TOOLS'))", timeout=10)
        draft(qa, ['Focused composer', 'Second line', 'Third line'])
        qa.wait("drv.main_window().scene.mixie_chat_input=='Focused composer\\nSecond line\\nThird line'", timeout=5)
        capture(qa, out, 'populated-focused', True)
    elif stage == 'idle':
        blur(qa)
        qa.wait("drv.main_window().scene.mixie_chat_input=='Focused composer\\nSecond line\\nThird line'", timeout=5)
        capture(qa, out, 'populated-idle', True)
        qa.click(area_type='AGENT_BUBBLE', surface='chat_steps_header')
        qa.wait("not next(m for m in drv.main_window().scene.mixie_chat_messages if m.bubble_id=='qa-ui-agent').steps_collapsed", timeout=5)
        capture(qa, out, 'expanded-steps', True)
    elif stage.startswith('tab:'):
        tab = stage.split(':', 1)[1]
        qa.step('open-' + tab, qa.click, area_type='AGENT_BUBBLE',
                region_type='HEADER', op='WM_OT_context_set_enum', text=TABS[tab])
        qa.wait(f"bpy.context.window_manager.mixar_bubble_tab=={tab!r}", timeout=10)
        capture(qa, out, 'tab-' + tab.lower(), True)
    elif stage == 'menus':
        qa.cmd('workspace', name='Layout')
        time.sleep(5)
        capture(qa, out, 'engine-settled')
        for name in ('File', 'Edit'):
            qa.click(area_type='TOPBAR', text=name, but_type='Pulldown')
            capture(qa, out, name.lower() + '-menu')
            qa.press('ESC')
    elif stage in ('zen', 'moodboard', 'engine', 'texturing'):
        if os.environ.get('QA_DRIVER_URL') or os.environ.get('QA_X_DISPLAY'):
            # This sandbox has no working resting-pill minimize path. Close
            # only its companion windows to inspect unobstructed main UI.
            qa.eval("from mixar.bootstrap import agent_bubble_module\n"
                    "agent_bubble_module.mark_user_closed()\n"
                    "for _ in range(4):\n"
                    "    w=next((w for w in bpy.context.window_manager.windows if "
                    "any(a.type=='AGENT_BUBBLE' for a in w.screen.areas)),None)\n"
                    "    if w is None:break\n"
                    "    with bpy.context.temp_override(window=w):bpy.ops.wm.window_close()\n"
                    "result=True")
        else:
            qa.cmd('dismiss_chat')
        if stage in ('zen', 'engine'):
            qa.cmd('set_mode', mode=stage)
            ensure_scenes_drawer(qa)
        elif stage == 'moodboard':
            if qa.eval('result=drv.moodboard_drawer_amount()') < .99:
                qa.click(surface='moodboard_drawer_grip')
                qa.wait('drv.moodboard_drawer_amount() >= .99', timeout=8)
        elif stage == 'texturing':
            qa.cmd('workspace', name='Texturing')
        capture(qa, out, stage)
    else:
        raise ValueError(stage)


if __name__ == '__main__':
    for selected in sys.argv[1:]:
        run(selected)
