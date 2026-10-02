#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Time actual async previews in an idle isolated QA scene with a camera.

QA_HARNESS=/path/to/harness MIXAR_QA_PORT=4785 \
 QA_SCENARIO_OUT=/tmp/preview-performance \
 python3 tests/qa/preview_render_performance.py

Runs 1400 and 1920 square EEVEE previews through production start/poll, checks
restoration and payload bounds, and saves the delivered PNGs for vision review.
The temporary timing wrapper is removed on exit. No backend calls/token costs.
"""
import base64
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA  # noqa: E402

qa = QA()
out = Path(os.environ['QA_SCENARIO_OUT'])
out.mkdir(parents=True, exist_ok=True)
assert not qa.status()['busy']
SETUP = '''
import time
from mixar.modules.space_mixie_chat.core import preview_render as preview
assert preview._job is None and not bpy.app.is_job_running('RENDER')
assert preview.PNG_COMPRESSION == 15
original = preview._read_png

def timed_save(scene):
    started = time.perf_counter()
    pixels = original(scene)
    bpy.app.driver_namespace['qa_preview_save'] = dict(
        seconds=time.perf_counter()-started, bytes=len(pixels))
    return pixels

preview._qa_original_read_png = original
preview._read_png = timed_save
result = True
'''
qa.eval(SETUP)
verdicts = []
try:
    for edge in (1400, 1920):
        before = qa.eval('''
s = drv.main_window().scene
result = [s.render.engine, s.render.resolution_x, s.render.resolution_y,
          s.render.resolution_percentage, s.render.image_settings.file_format,
          s.render.image_settings.compression]
''')
        start = time.monotonic()
        job = qa.eval(f'''
import uuid
from mixar.modules.space_mixie_chat.core import preview_render as preview
with bpy.context.temp_override(window=drv.main_window()):
    result = preview.start(bpy.context, uuid.uuid4().hex, width={edge}, height={edge}, engine='eevee')
''')
        assert job['status'] == 'running', job
        key = job['job_id']
        polls = []
        while time.monotonic() - start < 120:
            tick = time.monotonic()
            state = qa.cmd('eval', code=f'''
from mixar.modules.space_mixie_chat.core import preview_render as preview
result = {{k:v for k,v in preview.poll({key!r}).items() if k != 'image_url'}}
''', _sock_timeout=30)
            polls.append(time.monotonic() - tick)
            if state['status'] != 'running':
                break
            time.sleep(.1)
        assert state['status'] == 'done', state
        delivered = qa.eval(f'''
from mixar.modules.space_mixie_chat.core import preview_render as preview
s = drv.main_window().scene
result = dict(image=preview.poll({key!r})['image_url'],
              save=bpy.app.driver_namespace['qa_preview_save'],
              restored=[s.render.engine, s.render.resolution_x, s.render.resolution_y,
                        s.render.resolution_percentage, s.render.image_settings.file_format,
                        s.render.image_settings.compression])
''')
        assert delivered['restored'] == before
        pixels = base64.b64decode(delivered['image'].split(',', 1)[1])
        assert pixels.startswith(b'\x89PNG\r\n\x1a\n') and len(pixels) <= 8_000_000
        (out / f'preview-{edge}.png').write_bytes(pixels)
        state.update(save=delivered['save'], max_poll_seconds=max(polls),
                     wall_seconds=time.monotonic()-start, settings_restored=True)
        verdicts.append(state)
        print(json.dumps(state, indent=2), flush=True)
finally:
    qa.eval('''
from mixar.modules.space_mixie_chat.core import preview_render as preview
preview._read_png = preview._qa_original_read_png
del preview._qa_original_read_png
result = True
''')
    (out / 'preview-verdicts.json').write_text(json.dumps(verdicts, indent=2))
