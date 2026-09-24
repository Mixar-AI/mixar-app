#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Hold-Option/Alt at native carets/selections in chat, Moodboard and popup fields.

QA_HARNESS=/path/to/harness MIXAR_QA_PORT=4788 \
QA_SCENARIO_OUT=/tmp/voice-fields python3 tests/qa/voice_fields_e2e.py

Run against an isolated Dev profile. Capture and transcription are fixtures;
no microphone, cloud, generation or agent request is used. Input is native
mouse/key events. Inspect the PNGs along with the state assertions.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario
from mixie_open_type_send_e2e import open_pill

SCENE = 'drv.main_window().scene'
OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/voice-fields'))
CHAT = {'area_type': 'AGENT_BUBBLE', 'prop': 'mixie_chat_input'}
NODE = {'area_type': 'MIXIE', 'region_type': 'WINDOW', 'prop': 'prompt'}
TEXT = {'popup': True, 'prop': 'text'}
SHORT = {'popup': True, 'prop': 'short'}


def require(value, message):
    if not value:
        raise ScenarioFail(message)


def key(qa, field, name, **mods):
    qa.press(name, window=qa.find(**field)['widgets'][0]['window'], **mods)


def set_text(qa, field, text):
    qa.cmd('set_text', widget=field, text=text, enter=False)


def caret(qa, field, expected):
    edit = qa.find(**field)['widgets'][0].get('text_edit')
    size = len(expected.encode('utf-8'))
    require(edit and edit['cursor'] == size, f'Wrong native caret: {edit}, expected {size}')
    require(edit['selection'][0] == edit['selection'][1], f'Selection not cleared: {edit}')


def hold(qa, field):
    qa.eval(f"""
w=drv.find_one(**{field!r})['_win']
drv._sim(w,type='LEFT_ALT',value='PRESS',alt=True)
result=True
""")
    qa.wait("bpy.context.window_manager.mixie_chat_voice_status == 'Listening'", timeout=5)
    require(qa.eval("from mixar.modules.space_mixie_chat.core import voice; "
                    "result=bool(voice._session.field_token)"), 'Hold targeted chat fallback')


def release(qa, field, shift=False):
    qa.eval(f"""
w=drv.find_one(**{field!r})['_win']
drv._sim(w,type='LEFT_ALT',value='RELEASE',alt=False,shift={shift!r})
result=True
""")
    qa.wait("bpy.context.window_manager.mixie_chat_voice_status == 'Finishing'", timeout=5)


def finish(qa, text):
    qa.eval(f'import voice_focus_probe as v; v.finish({text!r}); result=True')
    qa.wait("not bpy.context.window_manager.mixie_chat_voice_field_token", timeout=5)


def snapshot(qa, name, field):
    time.sleep(.2)
    # Explicitly present both buffers: the minimized island can leave the main
    # window's screenshot backing store stale despite current widget/RNA state.
    qa.eval("bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=2); result=True")
    qa.cmd('snap', path=str(OUT / f'{name}.png'), target=field, margin=200)
    if name in {'node-listening', 'node-finishing'}:
        qa.cmd('snap', path=str(OUT / f'{name}-full.png'))


def focus(qa, field):
    qa.click(**field)
    # In a dialog the first click commits the previous non-interactive editor.
    if not qa.find(**field)['widgets'][0].get('text_edit'):
        qa.click(**field)
    require(qa.find(**field)['widgets'][0].get('text_edit'), 'Field did not enter editing')


def chat_case(qa):
    open_pill(qa)
    set_text(qa, CHAT, 'video vivid')
    qa.wait(f"{SCENE}.mixie_chat_input == 'video vivid'", timeout=5)
    require(not qa.eval('result=bpy.context.window_manager.mixie_chat_voice_listening'),
            'Quick v taps started recording')
    qa.eval("bpy.context.window_manager.clipboard='paste still works'; result=True")
    key(qa, CHAT, 'A', oskey=True)
    key(qa, CHAT, 'V', oskey=True)
    qa.wait(f"{SCENE}.mixie_chat_input == 'paste still works'", timeout=5)
    set_text(qa, CHAT, 'red cube')
    key(qa, CHAT, 'HOME')
    for _ in range(3):
        key(qa, CHAT, 'RIGHT_ARROW', shift=True)
    hold(qa, CHAT)
    snapshot(qa, 'chat-listening', CHAT)
    release(qa, CHAT, shift=True)
    finish(qa, 'blue')
    qa.wait(f"{SCENE}.mixie_chat_input == 'blue cube'", timeout=5)
    caret(qa, CHAT, 'blue')
    snapshot(qa, 'chat-selection-replaced', CHAT)
    key(qa, CHAT, 'Z', oskey=True)
    qa.wait(f"{SCENE}.mixie_chat_input == 'red cube'", timeout=5)
    require(not qa.eval(f'result={SCENE}.mixie_chat_is_busy'), 'Dictation auto-submitted')


