# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""X11/XWayland chrome, resize, native drag and live-glass regression.

Requires Pillow, xprop, xwininfo and libXtst. Run on an idle test desktop:
the drag check briefly moves the real pointer and focuses its isolated window.

QA_HARNESS=/path/to/mixar-qa-harness python3 tests/qa/linux_bubble_window.py
Set MIXAR_QA_BASELINE=1 to record the unfixed behavior without assertions.
"""

import ctypes
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from PIL import Image, ImageChops, ImageStat

repo = Path(__file__).resolve().parents[2]
harness = Path(os.environ['QA_HARNESS']).resolve()
sys.path[:0] = [str(repo / 'tests/qa/sticky_ui'), str(harness / 'scenarios')]
from qa_launch import start
from lib import QA

baseline = os.environ.get('MIXAR_QA_BASELINE') == '1'
port = int(os.environ.get('MIXAR_QA_PORT', '4792'))
# Only the app needs X11. Keep the runner's Wayland display: Ubuntu's XTest
# input bridge uses it, and silently ignores pointer injection without it.
app = start(harness, repo / 'build/Dev/bin', port, Path('/tmp/mixar-linux-bubble'),
            mixed=True, extra_env={'WAYLAND_DISPLAY': ''})
qa = QA(port=port)
xlib = ctypes.CDLL('libX11.so.6')
xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
xlib.XOpenDisplay.restype = ctypes.c_void_p
xlib.XResizeWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_uint, ctypes.c_uint]
xlib.XFlush.argtypes = [ctypes.c_void_p]
xlib.XCloseDisplay.argtypes = [ctypes.c_void_p]
xlib.XRaiseWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
xlib.XSetInputFocus.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
xlib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
xlib.XDefaultRootWindow.restype = ctypes.c_ulong
xlib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
xlib.XInternAtom.restype = ctypes.c_ulong
xlib.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long, ctypes.c_void_p]

class ClientMessage(ctypes.Structure):
    _fields_ = [('type', ctypes.c_int), ('serial', ctypes.c_ulong),
                ('send_event', ctypes.c_int), ('display', ctypes.c_void_p),
                ('window', ctypes.c_ulong), ('message_type', ctypes.c_ulong),
                ('format', ctypes.c_int), ('data', ctypes.c_long * 5)]
display = xlib.XOpenDisplay(None)
assert display

class XImage(ctypes.Structure):
    _fields_ = [('width', ctypes.c_int), ('height', ctypes.c_int),
                ('xoffset', ctypes.c_int), ('format', ctypes.c_int),
                ('data', ctypes.c_void_p), ('byte_order', ctypes.c_int),
                ('bitmap_unit', ctypes.c_int), ('bitmap_bit_order', ctypes.c_int),
                ('bitmap_pad', ctypes.c_int), ('depth', ctypes.c_int),
                ('bytes_per_line', ctypes.c_int), ('bits_per_pixel', ctypes.c_int)]

xlib.XGetImage.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
                          ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong, ctypes.c_int]
xlib.XGetImage.restype = ctypes.POINTER(XImage)
xlib.XDestroyImage.argtypes = [ctypes.POINTER(XImage)]

def native_image(wid, width, height, rgba=False):
    """Read the presented client pixels, including the live GPU glass pass.

    bpy's offscreen screenshot deliberately omits that pass.
    """
    raw = xlib.XGetImage(display, int(wid, 16), 0, 0, width, height, ctypes.c_ulong(-1), 2)
    assert raw
    try:
        info = raw.contents
        assert info.bits_per_pixel == 32 and info.byte_order == 0
        data = ctypes.string_at(info.data, info.bytes_per_line * height)
        return Image.frombytes('RGBA' if rgba else 'RGB', (width, height), data,
                               'raw', 'BGRA' if rgba else 'BGRX', info.bytes_per_line)
    finally:
        xlib.XDestroyImage(raw)

def prop(wid, *names):
    return subprocess.check_output(['xprop', '-id', wid, *names], text=True)

class XRectangle(ctypes.Structure):
    _fields_ = [('x', ctypes.c_short), ('y', ctypes.c_short),
                ('width', ctypes.c_ushort), ('height', ctypes.c_ushort)]

xext = ctypes.CDLL('libXext.so.6')
xext.XShapeGetRectangles.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
                                    ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
xext.XShapeGetRectangles.restype = ctypes.POINTER(XRectangle)
xlib.XFree.argtypes = [ctypes.c_void_p]

def check_corners(wid, width, height):
    shapes = {}
    for name, kind in [('bounding', 0), ('input', 2)]:
        count, ordering = ctypes.c_int(), ctypes.c_int()
        raw = xext.XShapeGetRectangles(display, int(wid, 16), kind,
                                      ctypes.byref(count), ctypes.byref(ordering))
        try:
            rects = [(r.x, r.y, r.width, r.height) for r in raw[:count.value]]
        finally:
            xlib.XFree(raw)
        def contains(x, y):
            return any(rx <= x < rx + rw and ry <= y < ry + rh for rx, ry, rw, rh in rects)
        for x, y in [(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)]:
            assert not contains(x, y), (name, width, height, x, y, rects)
        for x, y in [(14, 0), (width - 15, 0), (0, 14), (width - 1, height - 15), (width // 2, height // 2)]:
            assert contains(x, y), (name, width, height, x, y, rects)
        shapes[name] = rects
    assert shapes['bounding'] == shapes['input'], shapes
    return shapes

try:
    qa.wait("any(a.type == 'AGENT_BUBBLE' for w in bpy.context.window_manager.windows for a in w.screen.areas)", timeout=30)
    time.sleep(5)
    tree = subprocess.check_output(['xwininfo', '-root', '-tree'], text=True)
    candidates = re.findall(r'(0x[0-9a-f]+) "Agent Bubble": \("Mixar" "Mixar"\)', tree)
    wid = next(w for w in candidates if re.search(r'= ' + str(app.pid) + r'\b', prop(w, '_NET_WM_PID')))
    properties = prop(wid, '_MOTIF_WM_HINTS', '_NET_FRAME_EXTENTS', 'WM_NORMAL_HINTS')
    if not baseline:
        motif = re.search(r'_MOTIF_WM_HINTS\([^)]*\) = ([^\n]+)', properties)
        assert motif, properties
        motif_values = [part.strip() for part in motif.group(1).split(',')]
        # xfwm4 ignores Motif unless five CARD32s are present.
        assert len(motif_values) == 5, properties
        assert int(motif_values[0], 0) & 0x2, properties  # MWM_HINTS_DECORATIONS
        assert int(motif_values[2], 0) == 0, properties  # decorations off
        extents = prop(wid, '_NET_FRAME_EXTENTS')
        # Mutter removes the frame property entirely when it unreparents a
        # frameless client; other WMs publish four zero extents.
        if 'not found' in extents:
            hierarchy = subprocess.check_output(['xwininfo', '-id', wid, '-tree'], text=True)
            root = re.search(r'Root window id: (0x[0-9a-f]+)', hierarchy).group(1)
            assert f'Parent window id: {root}' in hierarchy, hierarchy
        else:
            assert '0, 0, 0, 0' in extents, properties
        assert 'minimum size: 560 by 230' in properties, properties
    result = {'baseline': baseline, 'native_properties': properties, 'sizes': []}
    for index, (width, height) in enumerate([(100, 80), (800, 500), (320, 240), (560, 230), (1000, 230), (678, 300)]):
        xlib.XResizeWindow(display, int(wid, 16), width, height)
        xlib.XFlush(display)
        time.sleep(2)
        image = app.out / f'resize-{index}.png'
        state = qa.eval("w = next(w for w in bpy.context.window_manager.windows if any(a.type == 'AGENT_BUBBLE' for a in w.screen.areas));\nwith bpy.context.temp_override(window=w): bpy.ops.screen.screenshot(filepath=" + repr(str(image)) + ")\nresult = {'width': w.width, 'height': w.height, 'regions': [(r.type, r.width, r.height) for a in w.screen.areas for r in a.regions]}")
        pixels = Image.open(image).convert('RGB')
        state['pixel_stddev'] = max(ImageStat.Stat(pixels).stddev)
        state['requested'] = [width, height]
        result['sizes'].append(state)
        if not baseline:
            assert state['width'] >= 560 and state['height'] >= 230, state
            assert state['pixel_stddev'] > 5, state
            state['native_corner_shapes'] = check_corners(wid, state['width'], state['height'])
    if not baseline:
        def position():
            info = subprocess.check_output(['xwininfo', '-id', wid], text=True)
            return tuple(int(re.search(r'Absolute upper-left ' + axis + r':\s+(-?\d+)', info).group(1)) for axis in ('X', 'Y'))

        # Native pointer input is needed: the X11 drag follow-up reads the
        # real pointer and asks the WM to move via _NET_MOVERESIZE_WINDOW.
        xtest = ctypes.CDLL('libXtst.so.6')
        xtest.XTestFakeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
        xtest.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        before = position()
        event = ClientMessage(type=33, display=display, window=int(wid, 16),
                              message_type=xlib.XInternAtom(display, b'_NET_ACTIVE_WINDOW', 0),
                              format=32, data=(ctypes.c_long * 5)(2, 0, 0, 0, 0))
        xlib.XSendEvent(display, xlib.XDefaultRootWindow(display), 0,
                        (1 << 19) | (1 << 20), ctypes.byref(event))
        xlib.XRaiseWindow(display, int(wid, 16))
        xlib.XSetInputFocus(display, int(wid, 16), 2, 0)
        xlib.XFlush(display)
        time.sleep(0.5)
        # Empty space between the tab row and Library button. Drive the real
        # header handler once; invoking its native operator a second time can
        # cancel a window-manager move that the press has already started.
        x, y = before[0] + 480, before[1] + 15
        xtest.XTestFakeMotionEvent(display, -1, x, y, 0)
        xtest.XTestFakeButtonEvent(display, 1, 1, 0)
        xlib.XFlush(display)
        drag_positions = [before]
        try:
            time.sleep(0.5)
            for step in range(1, 6):
                xtest.XTestFakeMotionEvent(display, -1, x + 16 * step, y + 10 * step, 0)
                xlib.XFlush(display)
                time.sleep(0.15)
                # A timer must not pull the window back to its press position
                # while the compositor owns the native drag.
                for sample in range(3):
                    drag_positions.append(position())
                    time.sleep(0.05)
        finally:
            xtest.XTestFakeButtonEvent(display, 1, 0, 0)
            xlib.XFlush(display)
        time.sleep(0.5)
        result['drag'] = {'before': before, 'after': position(), 'positions': drag_positions}
        assert result['drag']['after'] != before, result['drag']
        assert all(b[0] >= a[0] and b[1] >= a[1]
                   for a, b in zip(drag_positions, drag_positions[1:])), result['drag']
        xtest.XTestFakeMotionEvent(display, -1, x + 120, y + 80, 0)
        xlib.XFlush(display)
        time.sleep(0.3)
        assert position() == result['drag']['after'], 'Window followed pointer after release'
        # The product's resize operator must resize the real Linux window too.
        qa.eval("w = next(w for w in bpy.context.window_manager.windows if any(a.type == 'AGENT_BUBBLE' for a in w.screen.areas));\nwith bpy.context.temp_override(window=w): bpy.ops.mixar.bubble_set_size(width=700,height=350)")
        qa.wait("any(w.width == 700 and w.height == 350 for w in bpy.context.window_manager.windows)", timeout=5)
        result['operator_resize'] = check_corners(wid, 700, 350)
        qa.eval("w = next(w for w in bpy.context.window_manager.windows if any(a.type == 'AGENT_BUBBLE' for a in w.screen.areas));\nwith bpy.context.temp_override(window=w): bpy.ops.mixar.bubble_set_size(width=678,height=300)")
        qa.wait("any(w.width == 678 and w.height == 300 for w in bpy.context.window_manager.windows)", timeout=5)
        # The background must follow live viewport changes while the UI stays
        # crisp. Read real presented pixels, not Blender's offscreen screenshot.
        captures = []
        for name, color in [('red', (0.8, 0.05, 0.05)), ('blue', (0.05, 0.05, 0.8))]:
            qa.eval("\nfor w in bpy.context.window_manager.windows:\n for a in w.screen.areas:\n  if a.type == 'VIEW_3D':\n   a.spaces.active.shading.background_type = 'VIEWPORT'\n   a.spaces.active.shading.background_color = " + repr(color) + "\n   a.tag_redraw()")
            time.sleep(2)
            capture = native_image(wid, 678, 300)
            capture.save(app.out / f'glass-{name}.png')
            captures.append(capture)
        difference = ImageChops.difference(*captures)
        result['glass_mean_difference'] = ImageStat.Stat(difference).mean
        assert max(result['glass_mean_difference']) > 2, result['glass_mean_difference']
        rounded = native_image(wid, 678, 300, rgba=True)
        result['corner_alpha'] = [rounded.getpixel(p)[3] for p in
                                  [(0, 0), (677, 0), (0, 299), (677, 299)]]
        assert result['corner_alpha'] == [0, 0, 0, 0], result['corner_alpha']
        assert rounded.getpixel((14, 0))[3] == 255
        rounded.save(app.out / 'rounded-window.png')
    (app.out / 'verdict.json').write_text(json.dumps(result, indent=2))
    print(json.dumps({'out': str(app.out), **result}, indent=2), flush=True)
finally:
    xlib.XCloseDisplay(display)
    app.stop(harness)
