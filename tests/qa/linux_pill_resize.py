# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Linux outside-click, pill/restore/resize regression, without backend requests.

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
            mixed=not wayland, extra_env={} if wayland else {'WAYLAND_DISPLAY': ''})
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
native_input = None
last_cursor = None

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
    if native_input:
        native_input.move(px, py)
        return
    xt.XTestFakeMotionEvent(display, -1, px, py, 0)
    x.XFlush(display)

def button(down, number=1):
    if native_input:
        if number == 4:
            if down:
                native_input.call(native_input.desktop, native_input.path,
                                  native_input.desktop+'.Session',
                                  'NotifyPointerAxisDiscrete', '(ui)', (0, -1))
        else:
            native_input.button(down, number)
        return
    xt.XTestFakeButtonEvent(display, number, int(down), 0)
    x.XFlush(display)

def main_event(kind):
    # Background viewport gestures have no button target. Derive their point
    # from the live VIEW_3D WINDOW region, away from the island and toolbars.
    target = qa.eval("w=drv.main_window()\n"
                     "r=next(r for a in w.screen.areas if a.type=='VIEW_3D' "
                     "for r in a.regions if r.type=='WINDOW')\n"
                     "result={'x':r.x+150,'y':r.y+r.height-120}")
    if wayland:
        qa.eval("w=drv.main_window()\n"
                f"w.event_simulate(type={kind!r},value='NOTHING' if {kind!r}=='MOUSEMOVE' "
                f"else 'PRESS',x={target['x']},y={target['y']})")
        if kind in {'LEFTMOUSE', 'MIDDLEMOUSE'}:
            qa.eval("w=drv.main_window()\n"
                    f"w.event_simulate(type={kind!r},value='RELEASE',"
                    f"x={target['x']},y={target['y']})")
    else:
        g = geometry(main_wid)
        pointer(g['x'] + target['x'], g['y'] + g['height'] - 1 - target['y'])
        time.sleep(.2)
        if kind != 'MOUSEMOVE':
            number = {'LEFTMOUSE': 1, 'MIDDLEMOUSE': 2, 'WHEELUPMOUSE': 4}[kind]
            button(True, number)
            time.sleep(.1)
            button(False, number)
    time.sleep(.4)