def modifier_case(qa):
    set_text(qa, CHAT, 'voice')
    qa.eval(f"""
def chord():
    w=drv.find_one(**{CHAT!r})['_win']
    drv._sim(w,type='LEFT_ALT',value='PRESS',alt=True)
    yield .1
    drv._sim(w,type='E',value='PRESS',unicode='é',alt=True)
    drv._sim(w,type='E',value='RELEASE',alt=True)
    drv._sim(w,type='LEFT_ALT',value='RELEASE',alt=False)
    yield .1
    return True
result=chord()
""")
    qa.wait(f"{SCENE}.mixie_chat_input == 'voiceé'", timeout=5)
    require(not qa.eval('result=bpy.context.window_manager.mixie_chat_voice_listening'),
            'Option-letter chord started capture')
    hold(qa, CHAT)
    qa.eval(f"""
w=drv.find_one(**{CHAT!r})['_win']
drv._sim(w,type='E',value='PRESS',unicode='é',alt=True)
drv._sim(w,type='E',value='RELEASE',alt=True)
drv._sim(w,type='LEFT_ALT',value='RELEASE',alt=False)
result=True
""")
    qa.wait('not bpy.context.window_manager.mixie_chat_voice_listening', timeout=5)
    qa.wait(f"{SCENE}.mixie_chat_input == 'voiceéé'", timeout=5)
    qa.eval(f"""
def right_alt():
    w=drv.find_one(**{CHAT!r})['_win']
    drv._sim(w,type='RIGHT_ALT',value='PRESS',alt=True)
    yield .5
    assert not bpy.context.window_manager.mixie_chat_voice_listening
    drv._sim(w,type='RIGHT_ALT',value='RELEASE',alt=False)
    return True
result=right_alt()
""")
    snapshot(qa, 'normal-typing-and-option-chords', CHAT)


def moodboard_setup(qa):
    qa.eval(f"""
bpy.ops.mixar.bubble_minimise()
w=drv.main_window()
a=next(a for a in w.screen.areas if a.type in {'VIEW_3D', 'MIXIE'})
a.type='MIXIE'
s={SCENE}
s.mixie_moodboard_action_nodes.clear()
n=s.mixie_moodboard_action_nodes.add()
n.node_id='voice-qa-image'; n.action_type='IMAGE_GEN'
n.selected=True; n.show_prompt=True; n.prompt='red cube'; n.edit_mode=True
s.mixie_moodboard_active_node_id=n.node_id
r=next(r for r in a.regions if r.type=='WINDOW')
x,y=r.view2d.region_to_view(350,250)
x1,y1=r.view2d.region_to_view(950,680)
n.position_x=x; n.position_y=y; n.width=x1-x; n.height=y1-y
s.mixie_chat_input='Chat stays untouched'
a.tag_redraw()
result=True
""")
    qa.wait(f'bool(drv.find(**{NODE!r}))', timeout=5)


