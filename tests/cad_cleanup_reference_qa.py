# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Isolated Blender integration fixture; never runs against the user's project."""
from pathlib import Path
import sys
import json
import bpy

import tempfile
ROOT = Path(tempfile.mkdtemp(prefix='mixar-reference-qa-'))
if True:
    from mixar.modules.common.cad_cleanup.core import state, reference, visual, grounding, reference_delivery, delivery, inventory
else:
    sys.path.insert(0, str(ROOT / 'client/src/scripts/mixar/modules/common'))
    from cad_cleanup.core import state, reference, visual, grounding, reference_delivery, delivery

bpy.ops.wm.read_factory_settings(use_empty=True)
for name, location in [('front_piece', (-2, 0, 0)), ('occluded_piece', (2, 0, 0)), ('side_piece', (0, 4, 0))]:
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    bpy.context.object.name = name
bpy.context.view_layer.update()
run = state.start({'owner_id': 'reference-qa', 'request_id': 'fixture'})
run['source_file'] = str(ROOT / 'fixture.blend')
ids = {o.name: k for k, o in state.objects(run).items()}
inventory.inspect_batch(run,{'queries':[{'limit':100}]})
# This synthetic reference has two required populated paths while retaining the
# real 120-path export hierarchy. It does not pretend absent vehicle components
# were visually checked in a three-cube fixture.
fixture_profile=reference.profile()
for row in fixture_profile['collections']:
    row['mesh_count']=int(row['path'] in ('EXT/FRONT/FRONT_BUMPER','INT/DASHBOARD'))
reference.profile=lambda:fixture_profile
before_objects = set(o.as_pointer() for o in bpy.data.objects)
before_meshes = set(m.as_pointer() for m in bpy.data.meshes)

def refused(code, fn):
    try: fn()
    except state.CadError as error: assert error.code == code, (error.code, code)
    else: raise AssertionError('Expected '+code)

refused('invalid_regions', lambda: grounding.points_for_regions([[0, 0, float('nan'), 1]]))
refused('invalid_regions', lambda: grounding.points_for_regions([[5, 5, 4, 10]]))
refused('empty_render', lambda: visual.render(run, {'object_ids': []}))
image = visual.render(run, {'view': 'front'})
retry = visual.render(run, {'view': 'front'})
assert retry['cached'] and retry['evidence_id'] == image['evidence_id']
rays = grounding.ray_select(run, {'evidence_id': image['evidence_id'], 'boxes': [[0, 0, 1000, 1000]]})
hit_ids = {r['object_id'] for r in rays['candidates']}
assert ids['front_piece'] in hit_ids and ids['occluded_piece'] not in hit_ids, rays
# Asynchronous native rendering has a separate GUI test.
raster = {'visible_count': None}
refused('removal_evidence_required', lambda: reference.assign(run, {'request_id': 'unsafe',
    'decisions': [{'object_ids': [ids['occluded_piece']], 'disposition': 'omit',
                   'reason': 'Not visible', 'evidence_kind': 'visual_candidates'}]}))
reference.assign(run, {'request_id': 'keep-front', 'decisions': [{'object_ids': [ids['front_piece']],
    'disposition': 'keep', 'path': 'EXT/FRONT/FRONT_BUMPER', 'reason': 'Fixture front surface',
    'evidence_kind': 'semantic_review','evidence_ids':[image['evidence_id']]}]})
refused('reference_incomplete', lambda: reference_delivery.validate(run))
reference.assign(run, {'request_id': 'remaining', 'decisions': [
    {'object_ids': [ids['side_piece']], 'disposition': 'keep', 'path': 'INT/DASHBOARD',
     'reason': 'Interior fixture retained despite not being an exterior category', 'evidence_kind': 'semantic_review','evidence_ids':[image['evidence_id']]},
    {'object_ids': [ids['occluded_piece']], 'disposition': 'omit',
     'reason': 'Fixture-only backing cube, explicitly outside delivery standard', 'evidence_kind': 'semantic_review','evidence_ids':[image['evidence_id']]}]})
# Fixture establishes completed categories; verify() still runs the real full audit.
for key, obj in state.objects(run).items(): run['records'][key]['category'] = obj.users_collection[0].name
run['stage_status'] = dict.fromkeys(run['stage_status'], 'reviewed')
reference.review_coverage(run,{'reviews':[{'path':path,'status':'verified',
    'notes':'Synthetic fixture membership and surfaces checked against its two-cube target.',
    'evidence_ids':[image['evidence_id']]} for path in ('EXT/FRONT/FRONT_BUMPER','INT/DASHBOARD')]})
assert delivery.verify(run)['verified']
image = visual.render(run, {'view': 'front', 'delivery': True})
visual.review(run, {'evidence_id': image['evidence_id'], 'verdict': 'pass', 'notes': 'Synthetic fixture assertion; two retained surfaces.'})
refused('reference_review_required', lambda: reference_delivery.validate(run))
image = visual.render(run, {'view': 'right', 'delivery': True})
visual.review(run, {'evidence_id': image['evidence_id'], 'verdict': 'pass', 'notes': 'Synthetic alternate-direction fixture review.'})
filename = 'fixture-output-' + state.token()[:8] + '.blend'
result = reference_delivery.save(run, {'request_id': 'save', 'filename': filename})
assert result['saved'] and (ROOT / filename).is_file()
assert set(o.as_pointer() for o in bpy.data.objects) == before_objects
assert set(m.as_pointer() for m in bpy.data.meshes) == before_meshes
assert ids['occluded_piece'] in state.objects(run)
run['revision'] += 1
refused('stale_evidence', lambda: grounding.image(run, {'evidence_id': image['evidence_id']}))
(ROOT / 'fixture-result.json').write_text(json.dumps({'pass': True, 'output': filename, 'rays': rays,
    'raster_visible': raster['visible_count']}), encoding='utf-8')
print('REFERENCE_WORKFLOW_PASS', filename)
