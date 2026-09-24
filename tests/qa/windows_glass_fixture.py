# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Parent-framebuffer fixture and process-scoped Windows compositor captures."""

import ctypes
from ctypes import wintypes
import math
from pathlib import Path


def install():
    """Draw two spatial frequencies into the real viewport below the island."""
    import bpy
    import gpu
    from gpu_extras.batch import batch_for_shader

    assert __import__('os').environ.get('MIXAR_QA') == '1'
    state = {'color': (1.0, 0.1, 0.04), 'window_colors': {}, 'draws': 0, 'cache': None}
    shader = gpu.shader.from_builtin('SMOOTH_COLOR')

    def draw():
        region = bpy.context.region
        rgb = state['window_colors'].get(bpy.context.window.as_pointer(), state['color'])
        size = (region.width, region.height, rgb)
        if not state['cache'] or state['cache'][0] != size:
            vertices, colors = [], []
            for x in range(region.width):
                value = 0.5 + 0.22 * math.sin(2 * math.pi * x / 64)
                value += 0.22 * math.sin(2 * math.pi * x / 8)
                color = tuple(c * value for c in rgb) + (1,)
                vertices.extend(((x, 0), (x + 1, 0), (x + 1, region.height),
                                 (x, 0), (x + 1, region.height), (x, region.height)))
                colors.extend((color,) * 6)
            batch = batch_for_shader(shader, 'TRIS', {'pos': vertices, 'color': colors})
            state['cache'] = (size, batch)
        gpu.state.blend_set('NONE')
        shader.bind()
        state['cache'][1].draw(shader)
        state['draws'] += 1

    state['handler'] = bpy.types.SpaceView3D.draw_handler_add(draw, (), 'WINDOW', 'POST_PIXEL')
    bpy.app.driver_namespace['qa_windows_glass'] = state
    return {'installed': True}


def color(rgb, window=None):
    import bpy

    state = bpy.app.driver_namespace['qa_windows_glass']
    if window is None:
        state['color'] = tuple(rgb)
    else:
        state['window_colors'][window] = tuple(rgb)
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()
    return {'color': tuple(rgb), 'draws_before': state['draws']}


def remove():
    import bpy

    state = bpy.app.driver_namespace.pop('qa_windows_glass', None)
    if state:
        bpy.types.SpaceView3D.draw_handler_remove(state['handler'], 'WINDOW')
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()


def _api():
    user = ctypes.WinDLL('user32', use_last_error=True)
    # Match the physical desktop pixels captured by Pillow at non-100% scaling.
    user.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    user.BringWindowToTop.argtypes = [wintypes.HWND]
    user.GetForegroundWindow.restype = wintypes.HWND
    user.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user.WindowFromPoint.argtypes = [wintypes.POINT]
    user.WindowFromPoint.restype = wintypes.HWND
    return user


