# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Real evaluated-geometry regressions for scoped ray transforms and partial results."""
import json
import tempfile
from pathlib import Path
import bpy
from mathutils import Matrix
from mixar.modules.common.cad_cleanup.core import state, scoped_rays

bpy.ops.wm.read_factory_settings(use_empty=True)
for name, z in (('unrelated_occluder', -2), ('target', -5)):
    bpy.ops.mesh.primitive_cube_add(location=(0, 0, z))
    obj = bpy.context.view_layer.objects.active
    obj.name = name
    if name == 'target':
        obj.scale = (-1, 2, .6)
        obj.rotation_euler = (.2, .4, .7)
bpy.context.view_layer.update()
run = state.start({'owner_id': 'scoped-rays-qa', 'request_id': 'fixture'})
target = next(k for k,v in run['records'].items() if v['name']=='target')
meta = {'render_ids': [target], 'camera': {'matrix': [list(r) for r in Matrix.Identity(4)],
        'corners': [[1,1,-1],[1,-1,-1],[-1,-1,-1],[-1,1,-1]], 'clip_start': .1, 'clip_end': 100}}
hits, samples, partial = scoped_rays.cast(run, meta, [(.5,.5)])
assert dict(hits)=={target:1} and samples==1 and not partial
checks = ['negative/nonuniform scale and rotated evaluated mesh hit', 'unrelated foreground object ignored']
budget = scoped_rays.TIME_BUDGET
try:
    scoped_rays.TIME_BUDGET = -1
    hits, samples, partial = scoped_rays.cast(run, meta, [(.5,.5)])
    assert not hits and samples==0 and partial
finally:
    scoped_rays.TIME_BUDGET = budget
checks.append('time budget yields explicit partial result without invented hits')
try:
    scoped_rays.cast(run, {**meta, 'render_ids': [target]*2049}, [(.5,.5)])
except state.CadError as error:
    assert error.code=='ray_scope_too_large'
else:
    raise AssertionError('Oversized scope accepted')
checks.append('oversized ray scope rejected before evaluation')
result = {'pass': True, 'checks': checks}
Path(tempfile.gettempdir(), 'cad-scoped-rays-qa-result.json').write_text(json.dumps(result,indent=2))
print('SCOPED_RAYS_QA_PASS', json.dumps(result))
