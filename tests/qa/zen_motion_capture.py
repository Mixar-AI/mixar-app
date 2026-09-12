# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Temporal QA: native input and real frames, without a forced redraw loop."""

import inspect
from pathlib import Path

from PIL import Image


def _hover_in_app(query, away_query, output, click=False):
    import json
    import time
    from pathlib import Path
    import bpy
    import qa_driver as drv

    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    target = drv.find_one(**query)
    away = drv.find_one(**away_query)
    win = target['_win']
    assert away['window'] == target['window']
    drv.move_to(win, *away['center'])
    yield .35
    sequences = []
    clicks_before = bpy.context.window_manager.mixar_ui_gallery.clicks
    began = time.monotonic()
    # Enter, reverse before completion, then settle both ends. Delays and
    # screenshots are yielded through the app loop, never time.sleep there.
    for phase, destination, seconds in (
            ('enter', target, .35), ('leave', away, .05),
            ('reverse', target, .35), ('rest', away, .35)):
        drv.move_to(win, *destination['center'])
        start = time.monotonic()
        pressed = released = False
        frames = []
        while time.monotonic() - start < seconds:
            elapsed = time.monotonic() - start
            if click and phase == 'reverse':
                if elapsed >= .025 and not pressed:
                    drv._sim(win, type='LEFTMOUSE', value='PRESS', **dict(zip(('x', 'y'), target['center'])))
                    pressed = True
                elif elapsed >= .075 and pressed and not released:
                    drv._sim(win, type='LEFTMOUSE', value='RELEASE', **dict(zip(('x', 'y'), target['center'])))
                    released = True
            current = drv.find_one(**query)
            x0, y0, x1, y1 = target['rect']
            path = out / f'{phase}-{len(frames):03}.png'
            with bpy.context.temp_override(window=win):
                assert win.mixar_qa_capture_frame(filepath=str(path), x=max(0,x0-2),
                    y=max(0,y0-2), width=x1-x0+4, height=y1-y0+4)
            frames.append({'time': time.monotonic()-began, 'path': str(path),
                           'rect': current['rect'], 'motion': current.get('mixar_motion')})
            yield .02
        sequences.append({'phase': phase, 'frames': frames})
    yield .35
    stats_a = json.loads(bpy.context.window_manager.mixar_qa_ui_dump).get('motion')
    yield .35
    stats_b = json.loads(bpy.context.window_manager.mixar_qa_ui_dump).get('motion')
    return {'sequences': sequences, 'idle_before': stats_a, 'idle_after': stats_b,
            'clicks': bpy.context.window_manager.mixar_ui_gallery.clicks-clicks_before}


def hover(qa, query, away, output, *, native=True, click=False):
    import json
    result = qa.eval(inspect.getsource(_hover_in_app) +
                     f'\nresult=_hover_in_app({query!r},{away!r},{str(output)!r},{click!r})')
    (Path(output)/'samples.json').write_text(json.dumps(result,indent=2)+'\n')
    frames = [frame for phase in result['sequences'] for frame in phase['frames']]
    assert len({tuple(frame['rect']) for frame in frames}) == 1, 'Hit rectangle moved'
    if native:
        values = [frame['motion']['hover'] for frame in frames]
        assert sum(0 < v < 1 for v in values) >= 2, values
        assert result['sequences'][0]['frames'][-1]['motion']['hover'] == 1, values
        assert result['sequences'][-1]['frames'][-1]['motion']['hover'] == 0, values
    signatures = []
    for frame in frames:
        with Image.open(frame['path']) as image:
            signatures.append(image.convert('RGB').tobytes())
    assert len(set(signatures)) >= 3, 'No intermediate rendered appearances'
    assert result['idle_before'] == result['idle_after'], 'Motion pump continued at rest'
    assert result['idle_after']['pending_regions'] == 0
    if click:
        assert result['clicks'] == 1, 'Click during transition did not invoke exactly once'
        reverse = result['sequences'][2]['frames']
        pressed = [f for f in reverse if f['motion']['press'] > .01]
        assert len(pressed) >= 4, 'Operator execution discarded the animated release pose'
        assert pressed[-1]['time']-pressed[0]['time'] >= .08, 'Release snapped to rest'
    preview(frames, Path(output) / 'motion.gif')
    contact_sheet(frames, Path(output) / 'frames.png')
    return {'frames': len(frames), 'appearances': len(set(signatures)),
            'idle': result['idle_after'], 'clicks': result['clicks'],
            'native_hover': [f['motion']['hover'] for f in frames] if native else None}


def preview(frames, output):
    images = [Image.open(frame['path']).convert('RGB') for frame in frames]
    durations = [max(20, round((b['time']-a['time'])*1000))
                 for a, b in zip(frames, frames[1:])]
    durations.append(durations[-1])
    images[0].save(output, save_all=True, append_images=images[1:], duration=durations, loop=0)
    for image in images:
        image.close()


def contact_sheet(frames, output):
    chosen = [frames[round(i*(len(frames)-1)/7)] for i in range(8)]
    images = [Image.open(frame['path']).convert('RGB') for frame in chosen]
    w, h = images[0].size
    sheet = Image.new('RGB', (w*4, h*2), '#111111')
    for i, image in enumerate(images):
        sheet.paste(image, ((i % 4)*w, (i//4)*h))
        image.close()
    sheet.save(output)