def windows(pid):
    user = _api()
    found = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd, _):
        owner = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid or not user.IsWindowVisible(hwnd):
            return True
        title = ctypes.create_unicode_buffer(512)
        user.GetWindowTextW(hwnd, title, len(title))
        rect, client, origin = wintypes.RECT(), wintypes.RECT(), wintypes.POINT()
        user.GetWindowRect(hwnd, ctypes.byref(rect))
        user.GetClientRect(hwnd, ctypes.byref(client))
        user.ClientToScreen(hwnd, ctypes.byref(origin))
        if rect.right > rect.left and rect.bottom > rect.top:
            found.append({'hwnd': int(hwnd), 'title': title.value,
                          'rect': [rect.left, rect.top, rect.right, rect.bottom],
                          'client': [origin.x, origin.y, origin.x + client.right,
                                     origin.y + client.bottom],
                          'style': user.GetWindowLongPtrW(hwnd, -16),
                          'exstyle': user.GetWindowLongPtrW(hwnd, -20)})
        return True

    callback = callback_type(visit)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    if not user.EnumWindows(callback, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    bubbles = [window for window in found if window['title'].startswith('Agent Bubble')]
    for window in bubbles:
        width = window['rect'][2] - window['rect'][0]
        height = window['rect'][3] - window['rect'][1]
        # wm_window_title uses the same title for the expanded island and pill
        # on Windows; distinguish their stable region geometry instead.
        window['role'] = 'island' if height > 120 and width > 300 else 'capsule'
    return found


def move(hwnd, x, y):
    # A native move isolates backdrop tracking from the separate drag gesture.
    if not _api().SetWindowPos(hwnd, None, x, y, 0, 0, 0x1 | 0x4 | 0x10):
        raise ctypes.WinError(ctypes.get_last_error())


def resize(hwnd, width, height):
    # Physical pixels, like the desktop capture. The bubble_set_size operator
    # takes logical units, whereas Window.width is physical at non-100% DPI.
    if not _api().SetWindowPos(hwnd, None, 0, 0, width, height, 0x2 | 0x4 | 0x10):
        raise ctypes.WinError(ctypes.get_last_error())


def foreground(pid):
    """Keep terminal/approval windows out of the isolated app's screenshots."""
    user = _api()
    visible = windows(pid)
    parent = max((w for w in visible if not w.get('role')),
                 key=lambda w: (w['rect'][2] - w['rect'][0]) * (w['rect'][3] - w['rect'][1]))
    kernel = ctypes.WinDLL('kernel32')
    current_thread = kernel.GetCurrentThreadId()
    foreground_thread = user.GetWindowThreadProcessId(user.GetForegroundWindow(), None)
    attached = current_thread != foreground_thread and user.AttachThreadInput(
        current_thread, foreground_thread, True)
    try:
        user.BringWindowToTop(parent['hwnd'])
        user.SetForegroundWindow(parent['hwnd'])
    finally:
        if attached:
            user.AttachThreadInput(current_thread, foreground_thread, False)


def capture(pid, out):
    from PIL import ImageGrab

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    visible = windows(pid)
    assert visible, f'No visible windows for QA process {pid}'
    user = _api()
    occluded = []
    for window in visible:
        if not window.get('role'):
            continue
        left, top, right, bottom = window['rect']
        for x, y in ((left + 8, top + 8), (right - 9, top + 8),
                     ((left + right) // 2, (top + bottom) // 2),
                     (left + 8, bottom - 9), (right - 9, bottom - 9)):
            hwnd = user.WindowFromPoint(wintypes.POINT(x, y))
            owner = wintypes.DWORD()
            user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value != pid:
                occluded.append(f'QA {window["role"]} is occluded at {(x, y)}')
    bounds = [min(w['rect'][0] for w in visible) - 8,
              min(w['rect'][1] for w in visible) - 8,
              max(w['rect'][2] for w in visible) + 8,
              max(w['rect'][3] for w in visible) + 8]
    desktop = ImageGrab.grab(bbox=tuple(bounds), include_layered_windows=True, all_screens=True)
    desktop.save(out / 'desktop.png')
    for window in visible:
        rect = window['rect']
        crop = (rect[0] - bounds[0], rect[1] - bounds[1],
                rect[2] - bounds[0], rect[3] - bounds[1])
        path = out / f"window_{window['hwnd']}.png"
        desktop.crop(crop).save(path)
        window['path'] = str(path)
    assert not occluded, f'{occluded}; screenshot: {out / "desktop.png"}'
    return {'desktop': str(out / 'desktop.png'), 'bounds': bounds, 'windows': visible}


def metrics(snapshot, role):
    """Tint preserves the high/low ratio; spatial frost suppresses the high band."""
    import numpy as np
    from PIL import Image

    window = next(w for w in snapshot['windows'] if w.get('role') == role)
    rgb = np.asarray(Image.open(window['path']).convert('RGB'), dtype=float)
    height, width = rgb.shape[:2]
    center = rgb[int(height * .42):int(height * .64), int(width * .15):int(width * .85)]
    channel = int(np.argmax(np.mean(center, axis=(0, 1))))
    signal = np.median(center[:, :, channel], axis=0)
    x = np.arange(len(signal))
    design = np.column_stack((np.ones_like(x), x / max(len(x), 1),
                              np.sin(2 * np.pi * x / 64), np.cos(2 * np.pi * x / 64),
                              np.sin(2 * np.pi * x / 8), np.cos(2 * np.pi * x / 8)))
    fit = np.linalg.lstsq(design, signal, rcond=None)[0]
    low, high = float(np.hypot(*fit[2:4])), float(np.hypot(*fit[4:6]))
    header = rgb[4:max(5, int(height * .22)), 8:-8]
    edges = np.max(np.abs(np.diff(header, axis=1)), axis=2)
    return {'mean_rgb': np.mean(center, axis=(0, 1)).tolist(),
            'low_frequency': low, 'high_frequency': high,
            'high_low_ratio': high / max(low, .001),
            'foreground_edge_p99': float(np.percentile(edges, 99))}


def corner_error(snapshot, role):
    """The fixture is constant vertically, including above/below rounded corners."""
    import numpy as np
    from PIL import Image

    window = next(w for w in snapshot['windows'] if w.get('role') == role)
    pixels = np.asarray(Image.open(snapshot['desktop']).convert('RGB'), dtype=int)
    left, top, right, bottom = window['rect']
    left -= snapshot['bounds'][0]
    right -= snapshot['bounds'][0]
    top -= snapshot['bounds'][1]
    bottom -= snapshot['bounds'][1]
    pairs = ((left + 1, top + 1, top - 2), (right - 2, top + 1, top - 2),
             (left + 1, bottom - 2, bottom + 1), (right - 2, bottom - 2, bottom + 1))
    return max(int(np.abs(pixels[y, x] - pixels[outside, x]).max())
               for x, y, outside in pairs)
