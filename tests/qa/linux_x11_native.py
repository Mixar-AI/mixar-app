# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Minimal Xlib access for an explicitly owned private QA display."""
import ctypes as c
import ctypes.util
import os


class Attributes(c.Structure):
    _fields_ = [(n, c.c_int) for n in ('x','y','width','height','border_width','depth')] + [
        ('visual',c.c_void_p),('root',c.c_ulong),('window_class',c.c_int),
        ('bit_gravity',c.c_int),('win_gravity',c.c_int),('backing_store',c.c_int),
        ('backing_planes',c.c_ulong),('backing_pixel',c.c_ulong),('save_under',c.c_int),
        ('colormap',c.c_ulong),('map_installed',c.c_int),('map_state',c.c_int),
        ('all_event_masks',c.c_long),('your_event_mask',c.c_long),
        ('do_not_propagate_mask',c.c_long),('override_redirect',c.c_int),('screen',c.c_void_p)]


class Display:
    def __init__(self):
        name=os.environ['QA_X_DISPLAY']
        assert name.startswith(':') and name not in (':0',':1'), name
        self.x=c.CDLL(ctypes.util.find_library('X11'))
        signatures={
            'XOpenDisplay':([c.c_char_p],c.c_void_p),
            'XDefaultRootWindow':([c.c_void_p],c.c_ulong),
            'XInternAtom':([c.c_void_p,c.c_char_p,c.c_int],c.c_ulong),
            'XQueryTree':([c.c_void_p,c.c_ulong,c.POINTER(c.c_ulong),c.POINTER(c.c_ulong),
                           c.POINTER(c.POINTER(c.c_ulong)),c.POINTER(c.c_uint)],c.c_int),
            'XGetWindowProperty':([c.c_void_p,c.c_ulong,c.c_ulong,c.c_long,c.c_long,c.c_int,c.c_ulong,
                                   c.POINTER(c.c_ulong),c.POINTER(c.c_int),c.POINTER(c.c_ulong),
                                   c.POINTER(c.c_ulong),c.POINTER(c.c_void_p)],c.c_int),
            'XGetWindowAttributes':([c.c_void_p,c.c_ulong,c.POINTER(Attributes)],c.c_int),
            'XTranslateCoordinates':([c.c_void_p,c.c_ulong,c.c_ulong,c.c_int,c.c_int,
                                      c.POINTER(c.c_int),c.POINTER(c.c_int),c.POINTER(c.c_ulong)],c.c_int),
            'XFetchName':([c.c_void_p,c.c_ulong,c.POINTER(c.c_void_p)],c.c_int),
            'XMoveWindow':([c.c_void_p,c.c_ulong,c.c_int,c.c_int],c.c_int),
            'XResizeWindow':([c.c_void_p,c.c_ulong,c.c_uint,c.c_uint],c.c_int),
            'XSync':([c.c_void_p,c.c_int],c.c_int),
            'XFree':([c.c_void_p],c.c_int),
            'XCloseDisplay':([c.c_void_p],c.c_int)}
        for name,(args,result) in signatures.items():
            fn=getattr(self.x,name);fn.argtypes=args;fn.restype=result
        self.d=self.x.XOpenDisplay(os.environ['QA_X_DISPLAY'].encode())
        assert self.d, 'Cannot open owned QA display'
        self.root=self.x.XDefaultRootWindow(self.d)

    def close(self):
        self.x.XCloseDisplay(self.d)

    def pid(self, window):
        atom=self.x.XInternAtom(self.d,b'_NET_WM_PID',True)
        actual,n,remaining=c.c_ulong(),c.c_ulong(),c.c_ulong()
        fmt,data=c.c_int(),c.c_void_p()
        self.x.XGetWindowProperty(self.d,window,atom,0,1,False,6,
                                 c.byref(actual),c.byref(fmt),c.byref(n),c.byref(remaining),c.byref(data))
        try:return c.cast(data,c.POINTER(c.c_ulong))[0] if data and n.value else None
        finally:
            if data:self.x.XFree(data)

    def children(self, window):
        root,parent,count=c.c_ulong(),c.c_ulong(),c.c_uint()
        values=c.POINTER(c.c_ulong)()
        self.x.XQueryTree(self.d,window,c.byref(root),c.byref(parent),c.byref(values),c.byref(count))
        try:return [values[i] for i in range(count.value)]
        finally:
            if values:self.x.XFree(values)

    def windows(self,pid):
        result=[]; pending=[self.root]
        while pending:
            window=pending.pop();pending.extend(self.children(window))
            if self.pid(window)!=pid:continue
            a=Attributes()
            if not self.x.XGetWindowAttributes(self.d,window,c.byref(a)) or a.map_state!=2:continue
            x,y,child=c.c_int(),c.c_int(),c.c_ulong()
            self.x.XTranslateCoordinates(self.d,window,self.root,0,0,c.byref(x),c.byref(y),c.byref(child))
            name=c.c_void_p();self.x.XFetchName(self.d,window,c.byref(name))
            try:title=c.string_at(name).decode(errors='replace') if name else ''
            finally:
                if name:self.x.XFree(name)
            rect=[x.value,y.value,x.value+a.width,y.value+a.height]
            row={'hwnd':window,'title':title,'rect':rect,'client':rect,'depth':a.depth}
            if title.startswith('Agent Bubble'):
                row['role']='island' if a.width>300 and a.height>120 else 'capsule'
            result.append(row)
        return result


def windows(pid):
    display=Display()
    try:return display.windows(pid)
    finally:display.close()


def geometry(window, *, position=None, size=None):
    display=Display()
    try:
        if position:display.x.XMoveWindow(display.d,window,*position)
        if size:display.x.XResizeWindow(display.d,window,*size)
        display.x.XSync(display.d,False)
    finally:display.close()
