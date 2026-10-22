#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""The first Cycles GPU render after launch, on a cold kernel cache, completes.

    rm -rf /tmp/qa-xdg && mkdir /tmp/qa-xdg
    XDG_CACHE_HOME=/tmp/qa-xdg ./run_qa_app.sh          # in the harness
    QA_HARNESS=/path/to/harness MIXAR_QA_PORT=4777 \
     QA_SCENARIO_OUT=/tmp/cycles-first-render \
     python3 tests/qa/cycles_cold_cache_first_render_e2e.py

Run it once per FRESH launch: `path_cache_get()` (intern/cycles/util/path.cpp)
initialises the kernel-cache root on its first call per process, and that call
comes from every Metal shader-compile thread at once. Upstream raced that
initialisation; a torn path became a nil `NSURL` and the app aborted. An empty
`XDG_CACHE_HOME` forces every kernel to compile, so each launch re-runs the
racy first call without touching the developer's own `~/.cache/cycles`.
`QA_COLD_CACHE=0` accepts a warm scratch cache for cheap repeated launches.

Drives the production agent preview (`preview_render.start`, the path behind
`render_viewport(quality="final", engine="cycles")`) and asserts: Cycles on
the GPU, job done, a non-black PNG, and the Metal binary archives written
under `$XDG_CACHE_HOME/cycles/kernels/<device>/<kernel>/<pso>/<md5>.bin`.
No backend calls or credits.
"""
import base64
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA, ScenarioFail, run_scenario  # noqa: E402

OUT = Path(os.environ['QA_SCENARIO_OUT'])
RENDER_TIMEOUT_S = 900  # a cold Metal compile of every kernel takes minutes
# QA_COLD_CACHE=0 reuses a warm cache: loading an archive goes through the same
# compile() and the same first path_cache_get(), in seconds instead of minutes,
# so many launches can be repeated cheaply.
COLD = os.environ.get('QA_COLD_CACHE', '1') != '0'

PRECONDITIONS = '''
import os
from mixar.modules.space_mixie_chat.core import preview_render as preview, render_device
cache = os.environ.get('XDG_CACHE_HOME', '')
scene = drv.main_window().scene
cycles_prefs = bpy.context.preferences.addons['cycles'].preferences
result = dict(
    xdg_cache_home=cache,
    cache_entries=sorted(os.listdir(cache)) if cache and os.path.isdir(cache) else None,
    compute_device_type=str(cycles_prefs.compute_device_type),
    devices=[d.name for d in cycles_prefs.devices
             if d.use and d.type == cycles_prefs.compute_device_type],
    use_gpu=render_device.use_gpu(),
    camera=scene.camera.name if scene.camera else None,
    idle=preview._job is None and not bpy.app.is_job_running('RENDER'),
)
'''

START = '''
from mixar.modules.space_mixie_chat.core import preview_render as preview
with bpy.context.temp_override(window=drv.main_window()):
    result = preview.start(bpy.context, {key!r}, width=512, height=512, engine='cycles')
'''

POLL = '''
from mixar.modules.space_mixie_chat.core import preview_render as preview
result = {{k: v for k, v in preview.poll({key!r}).items() if k != 'image_url'}}
'''

IMAGE = '''
from mixar.modules.space_mixie_chat.core import preview_render as preview
result = preview.poll({key!r})['image_url']
'''

# Pixel statistics of the delivered PNG, read in-app (the harness Python has no
# PIL); the probe image is removed again.
PIXELS = '''
import numpy as np
img = bpy.data.images.load({path!r}, check_existing=False)
try:
    px = np.empty(img.size[0] * img.size[1] * img.channels, dtype=np.float32)
    img.pixels.foreach_get(px)
    rgb = px.reshape(-1, img.channels)[:, :3]
    result = dict(size=list(img.size), mean=float(rgb.mean()), std=float(rgb.std()),
                  max=float(rgb.max()))
finally:
    bpy.data.images.remove(img)
'''

ARCHIVES = '''
import os
root = os.path.join(os.environ['XDG_CACHE_HOME'], 'cycles', 'kernels')
found = []
for dirpath, _dirs, files in os.walk(root):
    found += [os.path.relpath(os.path.join(dirpath, f), root) for f in files if f.endswith('.bin')]
result = sorted(found)
'''


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    pre = qa.step('preconditions', qa.eval, PRECONDITIONS)
    if not pre['xdg_cache_home']:
        raise ScenarioFail(f"needs XDG_CACHE_HOME pointing at a scratch cache: {pre}")
    if COLD and pre['cache_entries'] not in ([], None):
        raise ScenarioFail(f"QA_COLD_CACHE=1 needs an EMPTY XDG_CACHE_HOME: {pre}")
    if not pre['use_gpu'] or pre['compute_device_type'] != 'METAL':
        raise ScenarioFail(f"Cycles is not on a Metal GPU: {pre}")
    if not pre['camera'] or not pre['idle']:
        raise ScenarioFail(f"scene needs a camera and no running render: {pre}")

    key = uuid.uuid4().hex
    started = time.monotonic()
    job = qa.step('start cycles preview', qa.eval, START.format(key=key))
    if job['status'] != 'running':
        raise ScenarioFail(f"preview did not start: {job}")
    if job['render'].get('engine') != 'CYCLES' or job['render'].get('device') != 'GPU':
        raise ScenarioFail(f"not a Cycles GPU job: {job['render']}")

    def wait_done():
        while time.monotonic() - started < RENDER_TIMEOUT_S:
            state = qa.cmd('eval', code=POLL.format(key=key), _sock_timeout=60)
            if state['status'] != 'running':
                return state
            time.sleep(1.0)
        raise ScenarioFail(f"render still running after {RENDER_TIMEOUT_S}s")

    state = qa.step('render completes', wait_done)
    seconds = round(time.monotonic() - started, 1)
    if state['status'] != 'done':
        raise ScenarioFail(f"render ended {state['status']}: {state}")

    png = base64.b64decode(qa.eval(IMAGE.format(key=key)).split(',', 1)[1])
    if not png.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ScenarioFail('delivered image is not a PNG')
    path = OUT / 'first-render.png'
    path.write_bytes(png)
    pixels = qa.step('png has content', qa.eval, PIXELS.format(path=str(path)))
    if pixels['size'] != [512, 512] or pixels['max'] <= 0.05 or pixels['std'] <= 0.01:
        raise ScenarioFail(f"render is blank or the wrong size: {pixels}")

    def archives_written():
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            found = qa.eval(ARCHIVES)
            if found:
                return found
            time.sleep(2.0)
        raise ScenarioFail('no Metal binary archive under $XDG_CACHE_HOME/cycles/kernels')

    archives = qa.step('kernel cache under XDG_CACHE_HOME', archives_written)
    # A torn cache root would put archives elsewhere or under a mangled name.
    misplaced = [a for a in archives
                 if not re.fullmatch(r'[A-Za-z0-9_]+/[a-z0-9_]+/PSO_[A-Z_]+/[0-9A-F]{32}\.bin', a)]
    if misplaced:
        raise ScenarioFail(f"archives outside <device>/<kernel>/<pso>/<md5>.bin: {misplaced[:5]}")
    qa.step('app still alive', qa.status)
    verdict = dict(cold_cache=COLD, render_seconds=seconds, render=state.get('render'), pixels=pixels,
                   archives=len(archives), archive_sample=archives[:3],
                   device=pre['devices'], png=str(path))
    (OUT / 'verdict.json').write_text(json.dumps(verdict, indent=2))
    return verdict


if __name__ == '__main__':
    run_scenario('cycles_cold_cache_first_render', run)
