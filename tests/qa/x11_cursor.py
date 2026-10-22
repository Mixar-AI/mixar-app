# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Capture the actual X11/XWayland pointer image, including inherited cursors."""
import ctypes as ct
import hashlib
from PIL import Image


class CursorImage(ct.Structure):
    _fields_ = [('x', ct.c_short), ('y', ct.c_short),
                ('width', ct.c_ushort), ('height', ct.c_ushort),
                ('xhot', ct.c_ushort), ('yhot', ct.c_ushort),
                ('serial', ct.c_ulong), ('pixels', ct.POINTER(ct.c_ulong)),
                ('atom', ct.c_ulong), ('name', ct.c_char_p)]


def capture_cursor(display, path):
    fixes = ct.CDLL('libXfixes.so.3')
    fixes.XFixesGetCursorImage.argtypes = [ct.c_void_p]
    fixes.XFixesGetCursorImage.restype = ct.POINTER(CursorImage)
    x = ct.CDLL('libX11.so.6')
    x.XFree.argtypes = [ct.c_void_p]
    raw = fixes.XFixesGetCursorImage(display)
    assert raw
    try:
        c = raw.contents
        pixels = b''.join((int(c.pixels[i]) & 0xffffffff).to_bytes(4, 'little')
                          for i in range(c.width*c.height))
        Image.frombytes('RGBA', (c.width,c.height), pixels, 'raw', 'BGRA').save(path)
        return {'name': c.name.decode() if c.name else None,
                'width': c.width, 'height': c.height, 'hotspot':[c.xhot,c.yhot],
                'pixels_sha256':hashlib.sha256(pixels).hexdigest()}
    finally:
        x.XFree(raw)


def set_parent_busy(display, wid):
    """Simulate a compositor's launch cursor, only on a disposable X server."""
    x = ct.CDLL('libX11.so.6')
    x.XQueryTree.argtypes = [ct.c_void_p, ct.c_ulong, ct.POINTER(ct.c_ulong),
                            ct.POINTER(ct.c_ulong), ct.POINTER(ct.POINTER(ct.c_ulong)),
                            ct.POINTER(ct.c_uint)]
    x.XCreateFontCursor.argtypes = [ct.c_void_p, ct.c_uint]
    x.XCreateFontCursor.restype = ct.c_ulong
    x.XDefineCursor.argtypes = [ct.c_void_p, ct.c_ulong, ct.c_ulong]
    x.XFree.argtypes = [ct.c_void_p]
    x.XFlush.argtypes = [ct.c_void_p]
    root, parent, count = ct.c_ulong(), ct.c_ulong(), ct.c_uint()
    children = ct.POINTER(ct.c_ulong)()
    assert x.XQueryTree(display, int(wid,16), ct.byref(root), ct.byref(parent),
                         ct.byref(children), ct.byref(count))
    if children:
        x.XFree(children)
    watch = x.XCreateFontCursor(display,150)  # XC_watch
    x.XDefineCursor(display, parent.value, watch)
    x.XDefineCursor(display, int(wid,16), watch)
    x.XFlush(display)