def drag(wid, dx, dy, edge='se', inset=7):
    global last_cursor
    activate(wid)
    g = geometry(wid)
    px = g['x'] + (inset if 'w' in edge else g['width'] - inset if 'e' in edge else g['width']//2)
    py = g['y'] + (inset if 'n' in edge else g['height'] - inset if 's' in edge else g['height']//2)
    pointer(px, py)
    time.sleep(.2)
    if os.environ.get('MIXAR_QA_EDGES'):
        from x11_cursor import capture_cursor
        last_cursor = capture_cursor(display, app.out/f'cursor-{edge}.png')
    button(True)
    try:
        time.sleep(.05)
        for i in range(1, 6):
            pointer(px + dx * i // 5, py + dy * i // 5)
            time.sleep(.08)
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

def settle():
    if wayland:
        # A configure may briefly report the requested size while an older
        # configure is still queued. Wait for the production transition pump
        # to settle, rather than sampling the first matching dimensions.
        qa.wait('not bpy.ops.mixar.bubble_hover_tick.poll()', timeout=10)

try:
    if os.environ.get('MIXAR_QA_MUTTER'):
        from mutter_input import MutterInput
        native_input = MutterInput()
    # The interaction is local and works signed out. Apply the startup-health
    # log checks without waiting for backend login (which is rate limited).
    from startup_health import _LOAD_FAIL
    log = (app.out / 'app.log').read_text(errors='replace')
    failures = [line for line in log.splitlines() if _LOAD_FAIL.search(line)]
    tracebacks = log.count('Traceback (most recent call last)')
    assert not failures and not tracebacks, (failures, tracebacks)
    startup = {'module_load_failures': failures, 'tracebacks': tracebacks,
               'login_required': False}
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
        clients = re.findall(r'0x[0-9a-f]+', subprocess.check_output(
            ['xprop', '-root', '_NET_CLIENT_LIST'], text=True))
        owned = [w for w in clients if w != wid and re.search(
            r'= ' + str(app.pid) + r'\b', subprocess.check_output(
                ['xprop', '-id', w, '_NET_WM_PID'], text=True))]
        main_wid = max(owned, key=lambda w: geometry(w)['width'])
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
    initial = state()
    assert max(h for kind, _, h in initial['regions'] if kind == 'WINDOW') > 100, initial
    controls = qa.find(area_type='AGENT_BUBBLE', limit=500)['widgets']
    assert not any(w.get('op') in {
        'MIXAR_OT_bubble_close', 'MIXAR_OT_bubble_toggle_expand',
        'MIXAR_OT_bubble_toggle_expand_tracked', 'MIXAR_OT_bubble_minimise'
    } for w in controls), controls
    capture('conversation')
    if os.environ.get('MIXAR_QA_BUSY_PARENT'):
        assert not native_input and not wayland, 'busy-parent fixture requires disposable X11'
        from x11_cursor import set_parent_busy, capture_cursor
        g = geometry(wid)
        pointer(g['x']+g['width']//2, g['y']+g['height']//2)
        time.sleep(.3)
        set_parent_busy(display, wid)
        busy = capture_cursor(display, app.out/'busy-cursor-fixture.png')
        qa.eval("w=next(w for w in bpy.context.window_manager.windows "
                "if any(a.type=='AGENT_BUBBLE' for a in w.screen.areas)); w.cursor_set('DEFAULT')")
        cursor = capture_cursor(display, app.out/'idle-cursor.png')
        print('IDLE_CURSOR', json.dumps(cursor), flush=True)
        (app.out/'idle-cursor.json').write_text(json.dumps(cursor,indent=2)+'\n')
        if not os.environ.get('MIXAR_QA_BASELINE'):
            assert cursor['pixels_sha256'] != busy['pixels_sha256'], cursor
    for kind in ('MOUSEMOVE', 'WHEELUPMOUSE'):
        main_event(kind)
        assert state()['width'] >= 560, (kind, state())
    capture('outside-scroll-stays-open')
    if os.environ.get('MIXAR_QA_EDGES') and not wayland:
        from x11_cursor import capture_cursor
        g = geometry(wid)
        pointer(g['x']+g['width']//2, g['y']+g['height']//2)
        time.sleep(.2)
        body_cursor = capture_cursor(display, app.out/'body-cursor.png')
        edges = []
        for edge, dx, dy in [('w',-32,0),('e',32,0),('n',0,-24),('s',0,24),
                             ('nw',-32,-24),('ne',32,-24),('sw',-32,24),('se',32,24)]:
            before = geometry(wid)
            inset = int(os.environ.get('MIXAR_QA_EDGE_INSET', 7 if len(edge)==2 else 1))
            after = drag(wid, dx, dy, edge, inset)
            passed = (after['width'] >= before['width']+abs(dx)-4 and
                      after['height'] >= before['height']+abs(dy)-4)
            anchor = (abs((after['x']+after['width'] if 'w' in edge else after['x']) -
                          (before['x']+before['width'] if 'w' in edge else before['x'])) <= 4 and
                      abs((after['y']+after['height'] if 'n' in edge else after['y']) -
                          (before['y']+before['height'] if 'n' in edge else before['y'])) <= 4)
            cursor_visible = last_cursor['pixels_sha256'] != body_cursor['pixels_sha256']
            assert state()['draft'] == initial['draft'], state()
            edges.append({'edge':edge,'before':before,'after':after,
                          'cursor':last_cursor,'anchor_preserved':anchor,
                          'resize_cursor_visible':cursor_visible,
                          'passed':passed and anchor and cursor_visible})
            print('EDGE_RESULT', json.dumps(edges[-1]), flush=True)
        capture('all-edges')
        (app.out/'edges.json').write_text(json.dumps(edges,indent=2)+'\n')
        if not os.environ.get('MIXAR_QA_BASELINE'):
            assert all(e['passed'] for e in edges), edges
        print(app.out, flush=True)
        raise SystemExit(0)
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
        method = ('LEFTMOUSE', 'MIDDLEMOUSE', 'ESC')[index]
        if method != 'ESC':
            if method == 'LEFTMOUSE':
                qa.eval("bpy.ops.object.select_all(action='SELECT')\n"
                        "assert bpy.context.selected_objects")
            main_event(method)
            if method == 'LEFTMOUSE':
                assert qa.eval('result=len(drv.main_window().scene.objects) > 0 and '
                               'not any(o.select_get() for o in drv.main_window().scene.objects)'), \
                    'outside click was consumed instead of reaching the viewport'
        elif wayland:
            op('bubble_minimise')
        else:
            activate(wid)
            # Native pill restore can move the window. Put the pointer over
            # the live composer so the area-scoped Escape keymap has context
            # after the first Escape releases the window-modal text editor.
            target = qa.find(area_type='AGENT_BUBBLE', prop='mixie_chat_input')['widgets'][0]
            g = geometry(wid)
            pointer(g['x'] + target['center'][0],
                    g['y'] + g['height'] - 1 - target['center'][1])
            time.sleep(.2)
            code = x.XKeysymToKeycode(display, 0xff1b)  # Escape
            xt.XTestFakeKeyEvent(display, code, 1, 0)
            xt.XTestFakeKeyEvent(display, code, 0, 0)
            x.XFlush(display)
            # Restore now focuses the composer as on macOS. Its first Escape
            # ends text editing; the next reaches the window's pill shortcut.
            time.sleep(.3)
            assert state()['width'] >= 560, 'restore did not focus the composer'
            xt.XTestFakeKeyEvent(display, code, 1, 0)
            xt.XTestFakeKeyEvent(display, code, 0, 0)
            x.XFlush(display)
        qa.wait("any(w.width<400 and w.height<80 for w in bpy.context.window_manager.windows if any(a.type=='AGENT_BUBBLE' for a in w.screen.areas))", timeout=5)
        settle()
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
        settle()
        restored = state()
        print('RESTORE_STATE', index, json.dumps(restored), flush=True)
        assert restored['messages'] == initial['messages'], restored
        assert restored['draft'] == initial['draft'], restored
        assert restored['width'] == enlarged['width'], restored
        assert restored['height'] == enlarged['height'], restored
        cycles.append({'method': method, 'pill': pill, 'restored': restored})
    capture('restored')
    if wayland:
        op('bubble_set_size', width=100, height=80)
        time.sleep(1)
        shrunk = state()
    else:
        shrunk = drag(wid, -500, -500)
    assert shrunk['width'] >= 560 and shrunk['height'] >= 230, shrunk
    assert shrunk['width'] < enlarged['width'], (shrunk, enlarged)
    assert state()['draft'] == initial['draft'], state()
    assert state()['messages'] == initial['messages'], state()
    capture('minimum-size')
    # Programmatic restore must also honor the transcript floor.
    assert 'FINISHED' in op('bubble_minimise')
    assert 'FINISHED' in op('bubble_restore')
    qa.wait("any(w.width>=560 and w.height>=407 for w in bpy.context.window_manager.windows if any(a.type=='AGENT_BUBBLE' for a in w.screen.areas))", timeout=10)
    assert state()['height'] >= 407, state()
    result = {'initial': initial, 'enlarged': enlarged, 'cycles': cycles, 'shrunk': shrunk,
              'startup': startup, 'window_buttons': [], 'outside_scroll_stays_open': True,
              'out': str(app.out), 'wayland': wayland,
              'renderer': qa.eval('import gpu; result=gpu.platform.renderer_get()')}
    (app.out / 'verdict.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
except Exception:
    print('FAILURE_STATE', json.dumps(state()), flush=True)
    if wayland:
        print('TRANSITION_STATE', qa.eval(
            "from mixar.modules.agent_bubble.ui.operators import hover_ops\n"
            "result={'pending':bpy.ops.mixar.bubble_hover_tick.poll(),"
            "'timer':bpy.app.timers.is_registered(hover_ops._hover_tick)}"), flush=True)
    raise
finally:
    try:
        if native_input:
            native_input.close()
    finally:
        if display:
            x.XCloseDisplay(display)
        app.stop(harness)
