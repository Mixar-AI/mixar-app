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

Keyboard (macOS): the suppressed island is only transparent, so it stayed the
OS key window — Esc / Return / typing never reached the dialog — and nothing
gave the keyboard back after Cancel. The first dock hold now keys the
dialog's host and the last release re-keys the island. Simulated events
bypass AppKit, so every key here is injected into the wmWindow whose NSWindow
is `[NSApp keyWindow]` — where AppKit would deliver a real keystroke. The run
starts with the composer focused (the island key), opens the dialog, presses
Esc where the keyboard is and asserts the dialog answered (file still dirty),
then types a character and asserts it landed in the island composer with the
scene untouched (no viewport shortcut). Windows hides the docks instead and
is not covered by this replay.

Run in an isolated QA app (event simulation on). Export QA_HARNESS,
MIXAR_QA_PORT and QA_SCENARIO_OUT. No agent send, no credits.
"""
import os
from pathlib import Path
import sys
import time

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

# `[NSApp keyWindow]`: whether it is a floating dock, and its content size in
# points and pixels (one of them matches `Window.width/height`, which carries
# the wmWindow's size in GHOST units).
#
# ACTIVATE_APP: simulated clicks never activate the app, and while another
# app is frontmost there is no key window at all. `NSRunningApplication
# activateWithOptions:` (all windows | ignoring other apps) still brings it
# forward where `activateIgnoringOtherApps:` is ignored by cooperative
# activation.
NATIVE_KEY_WINDOW = r'''
import sys
result = None
if sys.platform == 'darwin':
    import ctypes as ct
    objc = ct.CDLL('/usr/lib/libobjc.A.dylib')
    objc.objc_getClass.restype = ct.c_void_p
    objc.sel_registerName.restype = ct.c_void_p
    sel = lambda n: objc.sel_registerName(n.encode())

    class Rect(ct.Structure):
        _fields_ = [('x', ct.c_double), ('y', ct.c_double),
                    ('w', ct.c_double), ('h', ct.c_double)]

    ptr = ct.CFUNCTYPE(ct.c_void_p, ct.c_void_p, ct.c_void_p)(('objc_msgSend', objc))
    dbl = ct.CFUNCTYPE(ct.c_double, ct.c_void_p, ct.c_void_p)(('objc_msgSend', objc))
    boolean = ct.CFUNCTYPE(ct.c_bool, ct.c_void_p, ct.c_void_p)(('objc_msgSend', objc))
    rect = ct.CFUNCTYPE(Rect, ct.c_void_p, ct.c_void_p)(('objc_msgSend', objc))
    utf8 = ct.CFUNCTYPE(ct.c_char_p, ct.c_void_p, ct.c_void_p)(('objc_msgSend', objc))
    app = ptr(objc.objc_getClass(b'NSApplication'), sel('sharedApplication'))
    key = ptr(app, sel('keyWindow'))
    result = {'active': boolean(app, sel('isActive')), 'dock': None, 'size': None}
    if key:
        ident = ptr(key, sel('identifier'))
        ident = (utf8(ident, sel('UTF8String')) or b'').decode() if ident else ''
        frame = rect(ptr(key, sel('contentView')), sel('frame'))
        scale = dbl(key, sel('backingScaleFactor'))
        result['dock'] = ident == 'mixar_floating_dock'
        result['size'] = [[round(frame.w), round(frame.h)],
                          [round(frame.w * scale), round(frame.h * scale)]]
'''

ACTIVATE_APP = r'''
import ctypes as ct
objc = ct.CDLL('/usr/lib/libobjc.A.dylib')
objc.objc_getClass.restype = ct.c_void_p
objc.sel_registerName.restype = ct.c_void_p
sel = lambda n: objc.sel_registerName(n.encode())
ptr = ct.CFUNCTYPE(ct.c_void_p, ct.c_void_p, ct.c_void_p)(('objc_msgSend', objc))
activate = ct.CFUNCTYPE(ct.c_bool, ct.c_void_p, ct.c_void_p, ct.c_ulong)(('objc_msgSend', objc))
current = ptr(objc.objc_getClass(b'NSRunningApplication'), sel('currentApplication'))
result = activate(current, sel('activateWithOptions:'), 3)
'''

DIALOG_TITLE = 'Save changes before closing?'


def key_window_ptr(qa):
    """The wmWindow a real keystroke would reach (None: no key window)."""
    native = qa.eval(NATIVE_KEY_WINDOW)
    if not native or native['size'] is None:
        return None
    sizes = qa.eval('result = [(w.as_pointer(), w.width, w.height, '
                    "any(a.type == 'AGENT_BUBBLE' for a in w.screen.areas)) "
                    'for w in bpy.context.window_manager.windows]')
    hits = [ptr for ptr, width, height, bubble in sizes
            if bubble == native['dock'] and any(
                abs(width - w) <= 2 and abs(height - h) <= 2 for w, h in native['size'])]
    assert len(hits) <= 1, (native, sizes)
    return hits[0] if hits else None


def wait_key_window(qa, want, timeout=5.0):
    deadline = time.monotonic() + timeout
    while True:
        got = key_window_ptr(qa)
        if got == want or time.monotonic() > deadline:
            return got
        time.sleep(0.1)


def composer_has_keyboard(qa, island_ptr):
    """Opening the island keys it and focuses the composer once the app is
    active (a real click on the pill activates it first)."""
    assert qa.eval(ACTIVATE_APP), 'the app could not be activated'
    got = wait_key_window(qa, island_ptr)
    assert got == island_ptr, f'key window {got}, island {island_ptr}'


def scene_snapshot(qa):
    return qa.eval('''
win = drv.main_window()
result = {'objects': sorted(o.name for o in bpy.data.objects),
          'mode': bpy.context.mode,
          'selected': sorted(o.name for o in win.view_layer.objects if o.select_get()),
          'composer': win.scene.mixie_chat_input}
''')


def press_where_the_keyboard_is(qa, key, char=None):
    """Inject a key into the OS key window's wmWindow, the pointer over the
    open dialog when that window holds it (else where it was)."""
    ptr = key_window_ptr(qa)
    assert ptr is not None, 'no key window'
    over = [w for w in qa.find(text=DIALOG_TITLE)['widgets'] if w['window'] == ptr]
    qa.eval(f'''
win = next(w for w in bpy.context.window_manager.windows if w.as_pointer() == {ptr})
over = {over[0]['rect'] if over else None!r}
if over:
    drv.move_to(win, (over[0] + over[2]) // 2, (over[1] + over[3]) // 2)
if {char!r}:
    drv.type_char(win, {char!r})
else:
    drv.press(win, {key!r})
result = True
''')
    return ptr


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
    keyboard = None
    if qa.eval(NATIVE_KEY_WINDOW) is not None:
        keyboard = qa.step('esc_cancels_then_island_types', cancel_with_the_keyboard,
                           qa, island_ptr, main_ptr, out)

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
    return {'dialog_hosts': hosts, 'native_after': after, 'main_after': new_main,
            'keyboard': keyboard}


def cancel_with_the_keyboard(qa, island_ptr, main_ptr, out):
    composer_has_keyboard(qa, island_ptr)
    before = scene_snapshot(qa)
    invoke_new_file_from_island(qa, island_ptr)
    assert dialog_windows(qa) == [main_ptr]

    # The dialog has the keyboard: the main window it lives in is key.
    got = wait_key_window(qa, main_ptr)
    assert got == main_ptr, f'dialog open, key window {got} (main {main_ptr}, island {island_ptr})'
    qa.snap(str(out / 'dialog-has-keyboard.png'))

    # Esc where a real Esc goes answers the dialog (Cancel: still dirty).
    press_where_the_keyboard_is(qa, 'ESC')
    deadline = time.monotonic() + 5
    while dialog_windows(qa):
        assert time.monotonic() < deadline, 'Esc did not reach the dialog'
        time.sleep(0.1)
    assert qa.eval('result = bpy.data.is_dirty') is True

    # Cancel hands the keyboard back to the island composer.
    got = wait_key_window(qa, island_ptr)
    assert got == island_ptr, f'after Cancel, key window {got} (island {island_ptr})'
    typed = press_where_the_keyboard_is(qa, None, char='x')
    assert typed == island_ptr, typed
    want = before['composer'] + 'x'
    qa.wait(f"drv.main_window().scene.mixie_chat_input == {want!r}", timeout=5)
    after = scene_snapshot(qa)
    assert {k: after[k] for k in ('objects', 'mode', 'selected')} == {
        k: before[k] for k in ('objects', 'mode', 'selected')}, (before, after)
    qa.eval(f"drv.main_window().scene.mixie_chat_input = {before['composer']!r}\nresult = True")
    return {'typed_into': typed, 'composer': after['composer']}


if __name__ == '__main__':
    run_scenario('bubble_new_file_from_island_e2e', run)
