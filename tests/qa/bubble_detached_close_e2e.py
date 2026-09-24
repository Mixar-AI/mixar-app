#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Assert AppKit key ownership is retired BEFORE disposing a detached island.

Run in an isolated offline macOS QA app. Export QA_HARNESS, MIXAR_QA_PORT and
QA_SCENARIO_OUT. The real compiled close helper runs on the focused Cocoa
window; only its parent relationship is changed by the fixture. No agent send.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from bubble_checkpoint_crash_e2e import capture
from mixie_open_type_send_e2e import SCENE, draft_is, open_pill, type_draft

PREPARE = r'''
import ctypes as ct
objc = ct.CDLL('/usr/lib/libobjc.A.dylib')
objc.objc_getClass.argtypes = [ct.c_char_p]
objc.objc_getClass.restype = ct.c_void_p
objc.sel_registerName.argtypes = [ct.c_char_p]
objc.sel_registerName.restype = ct.c_void_p
ptr = ct.CFUNCTYPE(ct.c_void_p, ct.c_void_p, ct.c_void_p)(('objc_msgSend', objc))
boolean = ct.CFUNCTYPE(ct.c_bool, ct.c_void_p, ct.c_void_p)(('objc_msgSend', objc))
action = ct.CFUNCTYPE(None, ct.c_void_p, ct.c_void_p, ct.c_void_p)(('objc_msgSend', objc))
responds = ct.CFUNCTYPE(ct.c_bool, ct.c_void_p, ct.c_void_p, ct.c_void_p)(('objc_msgSend', objc))
sel = lambda name: objc.sel_registerName(name.encode())
app = ptr(objc.objc_getClass(b'NSApplication'), sel('sharedApplication'))
window = ptr(app, sel('keyWindow'))
assert window, 'No native key window'
title = ptr(window, sel('title'))
utf8 = ct.CFUNCTYPE(ct.c_char_p, ct.c_void_p, ct.c_void_p)(('objc_msgSend', objc))
assert utf8(title, sel('UTF8String')) == b'Agent Bubble', 'Focus must be on the island'
view = ptr(window, sel('firstResponder'))
assert responds(view, sel('respondsToSelector:'), sel('windowCocoa')), 'Expected GHOST text client'
ghost = ptr(view, sel('windowCocoa'))
assert ghost
parent = ptr(window, sel('parentWindow'))
if parent:
    action(parent, sel('removeChildWindow:'), window)
assert not ptr(window, sel('parentWindow'))
assert ptr(app, sel('keyWindow')) == window, 'Detachment must preserve keyboard focus'
assert boolean(window, sel('isKeyWindow'))
prepare = ct.CDLL(None).Mixar_WindowPrepareForClose
prepare.argtypes = [ct.c_void_p]
prepare.restype = None
prepare(ghost)
result = {'key_status': boolean(window, sel('isKeyWindow')),
          'app_key_matches': ptr(app, sel('keyWindow')) == window,
          'visible': boolean(window, sel('isVisible'))}
'''


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/bubble-detached-close'))
    out.mkdir(parents=True, exist_ok=True)
    qa.wait("hasattr(bpy.types.Scene, 'mixie_chat_input')", timeout=30)
    qa.eval("import os, sys; assert os.environ.get('MIXAR_QA') == '1'; "
            "assert sys.platform == 'darwin'; "
            'from mixar.modules.space_mixie_chat.core.session import get_session_manager; '
            f'get_session_manager().set_connected({SCENE}); '
            'bpy.context.window_manager.mixie_chat_is_logged_in=True; '
            "bpy.context.window_manager.mixar_bubble_tab='AGENT'; result=True")
    qa.dismiss_splash()
    open_pill(qa)
    before = qa.eval(f'result={SCENE}.mixie_chat_input')
    type_draft(qa, 'Detached close draft')
    draft_is(qa, before + 'Detached close draft')
    capture(qa, out, 'focused-before-detach')
    try:
        state = qa.step('native_prepare_detached_key_window', qa.eval, PREPARE)
        assert state == {'key_status': False, 'app_key_matches': False, 'visible': False}, state
    finally:
        # Disposal follows the explicit prepare even when an old build fails
        # the ownership assertion; no disposed Cocoa pointer is used again.
        qa.eval('result=str(bpy.ops.mixar.agent_bubble_purge_windows())')
    qa.eval('result=str(bpy.ops.mixar.agent_bubble_open_window())')
    open_pill(qa)
    type_draft(qa, ' reopened')
    draft_is(qa, before + 'Detached close draft reopened')
    capture(qa, out, 'reopened-and-editable')
    return {'native_state_before_disposal': state, 'typing_after_reopen': True,
            'evidence': str(out)}


if __name__ == '__main__':
    run_scenario('bubble_detached_close_e2e', run)
