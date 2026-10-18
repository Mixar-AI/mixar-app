# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Linux pill -> real typing, field clicks, and outside-click focus handoff.

QA_HARNESS=/path/to/mixar-qa-harness python tests/qa/linux_bubble_focus.py
X11 uses XTest without forcibly activating the bubble. Wayland uses injected
WM events (MIXAR_QA_WAYLAND=1). No backend calls are made by this scenario.
MIXAR_QA_BASELINE=1 records failures before the fix without aborting early.
"""
import ctypes as ct
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

repo = Path(__file__).resolve().parents[2]
harness = Path(os.environ['QA_HARNESS']).resolve()
sys.path[:0] = [str(repo / 'tests/qa/sticky_ui'), str(harness / 'scenarios')]
from qa_launch import start
from lib import QA

wayland = os.environ.get('MIXAR_QA_WAYLAND') == '1'
baseline = os.environ.get('MIXAR_QA_BASELINE') == '1'
port = 4795 if wayland else 4794
app = start(harness, repo / 'build/Dev/bin', port, Path('/tmp/mixar-linux-focus'),
            mixed=not wayland, extra_env={'BROWSER': '/bin/true', **({} if wayland else {'WAYLAND_DISPLAY': ''})})
qa = QA(port=port)
field = {'area_type': 'AGENT_BUBBLE', 'prop': 'mixie_chat_input'}
checks = []
x = ct.CDLL('libX11.so.6')
xt = ct.CDLL('libXtst.so.6')
x.XOpenDisplay.argtypes = [ct.c_char_p]
x.XOpenDisplay.restype = ct.c_void_p
x.XCloseDisplay.argtypes = [ct.c_void_p]
x.XFlush.argtypes = [ct.c_void_p]
x.XKeysymToKeycode.argtypes = [ct.c_void_p, ct.c_ulong]
x.XKeysymToKeycode.restype = ct.c_uint
x.XGetInputFocus.argtypes = [ct.c_void_p, ct.POINTER(ct.c_ulong), ct.POINTER(ct.c_int)]
xt.XTestFakeMotionEvent.argtypes = [ct.c_void_p, ct.c_int, ct.c_int, ct.c_int, ct.c_ulong]
xt.XTestFakeButtonEvent.argtypes = [ct.c_void_p, ct.c_uint, ct.c_int, ct.c_ulong]
xt.XTestFakeKeyEvent.argtypes = [ct.c_void_p, ct.c_uint, ct.c_int, ct.c_ulong]
display = None if wayland else x.XOpenDisplay(None)
assert wayland or display


class XImage(ct.Structure):
    _fields_ = [('width', ct.c_int), ('height', ct.c_int),
                ('xoffset', ct.c_int), ('format', ct.c_int),
                ('data', ct.c_void_p), ('byte_order', ct.c_int),
                ('bitmap_unit', ct.c_int), ('bitmap_bit_order', ct.c_int),
                ('bitmap_pad', ct.c_int), ('depth', ct.c_int),
                ('bytes_per_line', ct.c_int), ('bits_per_pixel', ct.c_int)]


def capture(name):
    if wayland:
        return  # Blender's framebuffer screenshot excludes the final glass pass.
    from PIL import Image, ImageStat
    x.XGetImage.argtypes = [ct.c_void_p, ct.c_ulong, ct.c_int, ct.c_int,
                           ct.c_uint, ct.c_uint, ct.c_ulong, ct.c_int]
    x.XGetImage.restype = ct.POINTER(XImage)
    x.XDestroyImage.argtypes = [ct.POINTER(XImage)]
    g = geometry(bubble_wid)
    raw = x.XGetImage(display, int(bubble_wid, 16), 0, 0,
                      g['width'], g['height'], ct.c_ulong(-1), 2)
    assert raw
    try:
        info = raw.contents
        assert info.bits_per_pixel == 32 and info.byte_order == 0
        pixels = ct.string_at(info.data, info.bytes_per_line * g['height'])
        image = Image.frombytes('RGBA', (g['width'], g['height']), pixels,
                                'raw', 'BGRA', info.bytes_per_line)
        assert max(ImageStat.Stat(image.convert('RGB')).stddev) > 5
        image.save(app.out / f'{name}.png')
    finally:
        x.XDestroyImage(raw)


def geometry(wid):
    text = subprocess.check_output(['xwininfo', '-id', wid], text=True)
    return {k: int(re.search(p, text).group(1)) for k, p in {
        'x': r'Absolute upper-left X:\s+(-?\d+)', 'y': r'Absolute upper-left Y:\s+(-?\d+)',
        'width': r'Width:\s+(\d+)', 'height': r'Height:\s+(\d+)'
    }.items()}


def move(wid, point):
    g = geometry(wid)
    xt.XTestFakeMotionEvent(display, -1, g['x'] + point[0],
                           g['y'] + g['height'] - 1 - point[1], 0)
    x.XFlush(display)
    time.sleep(.15)


def click(query):
    if query.get('surface') == 'pill_cat':
        # Linux's resting capsule is the whole native window, with a
        # window-level click/drag gesture rather than a uiBut target.
        hit = qa.eval("w=next(w for w in bpy.context.window_manager.windows "
                      "if any(a.type=='AGENT_BUBBLE' for a in w.screen.areas)); "
                      "result={'window':w.as_pointer(),'center':[w.width//2,w.height//2]}")
        if wayland:
            qa.cmd('click_xy', window=hit['window'], x=hit['center'][0], y=hit['center'][1])
            return
    elif wayland:
        qa.click(**query)
        return
    else:
        hit = qa.find(**query)['widgets'][0]
    move(bubble_wid, hit['center'])
    for down in (1, 0):
        xt.XTestFakeButtonEvent(display, 1, down, 0)
        x.XFlush(display)
        time.sleep(.1)


def type_text(text):
    if wayland:
        qa.cmd('type', window=qa.find(**field)['widgets'][0]['window'], text=text)
    else:
        for char in text:
            code = x.XKeysymToKeycode(display, ord(char))
            assert code
            for down in (1, 0):
                xt.XTestFakeKeyEvent(display, code, down, 0)
            x.XFlush(display)
            time.sleep(.05)
    time.sleep(.3)


def draft():
    return qa.eval('result=drv.main_window().scene.mixie_chat_input')


def check(name, expected):
    actual = draft()
    focused = None
    if not wayland:
        focus, revert = ct.c_ulong(), ct.c_int()
        x.XGetInputFocus(display, ct.byref(focus), ct.byref(revert))
        focused = focus.value == int(bubble_wid, 16)
    result = {'name': name, 'expected': expected, 'actual': actual, 'native_focus': focused,
              'passed': actual == expected and focused is not False}
    checks.append(result)
    print(json.dumps(result), flush=True)
    if not baseline:
        assert result['passed'], result


def settle(opened):
    qa.wait("any((w.width>=560) == " + repr(opened) +
            " for w in bpy.context.window_manager.windows if any(a.type=='AGENT_BUBBLE' for a in w.screen.areas))", timeout=8)
    if wayland:
        qa.wait('not bpy.ops.mixar.bubble_hover_tick.poll()', timeout=10)
    time.sleep(.3)


def host_pointer(press=False):
    point = qa.eval("w=drv.main_window(); r=next(r for a in w.screen.areas if a.type=='VIEW_3D' "
                    "for r in a.regions if r.type=='WINDOW'); result=[r.x+150,r.y+r.height-120]")
    if wayland:
        kind = 'LEFTMOUSE' if press else 'MOUSEMOVE'
        qa.eval(f"w=drv.main_window(); w.event_simulate(type={kind!r},value={'PRESS' if press else 'NOTHING'!r},x={point[0]},y={point[1]})")
        if press:
            qa.eval(f"w=drv.main_window(); w.event_simulate(type='LEFTMOUSE',value='RELEASE',x={point[0]},y={point[1]})")
    else:
        move(main_wid, point)
        if press:
            for down in (1, 0):
                xt.XTestFakeButtonEvent(display, 1, down, 0)
                x.XFlush(display)
                time.sleep(.1)
    time.sleep(.3)


try:
    time.sleep(5)
    qa.eval("from mixar.modules.onboarding.core import persistence; "
            "assert persistence.has_device_seen_onboarding()")
    qa.eval("w=drv.main_window()\nwith bpy.context.temp_override(window=w): bpy.ops.mixar.agent_bubble_show_window()")
    qa.eval("bpy.ops.mixar.bubble_minimise()")
    settle(False)
    qa.eval("s=drv.main_window().scene; s.mixie_chat_messages.clear(); s.mixie_chat_input=''")
    if not wayland:
        clients = re.findall(r'0x[0-9a-f]+', subprocess.check_output(['xprop', '-root', '_NET_CLIENT_LIST'], text=True))
        owned = [w for w in clients if re.search(r'= ' + str(app.pid) + r'\b',
                 subprocess.check_output(['xprop', '-id', w, '_NET_WM_PID'], text=True))]
        bubble_wid = min(owned, key=lambda w: geometry(w)['width'])
        main_wid = max(owned, key=lambda w: geometry(w)['width'])
    click({'surface': 'pill_cat'})
    settle(True)
    type_text('alpha')
    check('type_after_pill_without_field_click', 'alpha')
    capture('empty-typed')
    # Also diagnose a user clicking the input explicitly; do not force OS focus.
    click(field)
    before = draft()
    type_text(' manual')
    check('click_field_then_type', before + ' manual')
    # The caret can be placed in the middle by the click: preserve the actual
    # user draft as the next scenario's starting point.
    before = draft()
    host_pointer()
    type_text(' away')
    check('typing_after_pointer_leaves', before + ' away')
    before = draft()
    host_pointer(press=True)
    settle(False)
    click({'surface': 'pill_cat'})
    settle(True)
    type_text(' reopened')
    check('typing_after_outside_click_and_restore', before + ' reopened')
    host_pointer(press=True)
    settle(False)
    qa.eval("s=drv.main_window().scene; m=s.mixie_chat_messages.add(); "
            "m.bubble_id='focus-fixture'; m.sender='AGENT'; m.message_type='AGENT'; "
            "m.content=m.text='Continue typing after reopening the conversation.'")
    click({'surface': 'pill_cat'})
    settle(True)
    before = draft()
    type_text(' conversation')
    check('typing_in_conversation_footer', before + ' conversation')
    capture('typed')
    if not wayland:
        # A selection started inside the field must keep receiving motion
        # when it crosses the resize border; it must not resize the window.
        target = qa.find(**field)['widgets'][0]
        start = target['rect'][2] - 20
        y = target['center'][1]
        size_before = geometry(bubble_wid)
        move(bubble_wid, (start, y))
        xt.XTestFakeButtonEvent(display, 1, 1, 0)
        x.XFlush(display)
        time.sleep(.1)
        try:
            for i in range(1, 6):
                move(bubble_wid, (round(start + (5-start)*i/5), y))
        finally:
            xt.XTestFakeButtonEvent(display, 1, 0, 0)
            x.XFlush(display)
        type_text('replacement')
        check('selection_can_cross_resize_border', 'replacement')
        assert geometry(bubble_wid) == size_before
        capture('selection-replaced')
finally:
    (app.out / 'verdict.json').write_text(json.dumps({'baseline': baseline, 'wayland': wayland,
                                                   'checks': checks, 'out': str(app.out)}, indent=2) + '\n')
    print(app.out, flush=True)
    if display:
        x.XCloseDisplay(display)
    app.stop(harness)
