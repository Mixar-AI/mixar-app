# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Native geometry fixtures, confined to the isolated QA process on macOS."""
import ctypes as ct
from mixie_window_native import Rect, Size


def frame(kind, *, move=None, size=None):
    objc = ct.CDLL('/usr/lib/libobjc.A.dylib')
    objc.objc_getClass.argtypes = [ct.c_char_p]
    objc.objc_getClass.restype = ct.c_void_p
    objc.sel_registerName.argtypes = [ct.c_char_p]
    objc.sel_registerName.restype = ct.c_void_p

    def send(obj, selector, result=ct.c_void_p, args=(), values=()):
        fn = ct.CFUNCTYPE(result, ct.c_void_p, ct.c_void_p, *args)(('objc_msgSend', objc))
        return fn(obj, objc.sel_registerName(selector.encode()), *values)

    app = send(objc.objc_getClass(b'NSApplication'), 'sharedApplication')
    windows = send(app, 'windows')
    candidates = []
    for i in range(send(windows, 'count', ct.c_ulong)):
        win = send(windows, 'objectAtIndex:', args=(ct.c_ulong,), values=(i,))
        title = send(send(win, 'title'), 'UTF8String', ct.c_char_p) or b''
        rect = send(win, 'frame', Rect)
        bubble = title == b'Agent Bubble' and rect.size.height > 100
        pill = title == b'Agent Bubble' and rect.size.height <= 100
        host = title != b'Agent Bubble' and rect.size.width > 500 and rect.size.height > 500
        if {'bubble': bubble, 'pill': pill, 'host': host}[kind]:
            candidates.append((rect.size.width * rect.size.height, win, rect))
    _, win, rect = max(candidates, key=lambda item: item[0])
    if move:
        rect.origin.width += move[0]
        rect.origin.height += move[1]
    if size:
        rect.size = Size(*size)
    if move or size:
        send(win, 'setFrame:display:', None, (Rect, ct.c_bool), (rect, True))
    rect = send(win, 'frame', Rect)
    return [rect.origin.width, rect.origin.height, rect.size.width, rect.size.height]
