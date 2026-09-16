# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Blender regression: large assembly receipts cannot bypass scope or semantic gates."""
import json
import tempfile
from pathlib import Path
import bpy
from mixar.modules.common.cad_cleanup import api
from mixar.modules.common.cad_cleanup.core import state, reference, assemblies, inventory, rules

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add()
mesh = bpy.context.view_layer.objects.active.data
bpy.data.objects.remove(bpy.context.view_layer.objects.active, do_unlink=True)
for i in range(1201):
    obj = bpy.data.objects.new('FRT_RADIATOR_GRILL.' + str(i).zfill(4), mesh)
    bpy.context.scene.collection.objects.link(obj)
obj = bpy.data.objects.new('WHEEL HOUSE FRONT', mesh)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.update()
owner = {'owner_id': 'assembly-qa', 'request_id': 'start', 'reference_profile': True}
run = state.start(owner)
owner['run_id'] = run['run_id']
root = Path(tempfile.mkdtemp(prefix='cad-assembly-qa-'))
run['source_file'] = str(root/'fixture.mixar')
for row in run['records'].values():
    row['category'] = '_SYS_COOLING_MAIN' if 'GRILL' in row['name'] else '_VIZ_WHEELS_MAIN'
state.persist(run)
checks = []

def call(action, **payload):
    result = api.dispatch(action, {**owner, **payload})
    assert result['success'], result
    return result

group = call('inspect_batch', queries=[{'query': 'RADIATOR', 'limit': 1}])['results'][0]
receipt = call('inspect_assembly', selection_id=group['selection_id'], path='EXT/FRONT/FRONT_GRILL')
assert receipt['checked_count'] == 1201 and receipt['exception_count'] == 0 and receipt['assembly_id']
assert len(receipt['examples']) == 6
checks.append('1201 fragments checked locally without paginated LLM inspection')
ids = run['selections'][group['selection_id']]['object_ids']
decision = {'selection_id': group['selection_id'], 'assembly_id': receipt['assembly_id'],
            'disposition': 'keep', 'path': 'EXT/FRONT/FRONT_GRILL', 'reason': 'Whole assembly fixture review',
            'evidence_kind': 'semantic_review', 'evidence_ids': ['fixture-image']}

def reject(row, code='semantic_review_required'):
    result = api.dispatch('reference_assign', {**owner, 'request_id': state.token(), 'decisions': [row]})
    assert not result['success'] and result['error']['code'] == code, result

reject(decision)
checks.append('large assembly cannot assign without current whole-group image')
# Synthetic evidence tests receipt semantics only; real raster is a separate fixture.
run['evidence']['fixture-image'] = {'revision': run['revision'], 'fingerprint': run['fingerprint'],
                                 'camera': {'fixture': True}, 'render_ids': ids}
state.persist(run)
reject({**decision, 'path': 'EXT/UNDERBODY'})
reject({**decision, 'disposition': 'omit', 'path': None})
reject({**decision, 'assembly_id': None})
reject({**decision, 'selection_id': None, 'object_ids': ids[:10]})
checks.append('wrong path, omission, missing receipt and partial membership rejected atomically')
assigned = call('reference_assign', decisions=[decision], request_id='assembly-assignment')
assert assigned['assigned'] == 1201 and assigned['invalid_assignments'] == 0
checks.append('large grille assignment accepted despite obsolete cooling labels')
mixed = call('inspect_batch', queries=[{'limit': 1}])['results'][0]
bad = call('inspect_assembly', selection_id=mixed['selection_id'], path='EXT/FRONT/FRONT_GRILL')
assert not bad['assembly_id'] and bad['exception_count'] == 1
assert bad['compatible_selection_id'] and bad['exception_selection_id']
clean = call('inspect_assembly', selection_id=bad['compatible_selection_id'], path='EXT/FRONT/FRONT_GRILL')
assert clean['assembly_id'] and clean['checked_count'] == 1201
checks.append('one unrelated member blocks blanket assembly approval')
reject({**decision, 'path': 'EXT/FRONT/GRILLE'}, 'invalid_path')
assert 'EXT/WHEELS/BREAK_DISK' in {r['path'] for r in reference.profile()['collections']}
checks.append('exact reference spelling and hierarchy retained')
run['revision'] += 1
state.persist(run)
assert not assemblies.valid(run, ids, decision)
checks.append('scene revision invalidates assembly receipt')
result = {'pass': True, 'checks': checks}
(root/'result.json').write_text(json.dumps(result, indent=2))
Path(tempfile.gettempdir(), 'cad-assembly-qa-result.json').write_text(json.dumps(result, indent=2))
print('ASSEMBLY_QA_PASS', json.dumps(result))
