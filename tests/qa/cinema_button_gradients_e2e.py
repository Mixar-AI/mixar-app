#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-login, no-credit native Cinema painter fixture for an isolated QA app.

Set QA_HARNESS, MIXAR_QA_PORT, QA_SCENARIO_OUT. Exercises both actual widget
painters without starting a Director session. Inspect the four emitted PNGs.
"""
import os
from pathlib import Path
import statistics
import sys
import time

from PIL import Image

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/cinema-button-gradients'))

FIXTURE = '''
class QA_OT_cinema_gradients(bpy.types.Operator):
    bl_idname = 'qa.cinema_gradients'
    bl_label = 'Cinema gradient QA'
    def execute(self, context):
        return {'FINISHED'}
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=360)
    def draw(self, context):
        for host in ('Zen', 'Engine'):
            for active in (False, True):
                self.layout.label(text=host + (' active' if active else ' idle'))
                row = self.layout.mixar_surface(theme='ZEN', density='COMPACT').row()
                row.scale_y = 2
                if host == 'Zen':
                    row.operator('mixar.director_enter', text='Cinema Mode')
                    row.mixar_style(component='TOOLBAR', variant='PRIMARY', selected=active)
                else:
                    op = row.operator('wm.context_set_boolean', text='Cinema Mode')
                    op.data_path = 'scene.render.film_transparent'
                    op.value = context.scene.render.film_transparent
                    row.mixar_topbar_element(kind='CINEMA_PILL', active=active)
bpy.utils.register_class(QA_OT_cinema_gradients)
w = drv.main_window()
a = next(a for a in w.screen.areas if a.type == 'VIEW_3D')
r = next(r for r in a.regions if r.type == 'WINDOW')
with bpy.context.temp_override(window=w, area=a, region=r):
    bpy.ops.qa.cinema_gradients('INVOKE_DEFAULT')
result = True
'''


def measure(path, active):
    with Image.open(path).convert('RGB') as im:
        w, h = im.size
        left = im.getpixel((int(w * .2), int(h * .2)))
        right = im.getpixel((int(w * .8), int(h * .2)))
        assert right[1] > left[1] + 10, (left, right)
        ink = sorted((x, c[0]) for y in range(int(h * .25), int(h * .75))
                     for x in range(w) if (c := im.getpixel((x, y)))[0] > 65
                     and max(c) - min(c) <= 2)
        assert len(ink) > 30, 'Text missing'
        n = max(1, len(ink) // 5)
        dark = statistics.median(c for _, c in ink[:n])
        light = statistics.median(c for _, c in ink[-n:])
        assert light - dark > (25 if active else 60), (dark, light)
        return {'background_left': left, 'background_right': right,
                'text_left': dark, 'text_right': light}


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.eval(FIXTURE)
    try:
        qa.wait("len(drv.find(text='Cinema Mode', popup=True)) == 4", timeout=10)
        qa.eval('w=drv.main_window(); drv.move_to(w,20,20); result=True')
        time.sleep(.5)
        results = {}
        for i, name in enumerate(('Zen-idle', 'Zen-active', 'Engine-idle', 'Engine-active')):
            path = OUT / (name + '.png')
            query = {'text': 'Cinema Mode', 'popup': True, 'index': i}
            for _ in range(2):
                qa.cmd('snap', path=str(path), target=query, margin=0)
                time.sleep(.2)
            results[name] = measure(path, i % 2 == 1)
        for host in ('Zen', 'Engine'):
            assert results[host+'-active']['background_right'][1] > results[host+'-idle']['background_right'][1] + 20
        return {'samples': results}
    finally:
        qa.press('ESC')
        qa.eval('bpy.utils.unregister_class(QA_OT_cinema_gradients); result=True')


if __name__ == '__main__':
    run_scenario('cinema_button_gradients', run)
