# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Validated application, replay protection and reversible operation journals."""
import copy
import logging

import bpy
from mathutils import Matrix, Vector

from ..constants import OWNER_KEY
from .state import capture, digest, fail, matrix, objects, persist, record, refresh, token, relations, render_eligible_ids, authored_transform


def replay(run, payload, action):
    request = payload.get('request_id')
    if not isinstance(request, str) or not request:
        fail('missing_request', 'Mutation requires a request_id.')
    signature = digest({'action': action, **{k: v for k, v in payload.items() if k != 'owner_id'}})
    old = run['requests'].get(request)
    if old:
        if old['signature'] != signature: fail('request_conflict', 'Request ID already used for different arguments.')
        if action == 'apply' and any(op['operation_id'] == old['result'].get('operation_id') and op['undone']
                                     for op in run['operations']):
            fail('operation_undone', 'This operation was undone; analyze again instead of replaying it.')
        return signature, old['result']
    return signature, None


def remember(run, payload, signature, result):
    run['requests'][payload['request_id']] = {'signature': signature, 'result': result}
    persist(run)
    return result


def collection(run, name, parent=None):
    coll = bpy.data.collections.get(name)
    if coll:
        if coll.get(OWNER_KEY) != run['run_id']:
            fail('collection_collision', 'A destination collection exists outside this cleanup run.')
    else:
        coll = bpy.data.collections.new(name)
        coll[OWNER_KEY] = run['run_id']
        (parent or bpy.context.scene.collection).children.link(coll)
    return coll


def destination(run, path):
    parent=None
    for name in path: parent=collection(run,name,parent)
    return parent


def restore_snapshot(obj, snap, memberships=None, defer_visibility=False):
    # Validate every dependency BEFORE unlinking any membership.
    colls = [_original_collection(n) for n in snap['collections']]
    if not colls or any(c is None for c in colls): fail('missing_collection', 'A recovery collection is missing.')
    data = bpy.data.meshes.get(snap['data']) if obj.type == 'MESH' else obj.data
    if obj.type == 'MESH' and data is None: fail('missing_mesh', 'Original mesh datablock is missing.')
    for coll in colls:
        if obj.name not in coll.objects: coll.objects.link(obj)
    current_colls = (list(obj.users_collection) if memberships is None else
                     [_original_collection(name) for name in memberships.get(obj.as_pointer(), [])])
    for coll in current_colls:
        if coll not in colls: coll.objects.unlink(obj)
    if obj.type == 'MESH' and obj.data != data: obj.data = data
    authored = snap.get('authored_transform')
    if authored is None: fail('snapshot_upgrade_required', 'Recovery requires an authored-transform snapshot.')
    # Classification never changes these settings; do not write a stale cached
    # world matrix back through a parent/constraint during recovery.
    if authored_transform(obj) != authored:
        obj.rotation_mode = authored['rotation_mode']
        for name, value in authored.items():
            if name == 'rotation_mode': continue
            setattr(obj, name, Matrix(value) if name == 'matrix_parent_inverse' else value)
    obj.hide_render = snap['hide_render']; obj.hide_viewport = snap['hide_viewport']
    if not defer_visibility:
        bpy.context.view_layer.update()
        obj.hide_set(snap['hide_set'])


