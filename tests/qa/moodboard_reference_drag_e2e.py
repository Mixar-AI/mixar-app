#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit reference drag-enter / drop replay on an isolated Dev app.

Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT. The drag-enter hook
exercises the same preview dispatcher as native GHOST events, separately
from the real queued file-drop hook, proving the board opens BEFORE release.
Screenshots stay in the requested temporary output directory.
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
sys.path.insert(0, str(Path(__file__).parent))
from moodboard_drawer_e2e import (
    SETUP, drop, geometry, media, png, settle, switch_mode, target, toggle,
    verify_viewport,
)
from moodboard_tab_sidebar_e2e import sidebar


def hover(qa, path):
    qa.eval(f'drv.main_window().mixar_qa_drag_file(filepath={str(path)!r}); result=True')


def capture(qa, out, name):
    qa.eval(SETUP + f'''
def capture_frame():
    for region in area.regions:
        region.tag_redraw()
    yield .4
    with bpy.context.temp_override(window=win):
        result = win.mixar_qa_capture_frame(filepath={str(out / (name + '.png'))!r},
            x=area.x, y=area.y, width=area.width, height=area.height)
    return result
result=capture_frame()
''')


def canvas_state(qa):
    return qa.eval(SETUP + '''
result = {
    'width': bpy.context.window_manager.mixar_moodboard_drawer_width,
    'view': [list(drawer.view2d.region_to_view(0, 0)),
             list(drawer.view2d.region_to_view(drawer.width, drawer.height))],
}
''')


def assert_no_import(qa, before):
    assert media(qa) == before, 'Drag hover imported a reference before release'


def run(qa):
    qa.wait("hasattr(bpy.context.window_manager, 'mixar_moodboard_drawer_amount')", timeout=30)
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/moodboard-reference-drag'))
    out.mkdir(parents=True, exist_ok=True)
    image = png(out / 'reference.PNG', (60, 180, 110), width=240, height=160)
    ffmpeg = shutil.which('ffmpeg')
    assert ffmpeg, 'This image AND video regression requires ffmpeg'
    movie = out / 'reference-video.mp4'
    subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y',
                    '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=12', '-t', '1',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(movie)], check=True)
    qa.eval('bpy.ops.mixar.agent_bubble_purge_windows(); result=True')
    if geometry(qa)['workspace'] != 'Zen Mode':
        switch_mode(qa, 'mixar.set_ui_mode_ai', 'Zen Mode')
    settle(qa, round(geometry(qa)['amount']))
    if geometry(qa)['amount'] > .02:
        toggle(qa, 0)
    old_sidebar = qa.eval(SETUP + 'result=area.spaces.active.show_region_ui')
    before = media(qa)
    viewport = geometry(qa)
    capture(qa, out, 'before-drag')

    def rejects_non_media():
        for name in ('notes.txt', 'scene.mixar', 'mesh.glb'):
            hover(qa, out / name)
        time.sleep(.4)
        assert geometry(qa)['amount'] < .002
        assert_no_import(qa, before)

    qa.step('non_media_hover_keeps_drawer_closed', rejects_non_media)

    def previews_image():
        hover(qa, image)
        settle(qa, 1)
        assert_no_import(qa, before)
        verify_viewport(qa, viewport)
        assert target(qa, 'moodboard_drawer_panel')['rect'][0] < viewport['area'][2] - 100

    qa.step('image_hover_opens_before_drop', previews_image)
    capture(qa, out, 'image-hover-before-release')

    def repeated_hover():
        state = canvas_state(qa)
        hover(qa, image)
        hover(qa, movie)
        time.sleep(.4)
        assert geometry(qa)['amount'] > .998
        assert canvas_state(qa) == state, 'Hover reset drawer width or canvas pan/zoom'
        assert_no_import(qa, before)

    qa.step('repeated_hover_preserves_open_board', repeated_hover)

    def cancel_hover():
        # Preview owns no drag payload or imported media. Esc must not turn
        # this preview into a drop, and the revealed board remains available.
        qa.press('ESC')
        time.sleep(.2)
        assert_no_import(qa, before)
        assert geometry(qa)['amount'] > .998

    qa.step('cancelled_drag_adds_no_media', cancel_hover)

    panel = target(qa, 'moodboard_drawer_panel')['center']
    image_id = qa.step('image_release_imports_into_revealed_canvas', drop, qa, image,
                       x=int(panel[0]), y=int(panel[1]))
    capture(qa, out, 'image-after-release')
    before = media(qa)
    toggle(qa, 0)
    sidebar(qa, True)

    def previews_movie():
        hover(qa, movie)
        settle(qa, 1)
        assert_no_import(qa, before)
        verify_viewport(qa, viewport)

    qa.step('video_hover_opens_over_sidebar_before_drop', previews_movie)
    capture(qa, out, 'video-hover-with-sidebar')
    # A viewport release stays centred in the revealed board even though the
    # board is now fully open (the cursor is not on the canvas).
    # Stay clear of the overlapping native TOOLS region at the left edge.
    at = {'x': viewport['viewport'][0] +
               (viewport['viewport'][2] - viewport['viewport'][0]) // 3,
          'y': (viewport['viewport'][1] + viewport['viewport'][3]) // 2}
    movie_id = qa.step('video_release_imports_from_viewport', drop, qa, str(movie), **at)
    assert qa.eval(f'result=any(i.node_id=={movie_id!r} and i.image.source=="MOVIE" '
                   'for i in drv.main_window().scene.mixie_moodboard_images)')
    capture(qa, out, 'video-after-release')

    toggle(qa, 0)
    sidebar(qa, old_sidebar)
    switch_mode(qa, 'mixar.set_ui_mode_pro', 'Layout')

    def engine_unchanged():
        state = media(qa)
        hover(qa, image)
        hover(qa, movie)
        time.sleep(.4)
        assert geometry(qa)['amount'] < .002
        assert_no_import(qa, state)
        assert qa.find(surface='moodboard_drawer_grip')['total'] == 0

    qa.step('engine_hover_keeps_native_workspace', engine_unchanged)
    switch_mode(qa, 'mixar.set_ui_mode_ai', 'Zen Mode')
    return {'backend_calls': 0, 'image_id': image_id, 'movie_id': movie_id,
            'screenshots_retained': False}


if __name__ == '__main__':
    run_scenario('moodboard_reference_drag_e2e', run)
