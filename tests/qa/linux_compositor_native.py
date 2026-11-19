# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Process-scoped X11 geometry and native display captures for isolated QA.

QA_X_DISPLAY must name an owned private display. Captures read the X server's
presented root pixels, never Blender's offscreen screenshot path.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil

from windows_glass_fixture import corner_error, metrics as island_metrics


def metrics(snapshot, role):
    if role != 'capsule':
        return island_metrics(snapshot, role)
    import numpy as np
    from PIL import Image
    window = next(w for w in snapshot['windows'] if w.get('role') == role)
    rgb = np.asarray(Image.open(window['path']).convert('RGB'), dtype=float)
    height, width = rgb.shape[:2]
    # The 44px pill's middle contains sharp prompt glyphs. Measure the empty
    # bed below the label and left of the cat, not those intentional edges.
    bed = rgb[int(height*.68):int(height*.78), int(width*.13):int(width*.79)]
    channel = int(np.argmax(np.mean(bed, axis=(0, 1))))
    signal = np.median(bed[:, :, channel], axis=0)
    x = np.arange(len(signal))
    design = np.column_stack((np.ones_like(x), x/len(x),
                              np.sin(2*np.pi*x/64), np.cos(2*np.pi*x/64),
                              np.sin(2*np.pi*x/8), np.cos(2*np.pi*x/8)))
    fit = np.linalg.lstsq(design, signal, rcond=None)[0]
    low, high = float(np.hypot(*fit[2:4])), float(np.hypot(*fit[4:6]))
    return {'mean_rgb': np.mean(bed, axis=(0, 1)).tolist(),
            'low_frequency': low, 'high_frequency': high,
            'high_low_ratio': high/max(low, .001),
            'sample_region': 'text-free bed below prompt, left of cat'}


def command(*args):
    assert sys.platform.startswith('linux')
    display = os.environ['QA_X_DISPLAY']
    assert display.startswith(':') and display not in (':0', ':1'), display
    env = dict(os.environ, DISPLAY=display)
    return subprocess.check_output(args, env=env, text=True, timeout=20).strip()


def windows(pid):
    if not shutil.which('xdotool'):
        from linux_x11_native import windows as xwindows
        rows = xwindows(pid)
        assert rows, f'No visible X11 windows for QA PID {pid}'
        return rows
    found = []
    for xid in command('xdotool', 'search', '--onlyvisible', '--pid', str(pid)).split():
        title = command('xdotool', 'getwindowname', xid)
        values = dict(line.split('=', 1) for line in
                      command('xdotool', 'getwindowgeometry', '--shell', xid).splitlines())
        x, y, width, height = (int(values[k]) for k in ('X', 'Y', 'WIDTH', 'HEIGHT'))
        row = {'hwnd': int(xid), 'title': title, 'rect': [x, y, x + width, y + height],
               'client': [x, y, x + width, y + height]}
        if title.startswith('Agent Bubble'):
            row['role'] = 'island' if width > 300 and height > 120 else 'capsule'
        found.append(row)
    assert found, f'No visible X11 windows for QA PID {pid}'
    return found


def move(xid, x, y):
    if shutil.which('xdotool'):
        command('xdotool', 'windowmove', '--sync', str(xid), str(x), str(y))
    else:
        from linux_x11_native import geometry
        geometry(xid, position=(x, y))


def resize(xid, width, height):
    if shutil.which('xdotool'):
        command('xdotool', 'windowsize', '--sync', str(xid), str(width), str(height))
    else:
        from linux_x11_native import geometry
        geometry(xid, size=(width, height))


def capture(pid, out):
    from PIL import Image
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    visible = windows(pid)
    path = out / 'desktop.png'
    if shutil.which('import'):
        command('import', '-display', os.environ['QA_X_DISPLAY'], '-window', 'root', str(path))
    else:
        from PIL import ImageGrab
        ImageGrab.grab(xdisplay=os.environ['QA_X_DISPLAY']).save(path)
    with Image.open(path) as desktop:
        width, height = desktop.size
        for window in visible:
            left, top, right, bottom = window['rect']
            assert 0 <= left < right <= width and 0 <= top < bottom <= height, window
            target = out / f"window_{window['hwnd']}.png"
            desktop.crop((left, top, right, bottom)).save(target)
            window['path'] = str(target)
    value = {'desktop': str(path), 'bounds': [0, 0, width, height], 'windows': visible,
             'capture_method': 'X11 root presented pixels; window images are exact crops'}
    (out / 'capture.json').write_text(json.dumps(value, indent=2))
    return value


def install():
    """Fixture-only solid, dual-frequency band and checker parent viewport."""
    import bpy
    import gpu
    from gpu_extras.batch import batch_for_shader
    import math
    assert os.environ.get('MIXAR_QA') == '1'
    state = {'color': (1, 1, 1), 'pattern': 'bands', 'draws': 0, 'cache': None}
    shader = gpu.shader.from_builtin('SMOOTH_COLOR')

    def draw():
        region = bpy.context.region
        key = (region.width, region.height, state['color'], state['pattern'])
        if state['cache'] is None or state['cache'][0] != key:
            vertices, colors = [], []
            step = 16 if state['pattern'] == 'checker' else 1
            ys = range(0, region.height, step) if state['pattern'] == 'checker' else (0,)
            for y in ys:
                top = min(y + step, region.height) if state['pattern'] == 'checker' else region.height
                for x in range(0, region.width, step):
                    right = min(x + step, region.width)
                    value = 1.0
                    if state['pattern'] == 'bands':
                        value = .5 + .22 * math.sin(2 * math.pi * x / 64)
                        value += .22 * math.sin(2 * math.pi * x / 8)
                    elif state['pattern'] == 'checker':
                        value = 1.0 if (x // step + y // step) % 2 else .05
                    rgba = tuple(c * value for c in state['color']) + (1,)
                    vertices.extend(((x, y), (right, y), (right, top),
                                     (x, y), (right, top), (x, top)))
                    colors.extend((rgba,) * 6)
            state['cache'] = (key, batch_for_shader(shader, 'TRIS', {'pos': vertices, 'color': colors}))
        gpu.state.blend_set('NONE')
        shader.bind()
        state['cache'][1].draw(shader)
        state['draws'] += 1

    state['handler'] = bpy.types.SpaceView3D.draw_handler_add(draw, (), 'WINDOW', 'POST_PIXEL')
    bpy.app.driver_namespace['qa_linux_compositor'] = state
    return {'installed': True}


def backdrop(rgb, pattern='bands'):
    import bpy
    assert pattern in ('bands', 'solid', 'checker')
    state = bpy.app.driver_namespace['qa_linux_compositor']
    state.update(color=tuple(rgb), pattern=pattern)
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()
    return state['draws']


def remove():
    import bpy
    state = bpy.app.driver_namespace.pop('qa_linux_compositor', None)
    if state:
        bpy.types.SpaceView3D.draw_handler_remove(state['handler'], 'WINDOW')
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