def apply(run, payload):
    candidate = run['proposals'].get(payload.get('proposal_id'), {})
    geometry_ids = [i['object_id'] for i in candidate.get('decisions', [])
                    if i.get('bake_scale') or i.get('unit_factor') is not None]
    before = capture(run, audit_ids=geometry_ids)
    if digest(before) != run['fingerprint']:
        fail('scene_changed', 'Scene changed outside the CAD tools; restore that edit or restart from source.')
    request_sig, old = replay(run, payload, 'apply')
    if old: return old
    preview = run['proposals'].get(payload.get('proposal_id'))
    if not preview: fail('missing_proposal', 'Analyze or propose before applying.')
    if preview['applied']: fail('already_applied', 'Proposal already applied; use its original request ID for replay.')
    if preview['revision'] != run['revision'] or preview['fingerprint'] != run['fingerprint']:
        fail('stale_proposal', 'Scene revision changed; create a fresh preview.')
    obs = objects(run)
    items = preview['decisions']
    indexes = relations()
    render_ids = render_eligible_ids()
    visible_ids = {o.as_pointer() for o in obs.values() if o.visible_get()}
    for item in items:
        obj = obs[item['object_id']]
        if item.get('bake_scale') or item.get('unit_factor') is not None:
            if item.get('unit_factor') is not None:
                from .state import validate_number
                factor=validate_number(item['unit_factor'],'unit_factor')
                if not 1e-6<=factor<=1000: fail('invalid_units','Unit factor exceeds safe execution bounds.')
            if obj.type != 'MESH' or not record(obj, item['object_id'], run, indexes)['geometry_supported']:
                fail('unsupported_geometry', 'Geometry changes require independent static meshes without dependencies.')
            if item.get('unit_factor') is not None and run['records'][item['object_id']]['unit_factor'] != 1:
                fail('units_already_changed', 'Undo the previous unit correction before applying another.')
            if min(obj.scale) <= 0: fail('unsupported_scale', 'Negative/zero scale requires review.')
            loc, rot, scale = obj.matrix_world.decompose()
            recomposed = Matrix.LocRotScale(loc, rot, scale)
            if max(abs(recomposed[r][c] - obj.matrix_world[r][c]) for r in range(4) for c in range(4)) > 1e-6:
                fail('unsupported_shear', 'Sheared transforms are preserved for review.')
        if item.get('operation') == 'park_duplicate':
            discarded = {i['object_id'] for i in items if i.get('operation') == 'park_duplicate'}
            compatible = [other for other_key, other in obs.items() if other_key not in discarded
                and other != obj and other.type == 'MESH' and other.data == obj.data
                and record(other, other_key, run)['geometry_supported']
                and other.matrix_world == obj.matrix_world and other.visible_get() == obj.visible_get()
                and _render_eligible(other) == _render_eligible(obj)
                and [s.material for s in other.material_slots] == [s.material for s in obj.material_slots]]
            if not record(obj, item['object_id'], run)['geometry_supported'] or not compatible:
                fail('unproven_duplicate', 'A surviving identical object with matching visibility is required.')
        if item.get('operation') == 'park_cull':
            if obj.children or obj.type != 'MESH':
                fail('protected_part', 'Protected parts and dependencies must remain identified or in review.')
        # Preflight collection collisions before any mutation.
        for name in item['destination']:
            coll = bpy.data.collections.get(name)
            if coll and coll.get(OWNER_KEY) != run['run_id']:
                fail('collection_collision', 'Destination is not owned by this cleanup run.')
    prior_records = {i['object_id']: copy.deepcopy(run['records'][i['object_id']]) for i in items}
    previous_stages = dict(run['stage_status'])
    existing_collections = {c.name for c in bpy.data.collections}
    existing_meshes = {m.name for m in bpy.data.meshes}
    fake_users = {obs[i['object_id']].data.name: obs[i['object_id']].data.use_fake_user
                  for i in items if obs[i['object_id']].type == 'MESH'}
    previous_revision = run['revision']
    previous_operations = len(run['operations'])
    modified = []
    pending_visibility = []
    try:
        for item in items:
            key = item['object_id']; obj = obs[key]
            was_visible = obj.as_pointer() in visible_ids
            # Preserve inherited render exclusion when leaving original collections.
            render_eligible = obj.as_pointer() in render_ids
            target = destination(run, item['destination'])
            if item.get('bake_scale') or item.get('unit_factor') is not None:
                obj.data.use_fake_user = True
                obj.data = obj.data.copy()
                if item.get('unit_factor') is not None:
                    obj.matrix_world = Matrix.Scale(item['unit_factor'], 4) @ obj.matrix_world
                if item.get('bake_scale'):
                    loc, rot, scale = obj.matrix_world.decompose()
                    obj.data.transform(Matrix.Diagonal(Vector(scale)).to_4x4())
                    obj.matrix_world = Matrix.Translation(loc) @ rot.to_matrix().to_4x4()
            if obj.name not in target.objects: target.objects.link(obj)
            for name in before['objects'][key]['collections']:
                coll = _original_collection(name)
                if coll != target: coll.objects.unlink(obj)
            hidden = not was_visible
            obj.hide_render = not render_eligible
            if item.get('presentation_hidden') is not None:
                original = run['baseline']['objects'][key]
                row = run['records'][key]
                hidden = True if item['presentation_hidden'] else not row.get('initial_visible', not original['hide_set'])
                obj.hide_render = True if item['presentation_hidden'] else not row.get('initial_render_eligible', not original['hide_render'])
            run['records'][key].update(category=item['category'], reason=item['reason'],
                                       confidence=item.get('confidence', 'agent_reviewed'))
            if item.get('unit_factor') is not None:
                run['records'][key]['unit_factor'] = item['unit_factor']
            modified.append(obj.name)
            pending_visibility.append((obj, hidden))
        # One dependency-graph rebuild for all membership changes, then restore
        # per-view-layer visibility on the newly established object bases.
        bpy.context.view_layer.update()
        for obj, hidden in pending_visibility: obj.hide_set(hidden)
        if preview.get('exclude_collections'):
            for layer in bpy.context.view_layer.layer_collection.children:
                if layer.collection.get(OWNER_KEY) == run['run_id'] and layer.name in preview['exclude_collections']:
                    layer.exclude = True
        bpy.context.view_layer.update()
        # An empty non-visibility stage changes only the local review journal.
        # The full preflight snapshot remains current within this main-thread call.
        after = before if not items and not preview.get('exclude_collections') else capture(run, audit_ids=geometry_ids)
        # Names, original mesh attributes, and transforms may change only as declared.
        for item in items:
            key = item['object_id']; a = before['objects'][key]; b = after['objects'][key]
            if not item.get('bake_scale') and item.get('unit_factor') is None:
                if a['geometry'] != b['geometry'] or a['authored_transform'] != b['authored_transform'] or a['parent'] != b['parent']:
                    logging.getLogger(__name__).error(
                        'CAD preservation failed for %s (%s): geometry_equal=%s authored_equal=%s world_delta=%s',
                        a['name'], key, a['geometry'] == b['geometry'], a['authored_transform'] == b['authored_transform'],
                        max(abs(a['matrix'][r][c] - b['matrix'][r][c]) for r in range(4) for c in range(4)))
                    fail('preservation_failed', 'Classification changed geometry or world transforms.')
        # Unit/geometry changes invalidate later analysis; all mutations invalidate delivery evidence.
        if any(i.get('unit_factor') is not None or i.get('bake_scale') for i in items):
            stage_keys=list(run['stage_status'])
            for s in stage_keys[stage_keys.index(preview['stage']) + 1:]: run['stage_status'][s] = 'pending'
        run['stage_status'][preview['stage']] = 'reviewed'
        run.setdefault('stage_notes', {})[preview['stage']] = preview.get('notes', [])
        run['revision'] += 1
        operation = {'operation_id': token(), 'revision': run['revision'],
                     'before': {i['object_id']: before['objects'][i['object_id']] for i in items},
                     'records_before': prior_records, 'stages_before': previous_stages,
                     'stage': preview['stage'], 'geometry_ids': geometry_ids, 'layer_states_before': before['layers'],
                     'after_fingerprint': digest(after), 'undone': False}
        run['operations'].append(operation)
        preview['applied'] = True
        refresh(run, snapshot=after)
    except Exception:
        logging.getLogger(__name__).exception('CAD apply failed; restoring the recorded pre-operation state')
        rollback_memberships, _ = relations()
        for item in reversed(items):
            key = item['object_id']; restore_snapshot(obs[key], before['objects'][key], rollback_memberships, True)
            run['records'][key] = prior_records[key]
        restore_layers(before['layers'])
        for coll in list(bpy.data.collections):
            if coll.name not in existing_collections and coll.get(OWNER_KEY) == run['run_id']:
                if coll.objects: fail('rollback_failed', 'Recovery encountered unexpected collection contents.')
                bpy.data.collections.remove(coll)
        for mesh in list(bpy.data.meshes):
            if mesh.name not in existing_meshes and mesh.users == 0: bpy.data.meshes.remove(mesh)
        for name, flag in fake_users.items():
            bpy.data.meshes[name].use_fake_user = flag
        bpy.context.view_layer.update()
        for item in items:
            key = item['object_id']; obs[key].hide_set(before['objects'][key]['hide_set'])
        run['stage_status'] = previous_stages
        run['revision'] = previous_revision
        del run['operations'][previous_operations:]
        preview['applied'] = False
        refresh(run)
        raise
    result = {'operation_id': operation['operation_id'], 'revision': run['revision'],
              'changed_count': len(items), 'modified_objects': modified[:100],
              'stage': preview['stage'], 'stage_status': 'reviewed'}
    return remember(run, payload, request_sig, result)


