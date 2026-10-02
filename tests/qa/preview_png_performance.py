#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Compare lossless PNG saves of the SAME completed Render Result in real Mixar.

Run after a preview completes in an isolated QA app (never during a live turn):
QA_HARNESS=/path/to/harness MIXAR_QA_PORT=4785 \
 QA_SCENARIO_OUT=/tmp/png-benchmark python3 tests/qa/preview_png_performance.py

Settings are restored; no new render or backend request is made. Intentionally
reproduces the UI stall at compression 100. Pillow checks pixel equality outside
Blender. Keep the result PNGs and JSON alongside native/Python stack evidence.
"""
import json
import os
from pathlib import Path
import sys

from PIL import Image

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA  # noqa: E402

out = Path(os.environ['QA_SCENARIO_OUT']).resolve()
out.mkdir(parents=True, exist_ok=True)
qa = QA()
assert not qa.status()['busy'], 'Wait for the agent turn to finish'
code = '''
import time
from pathlib import Path
from mixar.modules.space_mixie_chat.core import preview_render
assert not bpy.app.is_job_running('RENDER') and preview_render._job is None
image=bpy.data.images.get('Render Result')
assert image is not None and image.has_data, 'Generate a preview first'
scene=drv.main_window().scene
settings=scene.render.image_settings
saved=(settings.file_format,settings.compression)
rows=[]
try:
    settings.file_format='PNG'
    for compression in (100,15,0,15,100):
        settings.compression=compression
        path=output/f'compression-{compression}.png'
        start=time.perf_counter()
        image.save_render(str(path),scene=scene)
        rows.append(dict(compression=compression,seconds=time.perf_counter()-start,
                         bytes=path.stat().st_size))
finally:
    settings.file_format,settings.compression=saved
result=rows
'''
rows = qa.cmd('eval', code=f'from pathlib import Path\noutput=Path({str(out)!r})\n'+code,
              _sock_timeout=180)
with Image.open(out/'compression-100.png') as a, Image.open(out/'compression-15.png') as b:
    assert a.size == b.size
    same = a.convert('RGBA').tobytes() == b.convert('RGBA').tobytes()
assert same, 'PNG compression changed decoded pixels'
result = dict(saves=rows, pixels_identical=same)
(out/'png-benchmark.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
