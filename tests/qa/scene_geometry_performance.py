#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Compare bulk geometry methods in an idle, isolated QA app.

QA_HARNESS=/path/to/harness MIXAR_QA_PORT=4785 \
 QA_SCENARIO_OUT=/tmp/scene-performance \
 python3 tests/qa/scene_geometry_performance.py

Creates/removes 300 unique cubes per method; checks dimensions and face counts.
Operator timing deliberately stalls the UI. If app.pid exists in the output
folder on macOS, also collect a native sample. No backend calls/token costs.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA  # noqa: E402

out = Path(os.environ['QA_SCENARIO_OUT'])
out.mkdir(parents=True, exist_ok=True)
qa = QA()
assert not qa.status()['busy']
CODE = '''
import time
from mixar.modules.moodboard.core import splat_render_camera as splat
from mixar.modules.space_mixie_chat.core import preview_render
assert not bpy.app.is_job_running('RENDER') and preview_render._job is None
window = drv.main_window()
original = splat._saved_splat_proxies
stats = dict(calls=0, seconds=0)

def scan():
    start = time.perf_counter()
    try:
        return original()
    finally:
        stats['calls'] += 1
        stats['seconds'] += time.perf_counter() - start

splat._saved_splat_proxies = scan
rows = []
vertices = [(x, y, z) for x in (-.5, .5) for y in (-1, 1) for z in (-1.5, 1.5)]
faces = [(0,4,6,2), (1,3,7,5), (0,1,5,4), (2,6,7,3), (0,2,3,1), (4,5,7,6)]
try:
    with bpy.context.temp_override(window=window):
        selected = list(bpy.context.selected_objects)
        active = bpy.context.view_layer.objects.active
        try:
            for method in ('operators', 'data_api'):
                made, meshes = [], []
                stats.update(calls=0, seconds=0)
                before = len(bpy.data.objects)
                start = time.perf_counter()
                try:
                    for i in range(300):
                        location = (200 + i % 30 * 2, 200 + i // 30 * 3, 0)
                        if method == 'operators':
                            bpy.ops.mesh.primitive_cube_add(size=1, location=location)
                            obj = bpy.context.object
                            made.append(obj)
                            meshes.append(obj.data)
                            obj.dimensions = (1, 2, 3)
                            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
                        else:
                            mesh = bpy.data.meshes.new('QA_Performance_Cube')
                            meshes.append(mesh)
                            mesh.from_pydata(vertices, [], faces)
                            obj = bpy.data.objects.new('QA_Performance_Cube', mesh)
                            made.append(obj)
                            obj.location = location
                            window.scene.collection.objects.link(obj)
                    bpy.context.view_layer.update()
                    elapsed = time.perf_counter() - start
                    assert all(tuple(obj.dimensions) == (1, 2, 3) for obj in made)
                    polygons = sum(len(obj.data.polygons) for obj in made)
                    assert polygons == 1800
                    rows.append(dict(method=method, count=len(made), seconds=elapsed,
                                     background_objects=before, splat_scan=dict(stats),
                                     polygons=polygons, dimensions_verified=True))
                finally:
                    bpy.data.batch_remove(ids=made + meshes)
                assert len(bpy.data.objects) == before
        finally:
            for obj in selected:
                obj.select_set(True)
            bpy.context.view_layer.objects.active = active
finally:
    splat._saved_splat_proxies = original
result = rows
'''


def sample():
    pid = out / 'app.pid'
    if not pid.exists() or sys.platform != 'darwin':
        return
    time.sleep(1)
    subprocess.run(['/usr/bin/sample', pid.read_text().strip(), '3', '-file',
                    str(out / 'operator-native-sample.txt')],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


sampler = threading.Thread(target=sample)
sampler.start()
try:
    rows = qa.cmd('eval', code=CODE, _sock_timeout=180)
    (out / 'geometry-benchmark.json').write_text(json.dumps(rows, indent=2))
    print(json.dumps(rows, indent=2))
finally:
    sampler.join()
