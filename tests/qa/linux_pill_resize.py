# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Native Linux pill/restore/resize and transcript regression, without backend requests.

QA_HARNESS=/path/to/mixar-qa-harness python tests/qa/linux_pill_resize.py
Uses a disposable app; preserve the runner's WAYLAND_DISPLAY for XTest.
"""
import ctypes
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
port = 4797 if wayland else 4796
root = '/tmp/mixar-linux-pill-wayland' if wayland else '/tmp/mixar-linux-pill'
app = start(harness, repo / 'build/Dev/bin', port, Path(root),
            mixed=True, extra_env={} if wayland else {'WAYLAND_DISPLAY': ''})
qa = QA(port=port)
x = ctypes.CDLL('libX11.so.6')
x.XOpenDisplay.argtypes = [ctypes.c_char_p]
x.XOpenDisplay.restype = ctypes.c_void_p
x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
x.XDefaultRootWindow.restype = ctypes.c_ulong
x.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
x.XInternAtom.restype = ctypes.c_ulong
x.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long, ctypes.c_void_p]
x.XFlush.argtypes = [ctypes.c_void_p]
x.XCloseDisplay.argtypes = [ctypes.c_void_p]
xt = ctypes.CDLL('libXtst.so.6')
xt.XTestFakeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
xt.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
xt.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
x.XKeysymToKeycode.restype = ctypes.c_uint
display = None if wayland else x.XOpenDisplay(None)
assert wayland or display

class XImage(ctypes.Structure):
    _fields_ = [('width', ctypes.c_int), ('height', ctypes.c_int),
                ('xoffset', ctypes.c_int), ('format', ctypes.c_int),
                ('data', ctypes.c_void_p), ('byte_order', ctypes.c_int),
                ('bitmap_unit', ctypes.c_int), ('bitmap_bit_order', ctypes.c_int),
                ('bitmap_pad', ctypes.c_int), ('depth', ctypes.c_int),
                ('bytes_per_line', ctypes.c_int), ('bits_per_pixel', ctypes.c_int)]

x.XGetImage.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
                       ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong, ctypes.c_int]
x.XGetImage.restype = ctypes.POINTER(XImage)
x.XDestroyImage.argtypes = [ctypes.POINTER(XImage)]

class ClientMessage(ctypes.Structure):
    _fields_ = [('type', ctypes.c_int), ('serial', ctypes.c_ulong),
                ('send_event', ctypes.c_int), ('display', ctypes.c_void_p),
                ('window', ctypes.c_ulong), ('message_type', ctypes.c_ulong),
                ('format', ctypes.c_int), ('data', ctypes.c_long * 5)]

def activate(wid):
    event = ClientMessage(type=33, display=display, window=int(wid, 16),
                          message_type=x.XInternAtom(display, b'_NET_ACTIVE_WINDOW', 0),
                          format=32, data=(ctypes.c_long * 5)(2, 0, 0, 0, 0))
    x.XSendEvent(display, x.XDefaultRootWindow(display), 0,
                 (1 << 19) | (1 << 20), ctypes.byref(event))
    x.XFlush(display)
    time.sleep(1)

def geometry(wid):
    info = subprocess.check_output(['xwininfo', '-id', wid], text=True)
    return {key: int(re.search(pattern, info).group(1)) for key, pattern in {
        'x': r'Absolute upper-left X:\s+(-?\d+)',
        'y': r'Absolute upper-left Y:\s+(-?\d+)',
        'width': r'Width:\s+(\d+)', 'height': r'Height:\s+(\d+)'
    }.items()}

def pointer(px, py):
    xt.XTestFakeMotionEvent(display, -1, px, py, 0)
    x.XFlush(display)

def button(down):
    xt.XTestFakeButtonEvent(display, 1, int(down), 0)
    x.XFlush(display)

def drag(wid, dx, dy):
    activate(wid)
    g = geometry(wid)
    px, py = g['x'] + g['width'] - 7, g['y'] + g['height'] - 7
    pointer(px, py)
    time.sleep(.2)
    button(True)
    try:
        time.sleep(1)
        for i in range(1, 6):
            pointer(px + dx * i // 5, py + dy * i // 5)
            time.sleep(.3)
    finally:
        button(False)
    time.sleep(.5)
    return geometry(wid)

def state():
    return qa.eval("w=next(w for w in bpy.context.window_manager.windows "
                   "if any(a.type=='AGENT_BUBBLE' for a in w.screen.areas))\n"
                   "result={'width':w.width,'height':w.height,"
                   "'messages':[(m.bubble_id,m.text) for m in w.scene.mixie_chat_messages],"
                   "'draft':w.scene.mixie_chat_input,"
                   "'regions':[(r.type,r.width,r.height) for a in w.screen.areas for r in a.regions]}")

def capture(name):
    path = app.out / f'{name}.png'
    if not wayland:
        from PIL import Image, ImageStat
        activate(wid)
        g = geometry(wid)
        raw = x.XGetImage(display, int(wid, 16), 0, 0, g['width'], g['height'], ctypes.c_ulong(-1), 2)
        assert raw
        try:
            info = raw.contents
            assert info.bits_per_pixel == 32 and info.byte_order == 0
            data = ctypes.string_at(info.data, info.bytes_per_line * g['height'])
            image = Image.frombytes('RGBA', (g['width'], g['height']), data,
                                    'raw', 'BGRA', info.bytes_per_line)
            assert max(ImageStat.Stat(image.convert('RGB')).stddev) > 5, name
            for point in [(0, 0), (g['width']-1, 0), (0, g['height']-1),
                          (g['width']-1, g['height']-1)]:
                assert image.getpixel(point)[3] == 0, (name, point, image.getpixel(point))
            image.save(path)
        finally:
            x.XDestroyImage(raw)
    else:
        qa.eval("w=next(w for w in bpy.context.window_manager.windows "
                "if any(a.type=='AGENT_BUBBLE' for a in w.screen.areas))\n"
                f"with bpy.context.temp_override(window=w): bpy.ops.screen.screenshot(filepath={str(path)!r})")

def op(name, **kwargs):
    return qa.eval("w=next(w for w in bpy.context.window_manager.windows "
                   "if any(a.type=='AGENT_BUBBLE' for a in w.screen.areas))\n"
                   f"with bpy.context.temp_override(window=w): result=str(bpy.ops.mixar.{name}(**{kwargs!r}))")

try:
    # File-load recovery recreates an initially restored overlay after startup.
    # Let it finish before identifying the window used by this scenario.
    time.sleep(5)
    qa.eval("w=drv.main_window()\nwith bpy.context.temp_override(window=w): bpy.ops.mixar.agent_bubble_show_window()")
    qa.wait("any(a.type=='AGENT_BUBBLE' for w in bpy.context.window_manager.windows for a in w.screen.areas)", timeout=30)
    # Autoshow can now be pill-only. Restore before creating the local fixture.
    op('bubble_restore')
    time.sleep(2)
    if not wayland:
        tree = subprocess.check_output(['xwininfo', '-root', '-tree'], text=True)
        candidates = re.findall(r'(0x[0-9a-f]+) "Agent Bubble":', tree)
        wid = next(w for w in candidates if re.search(
            r'= ' + str(app.pid) + r'\b', subprocess.check_output(['xprop', '-id', w, '_NET_WM_PID'], text=True)))
    qa.eval("scene=drv.main_window().scene\n"
            "assert len(scene.mixie_chat_messages)==0\n"
            "m=scene.mixie_chat_messages.add()\nm.bubble_id='linux-pill-fixture'\n"
            "m.sender='AGENT'\nm.message_type='AGENT'\n"
            "m.content=m.text='Linux conversation remains visible after minimizing, restoring, and resizing.'\n"
            "scene.mixie_chat_input='Keep this unsent draft'\n"
            "for w in bpy.context.window_manager.windows:\n"
            " for a in w.screen.areas: a.tag_redraw()")
    qa.wait("any(w.height>=407 for w in bpy.context.window_manager.windows if any(a.type=='AGENT_BUBBLE' for a in w.screen.areas))", timeout=10)
    time.sleep(2)
    if os.environ.get('MIXAR_QA_TRACE'):
        qa.eval('''import mixar.modules.agent_bubble.ui.operators.bubble_header_drag_op as dragmod
old_edges = dragmod._linux_resize_edges
def traced_edges(context,event):
    result=old_edges(context,event)
    print('RESIZE_HIT',event.type,event.mouse_x,event.mouse_y,result,flush=True)
    return result
dragmod._linux_resize_edges=traced_edges
''')
    initial = state()
    assert max(h for kind, _, h in initial['regions'] if kind == 'WINDOW') > 100, initial
    capture('conversation')
    if wayland:
        op('bubble_set_size', width=initial['width'] + 100, height=initial['height'] + 80)
        time.sleep(1)
        enlarged = state()
    else:
        enlarged = drag(wid, 100, 80)
    assert enlarged['width'] >= initial['width'] + 70, (initial, enlarged)
    assert enlarged['height'] >= initial['height'] + 50, (initial, enlarged)
    capture('resized')
    cycles = []
    for index in range(3):
        if wayland:
            op('bubble_minimise')
        else:
            activate(wid)
            code = x.XKeysymToKeycode(display, 0xff1b)  # Escape
            xt.XTestFakeKeyEvent(display, code, 1, 0)
            xt.XTestFakeKeyEvent(display, code, 0, 0)
            x.XFlush(display)
        qa.wait("any(w.width<400 and w.height<80 for w in bpy.context.window_manager.windows if any(a.type=='AGENT_BUBBLE' for a in w.screen.areas))", timeout=5)
        pill = state()
        print('PILL_STATE', index, json.dumps(pill), flush=True)
        capture(f'pill-{index}')
        if wayland:
            op('bubble_restore')
        else:
            activate(wid)
            g = geometry(wid)
            pointer(g['x'] + g['width'] // 2, g['y'] + g['height'] // 2)
            time.sleep(.2)
            button(True)
            time.sleep(.1)
            button(False)
        qa.wait("any(w.width>=560 and w.height>=407 for w in bpy.context.window_manager.windows if any(a.type=='AGENT_BUBBLE' for a in w.screen.areas))", timeout=5)
        restored = state()
        print('RESTORE_STATE', index, json.dumps(restored), flush=True)
        assert restored['messages'] == initial['messages'], restored
        assert restored['draft'] == initial['draft'], restored
        assert restored['width'] == enlarged['width'], restored
        assert restored['height'] == enlarged['height'], restored
        cycles.append({'pill': pill, 'restored': restored})
    capture('restored')
    if wayland:
        op('bubble_set_size', width=100, height=80)
        time.sleep(1)
        shrunk = state()
    else:
        shrunk = drag(wid, -500, -500)
    assert shrunk['width'] >= 560 and shrunk['height'] >= 230, shrunk
    assert shrunk['width'] < enlarged['width'], (shrunk, enlarged)
    capture('minimum-size')
    # Programmatic restore must also honor the transcript floor.
    assert 'FINISHED' in op('bubble_minimise')
    assert 'FINISHED' in op('bubble_restore')
    qa.wait("any(w.width>=560 and w.height>=407 for w in bpy.context.window_manager.windows if any(a.type=='AGENT_BUBBLE' for a in w.screen.areas))", timeout=10)
    assert state()['height'] >= 407, state()
    result = {'initial': initial, 'enlarged': enlarged, 'cycles': cycles, 'shrunk': shrunk,
              'out': str(app.out), 'wayland': wayland,
              'renderer': qa.eval('import gpu; result=gpu.platform.renderer_get()')}
    (app.out / 'verdict.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
except Exception:
    print('FAILURE_STATE', json.dumps(state()), flush=True)
    raise
finally:
    if display:
        x.XCloseDisplay(display)
    app.stop(harness)
