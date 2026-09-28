#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit G/R/S regression during onboarding in an isolated Dev QA app.

QA_HARNESS=/path/to/mixar-qa-harness python3 tests/qa/onboarding_transform_e2e.py
Requires Pillow; writes screenshots to QA_SCENARIO_OUT (default /tmp/onboarding-transform).
"""
import os
from pathlib import Path
import sys

from PIL import Image

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/onboarding-transform'))
SETUP = """
from mixar.modules.onboarding.core.tour.session import current
win = drv.main_window()
area = next(a for a in win.screen.areas if a.type == 'VIEW_3D')
region = next(r for r in area.regions if r.type == 'WINDOW')
"""


def assert_clear_viewport(path):
    """The broken status backdrop forms a tall, uniformly dark center strip."""
    im = Image.open(path).convert('RGB')
    x = im.width // 2
    longest = run = 0
    for y in range(im.height // 5, im.height * 4 // 5):
        pixels = [im.getpixel((xx, y)) for xx in range(x - 8, x + 9)]
        dark = max(pixels[0]) < 60
        flat = all(max(abs(a-b) for a, b in zip(p, pixels[0])) <= 2 for p in pixels)
        run = run + 1 if dark and flat else 0
        longest = max(longest, run)
    assert longest < im.height // 4, f'Viewport obscured by {longest}px status backdrop: {path}'
    return longest


def capture(qa, name):
    path = OUT / f'{name}.png'
    qa.snap(str(path))
    return assert_clear_viewport(path)


def begin(qa):
    return qa.eval(SETUP + """
def start():
    if current() is not None:
        current().stop('cancelled')
        yield .2
    with bpy.context.temp_override(window=win, area=area, region=region):
        for obj in win.view_layer.objects:
            obj.select_set(False)
        cube = bpy.data.objects['Cube']
        cube.select_set(True)
        win.view_layer.objects.active = cube
        cube.location = (0, 0, 0)
        cube.rotation_euler = (0, 0, 0)
        cube.scale = (1, 1, 1)
        assert bpy.ops.mixar.onboarding_tour('INVOKE_DEFAULT', silent=True) == {'RUNNING_MODAL'}
    current().runner._jump('shortcuts')
    current().clock.seek_ms(25000)
    current().runner.tick()
    current().runner.set_user_paused(True)
    yield .5
    drv.move_to(win, region.x + region.width // 2, region.y + region.height // 2)
    yield .2
    return True
result = start()
""")


def transform(qa, key, suffix, expected, name):
    qa.press(key)
    qa.eval("def settle():\n yield .3\n return True\nresult=settle()")
    capture(qa, name)
    qa.eval(SETUP + "assert current().running and current().runner.beat.id == 'shortcuts'; result=True")
    for k in suffix:
        if k in {'ONE', 'TWO', 'FIVE'}:
            # Numeric input consumes the character, not just the physical key.
            digit = {'ONE': '1', 'TWO': '2', 'FIVE': '5'}[k]
            qa.eval(f"drv.type_char(drv.main_window(), {digit!r}); result=True")
        else:
            qa.press(k)
    qa.wait(expected, timeout=5)
    return True


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.step('start_shortcut_beat', begin, qa)
    qa.step('before', capture, qa, 'before')
    try:
        qa.step('move_cancel', transform, qa, 'G', ['ESC'],
                "tuple(bpy.data.objects['Cube'].location) == (0, 0, 0)", 'move-cancel')
        qa.step('move_confirm', transform, qa, 'G', ['X', 'ONE', 'RET'],
                "abs(bpy.data.objects['Cube'].location.x - 1) < .001", 'move')
        qa.step('rotate_confirm', transform, qa, 'R', ['Z', 'ONE', 'FIVE', 'RET'],
                "abs(bpy.data.objects['Cube'].rotation_euler.z - 0.261799) < .001", 'rotate')
        qa.step('scale_confirm', transform, qa, 'S', ['TWO', 'RET'],
                "all(abs(v - 2) < .001 for v in bpy.data.objects['Cube'].scale)", 'scale')
        qa.step('after', capture, qa, 'after')
        return {'screenshots': str(OUT)}
    finally:
        qa.press('ESC')
        qa.eval(SETUP + "\nif current() is not None: current().stop('cancelled')\nresult=True")


if __name__ == '__main__':
    run_scenario('onboarding_transform', run)
