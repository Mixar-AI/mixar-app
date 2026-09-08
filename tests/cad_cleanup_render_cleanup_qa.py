# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Exercise real render cleanup, success and failure, without the vehicle file."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/scripts'))
import bpy
from mixar.modules.common.cad_cleanup.core import visual, state

bpy.ops.mesh.primitive_cube_add()
source = bpy.context.object
source.name = 'ENGINE BLOCK'
run = state.start({'owner_id':'render-qa', 'request_id':'start'})
initial = {name: {v.as_pointer() for v in getattr(bpy.data, name)}
           for name in ('objects', 'meshes', 'scenes', 'cameras')}
real_batch = bpy.data.batch_remove
calls = []
# Blender's data method cannot be replaced: validate its effects directly.
result = visual.render(run, {'view':'perspective'})
assert result['image_base64'] and result['rendered_meshes'] > 0
for name, pointers in initial.items():
    assert {v.as_pointer() for v in getattr(bpy.data, name)} == pointers, name
original_persist = visual.persist
def forced_failure(run):
    raise RuntimeError('injected after rendering')
visual.persist = forced_failure
try:
    visual.render(run, {'view':'front'})
    raise AssertionError('failure not injected')
except RuntimeError as exc:
    assert str(exc) == 'injected after rendering'
finally:
    visual.persist = original_persist
for name, pointers in initial.items():
    assert {v.as_pointer() for v in getattr(bpy.data, name)} == pointers, name
print('CAD_RENDER_CLEANUP_PASS: success and failure preserve source IDs and remove temporary IDs')