def node_case(qa):
    moodboard_setup(qa)
    set_text(qa, NODE, 'red  cube')
    key(qa, NODE, 'HOME')
    for _ in range(4):
        key(qa, NODE, 'RIGHT_ARROW')
    hold(qa, NODE)
    snapshot(qa, 'node-listening', NODE)
    release(qa, NODE)
    snapshot(qa, 'node-finishing', NODE)
    finish(qa, 'small')
    caret(qa, NODE, 'red small')
    qa.wait(f"{SCENE}.mixie_moodboard_action_nodes[0].prompt == 'red small cube'", timeout=5)
    snapshot(qa, 'node-caret-insertion', NODE)
    require(qa.eval(f"result={SCENE}.mixie_chat_input") == 'Chat stays untouched',
            'Node dictation changed chat')
    require(qa.eval(f"result={SCENE}.mixie_moodboard_action_nodes[0].state") == 'DRAFT',
            'Node dictation generated')
    hold(qa, NODE)
    key(qa, NODE, 'ESC')
    qa.eval(f"w=drv.find_one(**{NODE!r})['_win']; "
            "drv._sim(w,type='LEFT_ALT',value='RELEASE',alt=False); result=True")
    qa.wait('not bpy.context.window_manager.mixie_chat_voice_listening', timeout=5)
    require(qa.eval(f"result={SCENE}.mixie_moodboard_action_nodes[0].prompt") == 'red small cube',
            'Escape reverted the field')
    hold(qa, NODE)
    release(qa, NODE)
    # A normal edit during finalization cancels this target. A late result is inert.
    qa.cmd('type', window=qa.find(**NODE)['widgets'][0]['window'], text='!')
    qa.wait('not bpy.context.window_manager.mixie_chat_voice_listening', timeout=5)
    before = qa.eval(f'result={SCENE}.mixie_moodboard_action_nodes[0].prompt')
    qa.eval("import voice_focus_probe as v; v.latest.events.put({'type':'final','text':'LATE'}); result=True")
    time.sleep(.15)
    require(qa.eval(f'result={SCENE}.mixie_moodboard_action_nodes[0].prompt') == before,
            'Late result overwrote an edit')
    snapshot(qa, 'node-cancel-preserves-edits', NODE)


def popup_case(qa):
    qa.eval("bpy.ops.qa.voice_fields('INVOKE_DEFAULT'); result=True")
    qa.wait(f'bool(drv.find(**{TEXT!r}))', timeout=5)
    set_text(qa, TEXT, 'popup seed')
    key(qa, TEXT, 'A', oskey=True)
    hold(qa, TEXT)
    release(qa, TEXT)
    finish(qa, 'popup result')
    caret(qa, TEXT, 'popup result')
    snapshot(qa, 'popup-result', TEXT)
    focus(qa, SHORT)
    require(qa.eval('import voice_field_probe as f; result=f.active.text') == 'popup result',
            'Popup did not commit its own text')
    key(qa, SHORT, 'A', oskey=True)
    hold(qa, SHORT)
    release(qa, SHORT)
    finish(qa, 'This result cannot fit')
    require(qa.find(**SHORT)['widgets'][0]['text_edit']['selection'] == [0, 4],
            'Overflow changed the original selection')
    snapshot(qa, 'length-limit-preserves-selection', SHORT)
    focus(qa, TEXT)
    require(qa.eval('import voice_field_probe as f; result=f.active.short') == 'keep',
            'Overflow destroyed the selection')
    hold(qa, TEXT)
    release(qa, TEXT)
    key(qa, TEXT, 'TAB')
    qa.wait('not bpy.context.window_manager.mixie_chat_voice_listening', timeout=5)
    qa.eval("import voice_focus_probe as v; v.latest.events.put({'type':'final','text':'WRONG FIELD'}); result=True")
    time.sleep(.15)
    require(qa.eval('import voice_field_probe as f; result=f.active.short') == 'keep',
            'Transcript followed focus to another field')
    key(qa, SHORT, 'ESC')
    qa.press('ESC')


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    local = str(Path(__file__).resolve().parent)
    # A preceding diagnostic may have stopped capture without releasing its
    # simulated modifier. End that hold in every window before replaying.
    qa.eval("for w in bpy.context.window_manager.windows:\n"
            "    drv._sim(w,type='LEFT_ALT',value='RELEASE',alt=False)\n"
            "result=True")
    qa.eval(f"import sys; sys.path.insert(0,{local!r}); "
            "import voice_focus_probe as v; import voice_field_probe as f; "
            "v.install(); f.install(); "
            "bpy.context.window_manager.mixie_chat_is_logged_in=True; result=True")
    try:
        qa.step('chat_taps_selection_modifiers_undo', chat_case, qa)
        qa.step('option_chords_and_right_alt_stay_native', modifier_case, qa)
        qa.step('moodboard_caret_cancel_and_late_result', node_case, qa)
        qa.step('popup_selection_limits_and_focus_ownership', popup_case, qa)
        return {'backend_calls': 0, 'capture': 'fixture', 'snapshots': str(OUT)}
    finally:
        qa.eval('import voice_focus_probe as v; import voice_field_probe as f; '
                'v.uninstall(); f.uninstall(); result=True')


if __name__ == '__main__':
    run_scenario('voice_fields_e2e', run)