def _render_eligible(obj):
    if obj.hide_render: return False
    def walk(layer, blocked):
        blocked = blocked or layer.exclude or layer.collection.hide_render
        if not blocked and obj.name in layer.collection.objects: return True
        return any(walk(c, blocked) for c in layer.children)
    return walk(bpy.context.view_layer.layer_collection, False)


def restore_layers(states):
    def walk(layer, path):
        key = path + '/' + layer.name
        if key in states:
            s = states[key]
            layer.exclude = s['exclude']; layer.hide_viewport = s['hide_viewport']
            layer.collection.hide_viewport = s['collection_hide_viewport']
            layer.collection.hide_render = s['collection_hide_render']
        for child in layer.children: walk(child, key)
    walk(bpy.context.view_layer.layer_collection, '')


def _original_collection(name):
    if name == bpy.context.scene.collection.name: return bpy.context.scene.collection
    return bpy.data.collections.get(name)


def undo(run, payload):
    request_sig, old = replay(run, payload, 'undo')
    if old: return old
    operation = next((op for op in reversed(run['operations']) if not op['undone']), None)
    if not operation or operation['operation_id'] != payload.get('operation_id'):
        fail('undo_order', 'Undo the latest active operation first.')
    obs = objects(run)
    for key, snap in operation['before'].items():
        if any(_original_collection(n) is None for n in snap['collections']):
            fail('missing_collection', 'A recovery collection is missing; no changes applied.')
        if obs[key].type == 'MESH' and bpy.data.meshes.get(snap['data']) is None:
            fail('missing_mesh', 'A recovery mesh is missing; no changes applied.')
    memberships, _ = relations()
    for key, snap in operation['before'].items():
        restore_snapshot(obs[key], snap, memberships, True)
        run['records'][key] = operation['records_before'][key]
    restore_layers(operation['layer_states_before'])
    bpy.context.view_layer.update()
    for key, snap in operation['before'].items(): obs[key].hide_set(snap['hide_set'])
    operation['undone'] = True
    run['stage_status'] = operation['stages_before']
    run['revision'] += 1
    refresh(run)
    return remember(run, payload, request_sig, {'operation_id': operation['operation_id'],
                                               'revision': run['revision'], 'undone': True})
