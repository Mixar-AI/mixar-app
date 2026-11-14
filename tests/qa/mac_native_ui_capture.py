# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Passive macOS compositor evidence for one identity-checked QA window.

Load in the QA app, call ``start(path, expected, role='island')`` on its main
thread, then poll ``status()`` through the harness. ``expected`` contains the
controller's pid, profile, binary and qa_port. AppKit observation stays on the
main thread; the bounded screencapture subprocess and file IO run on a worker.
No input, activation, redraw, permission request or privacy-setting change.
Success means a correctly sized native PNG exists, not that vision passed.
"""

import ctypes as ct
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import threading
import time


class Point(ct.Structure):
    _fields_ = [('x', ct.c_double), ('y', ct.c_double)]


class Size(ct.Structure):
    _fields_ = [('width', ct.c_double), ('height', ct.c_double)]


class Rect(ct.Structure):
    _fields_ = [('origin', Point), ('size', Size)]


_lock = threading.Lock()
_state = {'done': True, 'available': False, 'reason': 'not started'}
_worker = None


def _identity(expected):
    import bpy

    assert sys.platform == 'darwin', 'native capture requires macOS'
    assert threading.current_thread() is threading.main_thread(), 'observe AppKit on main thread'
    actual = {'pid': os.getpid(), 'profile': os.environ.get('MIXAR_USER_RESOURCES'),
              'binary': bpy.app.binary_path, 'qa_port': int(os.environ.get('MIXAR_QA_PORT', 0))}
    assert os.environ.get('MIXAR_QA') == '1', 'capture requires an isolated QA app'
    assert actual['pid'] == expected['pid'] and actual['qa_port'] == expected['qa_port'], 'wrong QA process'
    assert actual['profile'] and Path(actual['profile']).resolve() == Path(expected['profile']).resolve(), 'wrong QA profile'
    assert Path(actual['binary']).resolve() == Path(expected['binary']).resolve(), 'wrong QA executable'
    return actual


class Observer:
    def __init__(self):
        self.objc = ct.CDLL('/usr/lib/libobjc.A.dylib')
        self.objc.objc_getClass.argtypes = [ct.c_char_p]
        self.objc.objc_getClass.restype = ct.c_void_p
        self.objc.sel_registerName.argtypes = [ct.c_char_p]
        self.objc.sel_registerName.restype = ct.c_void_p
        self.objc.object_getClass.argtypes = [ct.c_void_p]
        self.objc.object_getClass.restype = ct.c_void_p
        self.objc.class_getName.argtypes = [ct.c_void_p]
        self.objc.class_getName.restype = ct.c_char_p
        self.cg = ct.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
        self.cg.CGPreflightScreenCaptureAccess.argtypes = []
        self.cg.CGPreflightScreenCaptureAccess.restype = ct.c_bool
        self.cg.CGWindowListCopyWindowInfo.argtypes = [ct.c_uint32, ct.c_uint32]
        self.cg.CGWindowListCopyWindowInfo.restype = ct.c_void_p
        self.cf = ct.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        self.cf.CFRelease.argtypes = [ct.c_void_p]

    def cls(self, name):
        return self.objc.objc_getClass(name.encode())

    def send(self, obj, name, result=ct.c_void_p, args=(), values=()):
        call = ct.CFUNCTYPE(result, ct.c_void_p, ct.c_void_p, *args)(('objc_msgSend', self.objc))
        return call(obj, self.objc.sel_registerName(name.encode()), *values)

    def items(self, array):
        return [self.send(array, 'objectAtIndex:', args=(ct.c_ulong,), values=(i,))
                for i in range(self.send(array, 'count', ct.c_ulong))] if array else []

    def text(self, obj):
        value = self.send(obj, 'UTF8String', ct.c_char_p) if obj else None
        return value.decode('utf-8', errors='replace') if value else ''

    def get(self, obj, key):
        key = self.send(self.cls('NSString'), 'stringWithUTF8String:', args=(ct.c_char_p,), values=(key.encode(),))
        return self.send(obj, 'objectForKey:', args=(ct.c_void_p,), values=(key,))

    def class_name(self, obj):
        return self.objc.class_getName(self.objc.object_getClass(obj)).decode() if obj else ''

    def material(self, win):
        root = self.send(win, 'contentView')
        root_class = self.class_name(root).removeprefix('NSKVONotifying_')
        children = self.items(self.send(root, 'subviews'))
        host = self.send(root, 'contentView') if root_class == 'NSGlassEffectView' else (children[0] if children else None)
        layer = self.send(host, 'layer') if host else None
        return {'container': root_class, 'host': self.class_name(host),
                'host_window_matches': self.send(host, 'window') == win if host else False,
                'window_opaque': bool(self.send(win, 'isOpaque', ct.c_bool)),
                'background_alpha': self.send(self.send(win, 'backgroundColor'), 'alphaComponent', ct.c_double),
                'metal_opaque': bool(self.send(layer, 'isOpaque', ct.c_bool)) if layer else None,
                'pixel_format': self.send(layer, 'pixelFormat', ct.c_ulong) if self.class_name(layer) == 'CAMetalLayer' else None}

    def cg_window(self, number):
        value = self.cg.CGWindowListCopyWindowInfo(8, number)  # IncludingWindow, exact ID.
        try:
            rows = self.items(value)
            if len(rows) != 1:
                return None
            row = rows[0]
            bounds = self.get(row, 'kCGWindowBounds')
            return {'number': self.send(self.get(row, 'kCGWindowNumber'), 'unsignedIntValue', ct.c_uint),
                    'pid': self.send(self.get(row, 'kCGWindowOwnerPID'), 'intValue', ct.c_int),
                    'bounds': [self.send(self.get(bounds, k), 'doubleValue', ct.c_double)
                               for k in ('X', 'Y', 'Width', 'Height')]}
        finally:
            if value:
                self.cf.CFRelease(value)


def observe(expected, role='island'):
    identity = _identity(expected)
    assert role in ('island', 'pill', 'main'), role
    observer = Observer()
    screens = observer.items(observer.send(observer.cls('NSScreen'), 'screens'))
    assert screens, 'no native screen'
    primary = observer.send(screens[0], 'frame', Rect)
    primary_top = primary.origin.y + primary.size.height
    app = observer.send(observer.cls('NSApplication'), 'sharedApplication')
    windows = []
    for win in observer.items(observer.send(app, 'windows')):
        if not observer.send(win, 'isVisible', ct.c_bool) or observer.send(win, 'isMiniaturized', ct.c_bool):
            continue
        title = observer.text(observer.send(win, 'title'))
        frame = observer.send(win, 'frame', Rect)
        bounds = [frame.origin.x, primary_top - frame.origin.y - frame.size.height,
                  frame.size.width, frame.size.height]
        bubble = title.startswith('Agent Bubble')
        kind = ('island' if frame.size.height > 100 else 'pill') if bubble else 'main'
        if kind != role or (kind == 'main' and (bounds[2] < 500 or bounds[3] < 400)):
            continue
        number = observer.send(win, 'windowNumber', ct.c_long)
        backing = observer.send(win, 'backingScaleFactor', ct.c_double)
        assert number > 0 and backing > 0 and all(math.isfinite(x) for x in bounds)
        cg = observer.cg_window(number)
        if cg:
            assert cg['pid'] == identity['pid'] and cg['number'] == number, 'native window ownership changed'
            assert all(abs(a-b) <= 1 for a, b in zip(cg['bounds'], bounds)), 'CG/AppKit geometry disagreement'
        windows.append({'number': number, 'title': title, 'role': kind, 'bounds_points': bounds,
                        'backing_scale': backing, 'cg': cg,
                        'material': observer.material(win) if bubble else None})
    assert len(windows) == 1, f'Expected one visible {role} window, found {len(windows)}'
    return {'identity': identity, 'window': windows[0],
            'screen_capture_preflight': bool(observer.cg.CGPreflightScreenCaptureAccess()),
            'permission_requested': False}


def _capture(path, observation, timeout):
    global _state
    started = time.monotonic()
    result = dict(observation, done=False, available=False, path=str(path),
                  mode='passive exact owned window; macOS compositor')
    window = observation['window']
    command = ['/usr/sbin/screencapture', '-x', '-o', '-l', str(window['number']), str(path)]
    result['command'] = command
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        result.update(returncode=done.returncode, stderr=done.stderr.strip())
        if done.returncode:
            raise RuntimeError('native capture unavailable: ' + (done.stderr.strip() or str(done.returncode)))
        assert path.is_file() and not path.is_symlink(), 'native capture did not produce a regular file'
        data = path.read_bytes()
        assert len(data) > 33 and data[:8] == b'\x89PNG\r\n\x1a\n' and data[12:16] == b'IHDR', 'capture is not a PNG'
        size = list(struct.unpack('>II', data[16:24]))
        expected = [round(v * window['backing_scale']) for v in window['bounds_points'][2:]]
        assert all(abs(a-b) <= 2 for a, b in zip(size, expected)), f'native capture dimensions {size}, expected {expected}'
        result.update(available=True, size=size, sha256=hashlib.sha256(data).hexdigest())
    except BaseException as error:
        result['error'] = f'{type(error).__name__}: {error}'
    finally:
        result.update(done=True, seconds=time.monotonic()-started)
        try:
            path.with_suffix('.capture.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        except BaseException as error:
            result.update(available=False, receipt_error=repr(error))
        with _lock:
            _state = result


def start(path, expected, role='island', timeout=10):
    global _worker, _state
    assert 1 <= timeout <= 20, 'capture timeout must be bounded'
    assert _worker is None or not _worker.is_alive(), 'another owned capture is pending'
    path = Path(path)
    assert path.is_absolute() and path == path.resolve() and path.suffix == '.png'
    assert path.parent.is_dir() and not path.exists() and not path.is_symlink(), 'capture needs a new owned path'
    assert not path.with_suffix('.capture.json').exists(), 'capture receipt already exists'
    observation = observe(expected, role)
    with _lock:
        _state = dict(observation, done=False, available=False, path=str(path))
    _worker = threading.Thread(target=_capture, args=(path, observation, timeout),
                               name='qa-owned-native-capture', daemon=True)
    _worker.start()
    return status()


def status():
    with _lock:
        return dict(_state)


def verify_stable(expected, role='island'):
    """Call on the main thread after completion; never accept a moved/reused ID."""
    captured = status()
    assert captured['done'] and captured['available'], captured
    after = observe(expected, role)
    assert captured['identity'] == after['identity'] and captured['window'] == after['window'], 'native window changed during capture'
    return dict(captured, geometry_stable=True)


def capture_controller(qa, path, expected, role='island', timeout=10):
    """Capture from the authorized controller; only observation runs in Mixar.

    Screen Recording belongs to the calling identity. Granting Codex access
    does not grant the separately signed QA app access. This path checks the
    controller's existing grant; it never requests one or switches identity.
    """
    assert sys.platform == 'darwin' and 1 <= timeout <= 20
    cg = ct.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
    cg.CGPreflightScreenCaptureAccess.argtypes = []
    cg.CGPreflightScreenCaptureAccess.restype = ct.c_bool
    assert cg.CGPreflightScreenCaptureAccess(), 'controller Screen Recording unavailable; no permission request made'
    path = Path(path)
    assert path.is_absolute() and path == path.resolve() and path.suffix == '.png'
    assert path.parent.is_dir() and not path.exists() and not path.is_symlink(), 'capture needs a new owned path'
    assert not path.with_suffix('.capture.json').exists(), 'capture receipt already exists'
    helper = str(Path(__file__).resolve())

    def app_observation():
        return qa.eval(f'ns={{}}\nexec(compile(open({helper!r}).read(),{helper!r},"exec"),ns)\n'
                       f'result=ns["observe"]({expected!r},{role!r})')

    before = app_observation()
    # This synchronous wait belongs to the external controller, never Blender.
    _capture(path, before, timeout)
    captured = status()
    captured.update(capture_identity='controller', controller_screen_capture_preflight=True)
    try:
        assert captured['done'] and captured['available'], captured
        after = app_observation()
        assert before['identity'] == after['identity'] and before['window'] == after['window'], 'native window changed during capture'
        captured['geometry_stable'] = True
        return captured
    except BaseException as error:
        captured.update(available=False, error=repr(error))
        raise
    finally:
        path.with_suffix('.capture.json').write_text(json.dumps(captured, indent=2), encoding='utf-8')
