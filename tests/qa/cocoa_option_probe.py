# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Deliver AppKit Option events to the real GHOST view, below WM simulation.

Test-only: requires an isolated macOS QA app without --enable-event-simulate.
The target comes from a semantic native widget; no global OS key injection.
"""
import ctypes as ct
import time

import bpy
import qa_driver as drv

_objc = ct.CDLL('/usr/lib/libobjc.A.dylib')
_objc.objc_getClass.restype = ct.c_void_p
_objc.sel_registerName.restype = ct.c_void_p
PTR = ct.c_void_p


class Point(ct.Structure):
    _fields_ = [('x', ct.c_double), ('y', ct.c_double)]


class Rect(ct.Structure):
    _fields_ = [('origin', Point), ('size', Point)]


def send(ret, obj, selector, types=(), args=()):
    method = ct.CFUNCTYPE(ret, PTR, PTR, *types)(('objc_msgSend', _objc))
    return method(obj, _objc.sel_registerName(selector.encode()), *args)


def native_target(query):
    w = drv.find_one(**query)['_win']
    app = send(PTR, _objc.objc_getClass(b'NSApplication'), 'sharedApplication')
    windows = send(PTR, app, 'windows')
    matches = []
    for i in range(send(ct.c_ulong, windows, 'count')):
        win = send(PTR, windows, 'objectAtIndex:', (ct.c_ulong,), (i,))
        view = send(PTR, win, 'contentView')
        bounds = send(Rect, view, 'bounds')
        # Window RNA uses Cocoa points; the QA widget rectangles use pixels.
        if (abs(bounds.size.x - w.width) < 1 and
                abs(bounds.size.y - w.height) < 1):
            matches.append((win, view))
    assert len(matches) == 1, f'Ambiguous Cocoa window for {query}: {len(matches)}'
    win, container = matches[0]
    # The island's contentView is an NSGlassEffectView. Keyboard input goes
    # to the nested GHOST Metal/OpenGL responder, not that decorative host.
    views = []
    def visit(view):
        name = send(PTR, view, 'className')
        if send(ct.c_char_p, name, 'UTF8String') in {b'CocoaMetalView', b'CocoaOpenGLView'}:
            views.append(view)
        children = send(PTR, view, 'subviews')
        for i in range(send(ct.c_ulong, children, 'count')):
            visit(send(PTR, children, 'objectAtIndex:', (ct.c_ulong,), (i,)))
    visit(container)
    assert len(views) == 1, f'Expected one GHOST responder, got {len(views)}'
    return win, views[0]


def option(query, pressed, right=False):
    assert not bpy.app.use_event_simulate, 'WM simulation would discard native GHOST events'
    win, view = native_target(query)
    flags = ((1 << 19) | (0x40 if right else 0x20)) if pressed else 0
    empty = send(PTR, _objc.objc_getClass(b'NSString'), 'stringWithUTF8String:',
                 (ct.c_char_p,), (b'',))
    event = send(
        PTR, _objc.objc_getClass(b'NSEvent'),
        'keyEventWithType:location:modifierFlags:timestamp:windowNumber:context:'
        'characters:charactersIgnoringModifiers:isARepeat:keyCode:',
        (ct.c_ulong, Point, ct.c_ulong, ct.c_double, ct.c_long, PTR, PTR, PTR,
         ct.c_bool, ct.c_ushort),
        (12, Point(0, 0), flags, time.monotonic(), send(ct.c_long, win, 'windowNumber'),
         None, empty, empty, False, 61 if right else 58),
    )
    assert event, 'AppKit did not construct the modifier event'
    assert send(PTR, event, 'window') == win, 'AppKit event lost its target window'
    assert send(ct.c_ulong, event, 'modifierFlags') == flags, 'AppKit dropped modifier bits'
    # Queue through AppKit's event pump. Calling flagsChanged directly from a
    # bpy timer queues GHOST events outside processEvents(), so they may not
    # be dispatched until an unrelated physical event wakes the native loop.
    app = send(PTR, _objc.objc_getClass(b'NSApplication'), 'sharedApplication')
    send(None, app, 'postEvent:atStart:', (PTR, ct.c_bool), (event, False))


def focus_composer(query):
    widget = drv.find_one(**query)
    w = widget['_win']
    a = next(a for a in w.screen.areas if a.type == 'AGENT_BUBBLE')
    r = next(r for r in a.regions if r.type == 'WINDOW')
    with bpy.context.temp_override(window=w, area=a, region=r):
        bpy.ops.mixie_chat.focus_composer()


def activate(query):
    app = send(PTR, _objc.objc_getClass(b'NSApplication'), 'sharedApplication')
    win, view = native_target(query)
    send(None, app, 'activateIgnoringOtherApps:', (ct.c_bool,), (True,))
    send(None, win, 'makeKeyAndOrderFront:', (PTR,), (None,))
    send(ct.c_bool, win, 'makeFirstResponder:', (PTR,), (view,))
