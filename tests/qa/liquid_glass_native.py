# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Capture only this QA process's visible macOS windows, including OS frost.

Called on the app's main thread through qa.eval. Blender's screen.screenshot
captures GPU pixels before the native compositor, so cannot verify AppKit glass.
No input events or window changes are performed here.
"""

import ctypes
from pathlib import Path
import subprocess
import sys


def capture(out):
    if sys.platform != 'darwin':
        return {'available': False, 'reason': 'Native capture helper is macOS-only'}
    Path(out).mkdir(parents=True, exist_ok=True)
    objc = ctypes.CDLL('/usr/lib/libobjc.A.dylib')
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    send = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(('objc_msgSend', objc))
    indexed = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                              ctypes.c_ulong)(('objc_msgSend', objc))

    def msg(obj, name):
        return send(obj, objc.sel_registerName(name.encode()))

    floating = ctypes.CFUNCTYPE(ctypes.c_double, ctypes.c_void_p, ctypes.c_void_p)(
        ('objc_msgSend', objc))
    objc.object_getClass.argtypes = [ctypes.c_void_p]
    objc.object_getClass.restype = ctypes.c_void_p
    objc.class_getName.argtypes = [ctypes.c_void_p]
    objc.class_getName.restype = ctypes.c_char_p

    def class_name(obj):
        return objc.class_getName(objc.object_getClass(obj)).decode() if obj else ''

    def material_state(window):
        root = msg(window, 'contentView')
        root_class = class_name(root).removeprefix('NSKVONotifying_')
        if root_class == 'NSGlassEffectView':
            host = msg(root, 'contentView')
        else:
            children = msg(root, 'subviews')
            host = indexed(children, objc.sel_registerName(b'objectAtIndex:'), 0) if msg(children, 'count') else None
        layer = msg(host, 'layer') if host else None
        return {'container': root_class, 'host': class_name(host),
                'host_window_matches': msg(host, 'window') == window if host else False,
                'window_opaque': bool(msg(window, 'isOpaque')),
                'background_alpha': floating(msg(window, 'backgroundColor'),
                                             objc.sel_registerName(b'alphaComponent')),
                'metal_opaque': bool(msg(layer, 'isOpaque')) if layer else None,
                'pixel_format': msg(layer, 'pixelFormat') if class_name(layer) == 'CAMetalLayer' else None}

    app = msg(objc.objc_getClass(b'NSApplication'), 'sharedApplication')
    windows = msg(app, 'windows')
    snapshots = []
    for index in range(msg(windows, 'count') or 0):
        window = indexed(windows, objc.sel_registerName(b'objectAtIndex:'), index)
        if not msg(window, 'isVisible'):
            continue
        number = msg(window, 'windowNumber')
        title_ptr = msg(msg(window, 'title'), 'UTF8String')
        title = ctypes.string_at(title_ptr).decode() if title_ptr else ''
        path = Path(out) / f'native_{number}.png'
        done = subprocess.run(['/usr/sbin/screencapture', '-x', '-l', str(number), str(path)],
                              capture_output=True, text=True, timeout=15)
        snapshot = {'number': number, 'title': title, 'path': str(path),
                    'ok': done.returncode == 0, 'error': done.stderr.strip()}
        if title in ('Agent Bubble', 'Agent Bubble Status'):
            snapshot['material'] = material_state(window)
        snapshots.append(snapshot)
    return {'available': bool(snapshots) and all(s['ok'] for s in snapshots), 'windows': snapshots}
