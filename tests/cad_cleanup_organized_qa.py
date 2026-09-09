# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Background Blender fixture: real memberships, preservation and hidden gates.

Synthetic image receipts exercise validation, not visual recognition accuracy.
"""
import json
import tempfile
from pathlib import Path
import bpy
from mixar.modules.common.cad_cleanup.core import state, reference, organized, inventory, progress, delivery, visual, reference_delivery

bpy.ops.wm.read_factory_settings(use_empty=True)
root = bpy.context.scene
for name in ('TYRE', 'ENGINE BLOCK', 'UNKNOWN PART'):
    bpy.ops.mesh.primitive_cube_add()
    bpy.context.view_layer.objects.active.name = name
bpy.context.view_layer.update()
run = state.start({'owner_id': 'organized-qa', 'request_id': 'start'})
run['reference_profile'] = reference.profile()['profile_id']
run['source_file'] = str(Path(tempfile.mkdtemp(prefix='organized-qa-')) / 'source.blend')
objects = state.objects(run)
ids = {o.name: k for k, o in objects.items()}
before = state.capture(run, full=True)
inventory.inspect_batch(run, {'queries': [{'limit': 100}]})
for name, category in [('TYRE', '_VIZ_WHEELS_MAIN'), ('ENGINE BLOCK', '_SYS_ENGINE_MAIN')]:
    run['records'][ids[name]]['category'] = category
run['evidence']['parts'] = {'view': 'front', 'revision': run['revision'], 'fingerprint': run['fingerprint'],
                          'camera': {'test': True}, 'render_ids': [ids['ENGINE BLOCK']]}
run['evidence']['context'] = {'view': 'front', 'revision': run['revision'], 'fingerprint': run['fingerprint'],
                            'camera': {'test': True}, 'render_ids': list(objects)}
hidden = {'object_ids': [ids['ENGINE BLOCK']], 'disposition': 'hidden_internal',
          'reason': 'Identified sealed engine mechanism', 'evidence_kind': 'semantic_review',
          'evidence_ids': ['parts']}
def assign(request_id, rows):
    return reference.assign(run, {'request_id': request_id, 'decisions': rows})
try:
    assign('missing-context', [hidden])
except state.CadError as exc:
    assert exc.code == 'semantic_review_required'
else:
    raise AssertionError('Missing hidden visibility context was accepted')
hidden.update(context_evidence_ids=['context'], visibility_context=
              'Synthetic case: enclosed by the body outside and firewall from the cabin; not a visible underside surface.')
assign('batch', [hidden, {'object_ids': [ids['TYRE']], 'disposition': 'keep',
                       'path': 'EXT/WHEELS/TYRE', 'reason': 'Known road tyre',
                       'evidence_kind': 'name_and_context'}])
hashes = []
mesh_digest = state.mesh_digest
state.mesh_digest = lambda mesh: hashes.append(mesh.name) or mesh_digest(mesh)
receipt = organized.sync(run)
assert hashes == [], hashes
assert receipt['counts'] == {'EXT/WHEELS/TYRE': 1, 'HIDDEN_INTERNALS': 1, 'REVIEW': 1}, receipt
assert state.digest(state.capture(run)) == state.digest(before)
assert len(bpy.data.meshes) == 3  # Copies share geometry, never duplicate buffers.
assert bpy.data.collections['HIDDEN_INTERNALS'].hide_render
assert bpy.data.collections['HIDDEN_INTERNALS'].hide_viewport
assert all(o.parent is None for o in organized.scene_for(run).objects)
copies = {o.get(organized.SOURCE): o.as_pointer() for o in organized.scene_for(run).objects}
assert organized.sync(run) == receipt
assert copies == {o.get(organized.SOURCE): o.as_pointer() for o in organized.scene_for(run).objects}
assign('review-tyre', [{'object_ids': [ids['TYRE']], 'disposition': 'review', 'reason': 'Recheck tyre identity'}])
organized.sync(run)
assert bpy.data.collections.get('TYRE') is None  # Empty shells removed.
assert len(bpy.data.collections['REVIEW'].objects) == 2
assert state.digest(state.capture(run)) == state.digest(before)
# A foreign collection must never be commandeered.
foreign = bpy.data.collections.new('TYRE')
root.collection.children.link(foreign)
state.refresh(run)
assign('keep-again', [{'object_ids': [ids['TYRE']], 'disposition': 'keep',
                     'path': 'EXT/WHEELS/TYRE', 'reason': 'Known road tyre', 'evidence_kind': 'name_and_context'}])
try:
    organized.sync(run)
except state.CadError as exc:
    assert exc.code == 'reference_collision'
else:
    raise AssertionError('Foreign collection was commandeered')
bpy.data.collections.remove(foreign)
state.refresh(run)
snapshot = progress.checkpoint(run, {'reason': 'Fixture checkpoint', 'save_checkpoint': True})
folder = Path(run['progress_receipt']['local_directory'])
assert (folder / 'index.html').is_file()
assert (folder / 'snapshots' / snapshot['snapshot'] / 'organized.mixar').is_file()
assert (folder / 'snapshots' / snapshot['snapshot'] / 'checkpoint.mixar').is_file()
# Final export must retain hidden internals while excluding affirmative omissions.
fixture_profile = reference.profile()
for row in fixture_profile['collections']:
    row['mesh_count'] = int(row['path'] == 'EXT/WHEELS/TYRE')
reference.profile = lambda: fixture_profile
assign('omit-fixture-only', [{'object_ids': [ids['UNKNOWN PART']], 'disposition': 'omit',
    'reason': 'Synthetic backing cube outside this fixture target', 'evidence_kind': 'semantic_review',
    'evidence_ids': ['context']}])
reference.review_coverage(run, {'reviews': [{'path': 'EXT/WHEELS/TYRE', 'status': 'verified',
    'notes': 'Synthetic tyre collection membership reviewed in this fixture.', 'evidence_ids': ['context']}]})
for key, obj in objects.items(): run['records'][key]['category'] = obj.users_collection[0].name
run['stage_status'] = dict.fromkeys(run['stage_status'], 'reviewed')
assert delivery.verify(run)['verified']
for view in ('front', 'right'):
    image = visual.render(run, {'view': view, 'delivery': True})
    visual.review(run, {'evidence_id': image['evidence_id'], 'verdict': 'pass',
                       'notes': 'Synthetic fixture assertion of retained geometry.'})
saved = reference_delivery.save(run, {'request_id': 'save-final', 'filename': 'final.blend'})
assert saved['saved']
assert run['artifact']['hidden_internal_objects'] == 1
assert len(organized.scene_for(run).objects) == 2
assert len(bpy.data.collections['HIDDEN_INTERNALS'].objects) == 1
assert bpy.data.collections.get('REVIEW') is None
assert len(state.objects(run)) == 3
print('CAD_ORGANIZED_QA_PASS', json.dumps(organized.public(run)))
