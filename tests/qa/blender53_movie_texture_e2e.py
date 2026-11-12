#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit 5.3 tour texture ownership, pixels and backward-seek replay.

Run against an isolated QA app with QA_HARNESS, MIXAR_QA_PORT and
QA_SCENARIO_OUT. Requires ffmpeg. Inspect the red/blue viewport screenshots.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario


def run(qa):
    out = Path(os.environ['QA_SCENARIO_OUT'])
    out.mkdir(parents=True, exist_ok=True)
    clip = out / 'red-blue.mp4'
    ffmpeg = shutil.which('ffmpeg')
    assert ffmpeg, 'ffmpeg required for the disposable movie fixture'
    subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y',
                    '-f', 'lavfi', '-i', 'color=red:size=320x180:rate=12:duration=1',
                    '-f', 'lavfi', '-i', 'color=blue:size=320x180:rate=12:duration=1',
                    '-filter_complex', '[0:v][1:v]concat=n=2:v=1:a=0[v]',
                    '-map', '[v]', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(clip)], check=True)
    qa.cmd('dismiss_splash')
    qa.cmd('dismiss_chat')
    qa.eval(f'''
import os
assert os.environ.get('MIXAR_QA') == '1'
assert bpy.app.version[:2] == (5, 3)
from mixar.modules.onboarding.core.tour.video import MovieTexture
from gpu_extras.presets import draw_texture_2d
import gpu
movie = MovieTexture({str(clip)!r})
drv._qa_movie53 = movie
drv._qa_movie53_first = None
drv._qa_movie53_frame = 1
drv._qa_movie53_pixels = None
def draw_movie():
    if drv._qa_movie53_pixels is not None:
        texture = drv._qa_movie53_texture
    else:
        assert movie._decode(drv._qa_movie53_frame)
        texture = movie._current_texture()
        assert texture is not None
        if drv._qa_movie53_first is None:
            drv._qa_movie53_first = texture
        assert texture is drv._qa_movie53_first, 'per-frame GPU allocation churn'
        pixels = texture.read()
        pixels.dimensions = texture.width * texture.height * 4
        drv._qa_movie53_pixels = [v / 255.0 for v in pixels[:4]]
        drv._qa_movie53_texture = texture
    draw_texture_2d(texture, (60, 80), 480, 270)
drv._qa_movie53_draw = bpy.types.SpaceView3D.draw_handler_add(draw_movie, (), 'WINDOW', 'POST_PIXEL')
for area in drv.main_window().screen.areas:
    if area.type == 'VIEW_3D': area.tag_redraw()
result = True
''')
    rows = []
    try:
        for frame, channel in ((1, 0), (18, 2), (2, 0), (24, 2)):
            qa.eval(f'''
drv._qa_movie53_frame = {frame}
drv._qa_movie53_pixels = None
for area in drv.main_window().screen.areas:
    if area.type == 'VIEW_3D': area.tag_redraw()
result = True
''')
            qa.wait('drv._qa_movie53_pixels is not None', timeout=10)
            pixel = qa.eval('result = drv._qa_movie53_pixels')
            # The fixture uses an 8-bit Non-Color texture (UBYTE readback).
            assert pixel[channel] > .8 and pixel[2 if channel == 0 else 0] < .15, pixel
            rows.append({'frame': frame, 'pixel': pixel})
            qa.snap(str(out / f'frame-{frame}.png'))
    finally:
        qa.eval('''
bpy.types.SpaceView3D.draw_handler_remove(drv._qa_movie53_draw, 'WINDOW')
drv._qa_movie53_first = None
drv._qa_movie53_texture = None
drv._qa_movie53.close()
result = True
''')
    (out / 'pixels.json').write_text(json.dumps(rows, indent=2))
    return {'frames': rows, 'texture_reused': True, 'backend_turns': 0}


if __name__ == '__main__':
    run_scenario('blender53_movie_texture_e2e', run)
