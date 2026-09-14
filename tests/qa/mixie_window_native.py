# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Read native window visibility, keyboard focus and size constraints in the QA app."""
import ctypes as ct
import sys



class Size(ct.Structure):
    _fields_ = [('width', ct.c_double), ('height', ct.c_double)]


class Rect(ct.Structure):
    _fields_ = [("origin", Size), ("size", Size)]


def windows():
    assert sys.platform == 'darwin'
    objc = ct.CDLL('/usr/lib/libobjc.A.dylib')
    objc.objc_getClass.argtypes = [ct.c_char_p]
    objc.objc_getClass.restype = ct.c_void_p
    objc.sel_registerName.argtypes = [ct.c_char_p]
    objc.sel_registerName.restype = ct.c_void_p

    def send(obj, selector, restype=ct.c_void_p, args=(), values=()):
        fn = ct.CFUNCTYPE(restype, ct.c_void_p, ct.c_void_p, *args)(('objc_msgSend', objc))
        return fn(obj, objc.sel_registerName(selector.encode()), *values)

    app = send(objc.objc_getClass(b'NSApplication'), 'sharedApplication')
    items = send(app, 'windows')
    result = []
    for i in range(send(items, 'count', ct.c_ulong)):
        win = send(items, 'objectAtIndex:', args=(ct.c_ulong,), values=(i,))
        title = send(send(win, 'title'), 'UTF8String', ct.c_char_p)
        limit = send(win, 'contentMaxSize', Size)
        rect = send(win, 'frame', Rect)
        result.append({'x': rect.origin.width, 'y': rect.origin.height,
                       'width': rect.size.width, 'height': rect.size.height, 'is_island': title == b'Agent Bubble' and rect.size.height > 100, 'title': title.decode() if title else '',
                       'visible': send(win, 'isVisible', ct.c_bool),
                       'background_draggable': send(win, 'isMovableByWindowBackground', ct.c_bool),
                       'key': send(win, 'isKeyWindow', ct.c_bool),
                       'max_height': limit.height})
    return result
