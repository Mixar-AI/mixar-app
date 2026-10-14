#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""New File started from the focused island must keep the island usable.

Cmd+N with the island focused runs `wm.read_homefile` with the island as the
context window. On a dirty file the "Save changes before closing?" dialog
suppresses every floating dock (alpha 0, mouse ignored) while it is open, so a
dialog created INSIDE the island hid itself with the island. The fix hosts the
dialog in the main window. This replay invokes the operator exactly as the
keymap does (island context window, INVOKE_DEFAULT), asserts the dialog lives
in the main window and stays clickable, answers Don't Save, and asserts the
pill returns VISIBLE (native alpha 1, mouse accepted) on the new file.

Run in an isolated QA app (event simulation on). Export QA_HARNESS,
MIXAR_QA_PORT and QA_SCENARIO_OUT. No agent send, no credits.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario, wait_island

NATIVE_WINDOWS = r'''
import sys
result = None
if sys.platform == 'darwin':
    import ctypes as ct
    objc = ct.CDLL('/usr/lib/libobjc.A.dylib')
    objc.objc_getClass.restype = ct.c_void_p
    objc.sel_registerName.restype = ct.c_void_p
    sel = lambda n: objc.sel_registerName(n.encode())
    ptr = ct.CFUNCTYPE(ct.c_void_p, ct.c_void_p, ct.c_void_p)(('objc_msgSend', objc))
    at = ct.CFUNCTYPE(ct.c_void_p, ct.c_void_p, ct.c_void_p, ct.c_ulong)(('objc_msgSend', objc))
    count = ct.CFUNCTYPE(ct.c_ulong, ct.c_void_p, ct.c_void_p)(('objc_msgSend', objc))
    dbl = ct.CFUNCTYPE(ct.c_double, ct.c_void_p, ct.c_void_p)(('objc_msgSend', objc))
    boolean = ct.CFUNCTYPE(ct.c_bool, ct.c_void_p, ct.c_void_p)(('objc_msgSend', objc))
    utf8 = ct.CFUNCTYPE(ct.c_char_p, ct.c_void_p, ct.c_void_p)(('objc_msgSend', objc))
    app = ptr(objc.objc_getClass(b'NSApplication'), sel('sharedApplication'))
    wins = ptr(app, sel('windows'))
    out = []
    for i in range(count(wins, sel('count'))):
        w = at(wins, sel('objectAtIndex:'), i)
        ident = ptr(w, sel('identifier'))
        ident = (utf8(ident, sel('UTF8String')) or b'').decode() if ident else ''
        if ident != 'mixar_floating_dock':
            continue
        title = ptr(w, sel('title'))
        title = (utf8(title, sel('UTF8String')) or b'').decode() if title else ''
        out.append({'title': title,
                    'alpha': round(dbl(w, sel('alphaValue')), 2),
                    'visible': boolean(w, sel('isVisible')),
                    'ignores_mouse': boolean(w, sel('ignoresMouseEvents'))})
    result = out
'''

DIALOG_TITLE = 'Save changes before closing?'


def island_window_ptr(qa):
    state = wait_island(qa, 'island')
    return state['island_window']


def dirty_file(qa):
    qa.eval('''
bpy.context.preferences.view.use_save_prompt = True
bpy.ops.ed.undo_push(message='qa-before')
bpy.data.objects[0].location.x += 0.01
bpy.ops.ed.undo_push(message='qa-dirty')
result = bpy.data.is_dirty
''')
    assert qa.eval('result = bpy.data.is_dirty') is True


def invoke_new_file_from_island(qa, island_ptr):
    """The Window keymap runs Cmd+N in the focused island: same context."""
    status = qa.eval(f'''
wm = bpy.context.window_manager
isl = next(w for w in wm.windows if w.as_pointer() == {island_ptr})
with bpy.context.temp_override(window=isl):
    r = bpy.ops.wm.read_homefile('INVOKE_DEFAULT', app_template='')
result = sorted(r)
''')
    assert status == ['INTERFACE'], status


def dialog_windows(qa):
    found = qa.find(text=DIALOG_TITLE)
    return sorted({w['window'] for w in found['widgets']})


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/bubble-new-file-from-island'))
    out.mkdir(parents=True, exist_ok=True)
    qa.wait("hasattr(bpy.types.Scene, 'mixie_chat_input')", timeout=30)
    qa.dismiss_splash()
    qa.step('open_island', qa.open_chat)
    island_ptr = qa.step('island_window', island_window_ptr, qa)
    main_ptr = qa.eval('result = drv.main_window().as_pointer()')
    assert island_ptr != main_ptr

    qa.step('dirty_file', dirty_file, qa)
    qa.step('invoke_new_file_from_island', invoke_new_file_from_island, qa, island_ptr)

    hosts = qa.step('dialog_in_main_window', dialog_windows, qa)
    assert hosts == [main_ptr], f'dialog windows {hosts}, main {main_ptr}, island {island_ptr}'
    qa.snap(str(out / 'dialog-in-main-window.png'))

    # While the dialog is open the docks are suppressed: that is by design,
    # and harmless now that the dialog is not inside one of them.
    during = qa.eval(NATIVE_WINDOWS)
    if during is not None:
        assert during and all(w['alpha'] == 0.0 for w in during), during

    dont_save = qa.find(text="Don't Save")['widgets']
    assert dont_save and dont_save[0]['window'] == main_ptr, dont_save
    qa.step('click_dont_save', qa.click, text="Don't Save")

    qa.wait('not bpy.data.is_dirty', timeout=20)
    new_main = qa.eval('result = drv.main_window().as_pointer()')
    assert new_main != main_ptr, 'the file read replaces the window manager'
    state = qa.step('pill_returns', wait_island, qa, 'pill', 30)
    assert qa.find(surface='pill_cat')['widgets'], state

    after = qa.eval(NATIVE_WINDOWS)
    if after is not None:
        pill = [w for w in after if w['visible']]
        assert pill, after
        assert all(w['alpha'] == 1.0 and not w['ignores_mouse'] for w in pill), after
    assert not dialog_windows(qa)
    qa.snap(str(out / 'new-file-with-pill.png'))
    return {'dialog_hosts': hosts, 'native_after': after, 'main_after': new_main}


if __name__ == '__main__':
    run_scenario('bubble_new_file_from_island_e2e', run)
