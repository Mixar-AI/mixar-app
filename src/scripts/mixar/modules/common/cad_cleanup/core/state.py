# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Persisted local run state, exact scope, and change detection."""
import hashlib
import json
import math
import uuid

import bpy
import numpy as np

from ..constants import OBJECT_KEY, OWNER_KEY, STATE_KEY

_read_cache = None
_metadata_cache = None


def drop_cache():
    global _read_cache, _metadata_cache
    _read_cache = None
    _metadata_cache = None


def cache_metadata(run, snapshot):
    global _metadata_cache
    _metadata_cache = ((bpy.context.scene.as_pointer(),run['run_id'],run['fingerprint']),snapshot)


def check_targets(run, ids):
    """Validate target metadata and ancestors; full integrity remains a stage/save audit."""
    key=(bpy.context.scene.as_pointer(),run['run_id'],run['fingerprint'])
    if _metadata_cache is None or _metadata_cache[0]!=key:
        current=capture(run)
        if digest(current)!=run['fingerprint']: fail('scene_changed','Scene metadata changed outside the CAD tools.')
        cache_metadata(run,current)
        return
    expected=_metadata_cache[1]
    bpy.context.view_layer.update()
    obs=objects(run)
    requested=set(ids)
    if not requested<=obs.keys(): fail('invalid_target','Unknown target identity.')
    by_pointer={o.as_pointer():k for k,o in obs.items()}
    for k in list(requested):
        parent=obs[k].parent
        while parent:
            parent_key=by_pointer.get(parent.as_pointer())
            if parent_key is None:
                # Scoped roots can depend on external ancestors: use the full boundary.
                current=capture(run)
                if digest(current)!=run['fingerprint']: fail('scene_changed','Ancestor context changed.')
                cache_metadata(run,current)
                return
            requested.add(parent_key); parent=parent.parent
    memberships,_=relations()
    hashes={o.data.as_pointer():run['geometry_hashes'][o.data.name] for o in obs.values()
            if o.type=='MESH' and o.data and o.data.name in run.get('geometry_hashes',{})}
    if (bpy.context.scene.frame_current!=expected['frame'] or layer_states()!=expected['layers'] or
            sorted(o.name for o in bpy.context.scene.objects)!=expected['scene_objects']):
        fail('scene_changed','Scene membership, frame or visibility changed outside the pipeline.')
    for k in requested:
        if signature(obs[k],hashes,memberships)!=expected['objects'][k]:
            fail('scene_changed','A targeted object or ancestor changed; refresh and resolve the edit before continuing.')


class CadError(RuntimeError):
    def __init__(self, code, message, details=None):
        self.code = code
        self.details = details or {}
        super().__init__(message)


def fail(code, message, details=None):
    raise CadError(code, message, details)


def token():
    return uuid.uuid4().hex


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def matrix(obj):
    return [list(row) for row in obj.matrix_world]


def authored_transform(obj):
    """Raw transform settings remain authoritative even when depsgraph caches are cold."""
    names = ('location', 'scale', 'rotation_euler', 'rotation_quaternion',
             'rotation_axis_angle', 'delta_location', 'delta_scale',
             'delta_rotation_euler', 'delta_rotation_quaternion')
    result = {name: list(getattr(obj, name)) for name in names}
    result['rotation_mode'] = obj.rotation_mode
    result['matrix_parent_inverse'] = [list(row) for row in obj.matrix_parent_inverse]
    return result


def mesh_digest(mesh):
    """Topology and supported attributes, not a vertex-cloud duplicate key."""
    h = hashlib.sha256()
    for items, prop, width, dtype in (
            (mesh.vertices, 'co', 3, np.float32), (mesh.edges, 'vertices', 2, np.int32),
            (mesh.loops, 'vertex_index', 1, np.int32),
            (mesh.polygons, 'loop_start', 1, np.int32),
            (mesh.polygons, 'loop_total', 1, np.int32),
            (mesh.polygons, 'material_index', 1, np.int32),
            (mesh.polygons, 'use_smooth', 1, np.bool_)):
        values = np.empty(len(items) * width, dtype=dtype)
        items.foreach_get(prop, values)
        h.update(prop.encode()); h.update(values.tobytes())
    for attr in mesh.attributes:
        h.update((attr.name + attr.data_type + attr.domain).encode())
        field = {'FLOAT': ('value', 1), 'INT': ('value', 1), 'BOOLEAN': ('value', 1),
                 'FLOAT_VECTOR': ('vector', 3), 'FLOAT2': ('vector', 2),
                 'FLOAT_COLOR': ('color', 4), 'BYTE_COLOR': ('color', 4)}.get(attr.data_type)
        if field:
            values = np.empty(len(attr.data) * field[1], dtype=np.float64)
            attr.data.foreach_get(field[0], values)
            h.update(values.tobytes())
    if mesh.shape_keys:
        for block in mesh.shape_keys.key_blocks:
            values = np.empty(len(block.data) * 3, dtype=np.float32)
            block.data.foreach_get('co', values)
            h.update(block.name.encode()); h.update(values.tobytes())
    return h.hexdigest()


def relations():
    """Build reverse indexes once; Blender's object convenience accessors scan data."""
    memberships = {}
    children = set()
    for obj in bpy.data.objects:
        if obj.parent: children.add(obj.parent.as_pointer())
    collections = {c.as_pointer(): c for c in bpy.data.collections}
    collections.update({s.collection.as_pointer(): s.collection for s in bpy.data.scenes})
    for coll in collections.values():
        for obj in coll.objects:
            memberships.setdefault(obj.as_pointer(), []).append(coll.name)
    return memberships, children


def render_eligible_ids():
    """Union all unblocked layer paths, including multiply linked collections."""
    result = set()
    stack = [bpy.context.view_layer.layer_collection]
    while stack:
        layer = stack.pop()
        if layer.exclude or layer.collection.hide_render: continue
        result.update(o.as_pointer() for o in layer.collection.objects if not o.hide_render)
        stack.extend(layer.children)
    return result


def signature(obj, cache, memberships=None):
    data = obj.data
    if obj.type == 'MESH' and data is not None:
        key = data.as_pointer()
        if key not in cache: cache[key] = mesh_digest(data)
        geometry = cache[key]
    else:
        geometry = None
    return {'name': obj.name, 'type': obj.type, 'matrix': matrix(obj),
            'authored_transform': authored_transform(obj),
            'data': data.name if data else None, 'geometry': geometry,
            'parent': obj.parent.name if obj.parent else None,
            'collections': sorted(memberships[obj.as_pointer()] if memberships is not None else
                                  (c.name for c in obj.users_collection)),
            'hide_render': obj.hide_render, 'hide_viewport': obj.hide_viewport,
            'hide_set': obj.hide_get(),
            'materials': [s.material.name if s.material else None for s in obj.material_slots],
            'modifiers': [rna_settings(m) for m in obj.modifiers],
            'constraints': [rna_settings(c) for c in obj.constraints]}


def rna_settings(block):
    """Include modifier/constraint numeric settings so stale previews detect edits."""
    result = {}
    for prop in block.bl_rna.properties:
        if prop.identifier == 'rna_type' or prop.type == 'COLLECTION': continue
        value = getattr(block, prop.identifier, None)
        if prop.type == 'POINTER':
            result[prop.identifier] = getattr(value, 'name', None)
        elif getattr(prop, 'is_array', False):
            result[prop.identifier] = list(value)
        elif isinstance(value, (str, int, float, bool)) or value is None:
            result[prop.identifier] = value
    return result


def layer_states():
    result = {}
    def walk(layer, path):
        key = path + '/' + layer.name
        result[key] = {'exclude': layer.exclude, 'hide_viewport': layer.hide_viewport,
                       'collection_hide_viewport': layer.collection.hide_viewport,
                       'collection_hide_render': layer.collection.hide_render}
        for child in layer.children: walk(child, key)
    walk(bpy.context.view_layer.layer_collection, '')
    return result


def objects(run):
    ids = set(run['records'])
    found = {}
    for obj in bpy.context.scene.objects:
        key = obj.get(OBJECT_KEY)
        if key in ids:
            if key in found: fail('duplicate_identity', 'Two objects share a CAD identity; restart from source.')
            found[key] = obj
    if found.keys() != ids:
        fail('scope_changed', 'A scoped object is missing. Restore it before continuing.')
    return found


def capture(run, *, full=False, audit_ids=()):
    """Cached hashes are expectations, not fresh geometry evidence.

    Audit targets include shared mesh data regardless of collection membership.
    Only baseline and delivery audits read all scoped mesh buffers.
    """
    bpy.context.view_layer.update()
    obs = objects(run)
    audit_ids = set(audit_ids)
    audited = {ob.data.as_pointer() for key, ob in obs.items()
               if key in audit_ids and ob.type == 'MESH' and ob.data is not None}
    expected = run.get('geometry_hashes', {})
    cache = {ob.data.as_pointer(): expected[ob.data.name]
             for ob in obs.values() if ob.type == 'MESH' and ob.data is not None
             and not full and ob.data.as_pointer() not in audited and ob.data.name in expected}
    memberships, _ = relations()
    return {'objects': {key: signature(obj, cache, memberships) for key, obj in obs.items()},
            'layers': layer_states(), 'frame': bpy.context.scene.frame_current,
            'scene_objects': sorted(o.name for o in bpy.context.scene.objects)}


def persist(run):
    global _read_cache
    raw = json.dumps(run, separators=(',', ':'), allow_nan=False)
    bpy.context.scene[STATE_KEY] = raw
    _read_cache = (bpy.context.scene.as_pointer(), raw, run)


def read(payload, check=True):
    global _read_cache
    raw = bpy.context.scene.get(STATE_KEY)
    if not raw: fail('no_run', 'Start a CAD cleanup run first.')
    pointer = bpy.context.scene.as_pointer()
    if _read_cache is not None and _read_cache[0] == pointer and _read_cache[1] == raw:
        run = _read_cache[2]
    else:
        run = json.loads(raw)
        _read_cache = (pointer, raw, run)
    if run.get('snapshot_version', 1) < 3:
        fail('snapshot_upgrade_required', 'Restart from the original project for checkpoint validation.')
    if run['owner_id'] != payload.get('owner_id'):
        fail('wrong_owner', 'This cleanup belongs to a different agent task.')
    if payload.get('run_id') not in (None, run['run_id']):
        fail('wrong_run', 'This run is not active in the current scene.')
    if payload.get('request_id') and not payload.get('run_id'):
        if payload['request_id'] not in run.get('start_request_ids', [run['start_request_id']]):
            fail('wrong_request', 'No run matches that start request.')
    if bpy.context.view_layer.name != run['view_layer']:
        fail('view_layer_changed', 'Return to the cleanup view layer before continuing.')
    if check:
        snapshot=capture(run)
        if digest(snapshot) != run['fingerprint']:
            fail('scene_changed', 'Scene changed outside the CAD tools; restore that edit or restart from source.')
        cache_metadata(run,snapshot)
    if ('expected_revision' in payload and payload['expected_revision'] != run['revision']
            and payload.get('request_id') not in run['requests']):
        fail('stale_revision', 'Inspect the current revision before retrying.')
    return run


def refresh(run, snapshot=None):
    snapshot = capture(run) if snapshot is None else snapshot
    # Keep original recovery mesh hashes when geometry edits create new data.
    run.setdefault('geometry_hashes', {}).update({s['data']: s['geometry']
        for s in snapshot['objects'].values() if s['geometry'] is not None})
    run['fingerprint'] = digest(snapshot)
    cache_metadata(run,snapshot)
    run['stage_checks'] = {}
    run['verified_revision'] = None
    run['artifact'] = None
    run['visual_review'] = None
    persist(run)


def start(payload):
    if not payload.get('owner_id') or not payload.get('request_id'):
        fail('invalid_request', 'owner_id and request_id are required.')
    if bpy.context.scene.get(STATE_KEY):
        run = read(payload)
        if payload.get('workflow') is not None and run.get('workflow') and {k:v for k,v in payload['workflow'].items() if k!='version'}!={k:v for k,v in run['workflow'].items() if k!='version'}:
            fail('request_conflict','A resumed run cannot change its collection schema.')
        if payload.get('run_id'):
            if payload.get('root_collection') not in (None, run['root_collection']):
                fail('request_conflict', 'Resuming cannot change scope.')
            aliases = run.setdefault('start_request_ids', [run['start_request_id']])
            if payload['request_id'] not in aliases: aliases.append(payload['request_id'])
            persist(run)
        elif run['root_collection'] != payload.get('root_collection'):
            fail('request_conflict', 'A start request cannot change its scope.')
        return run
    if not isinstance(payload.get('workflow'),dict) or payload['workflow'].get('version') != 3:
        fail('collection_schema_required','Supply a collection hierarchy to start a fresh run.')
    if bpy.context.mode != 'OBJECT': fail('object_mode_required', 'Exit Edit mode before cleanup.')
    root_name = payload.get('root_collection')
    root = bpy.data.collections.get(root_name) if root_name else bpy.context.scene.collection
    if root is None: fail('missing_collection', 'The requested collection does not exist.')
    scene_ids = {o.as_pointer() for o in bpy.context.scene.objects}
    scope = list(root.all_objects)
    if not scope: fail('empty_scope', 'No objects in the requested scope.')
    other_scene_ids = {o.as_pointer() for scene in bpy.data.scenes if scene != bpy.context.scene
                       for o in scene.objects}
    for obj in scope:
        if obj.as_pointer() not in scene_ids or obj.library or obj.override_library or obj.as_pointer() in other_scene_ids:
            fail('unsupported_scope', 'Linked, overridden, or multi-scene objects need a local independent copy.')
    # Managed names must never commandeer an unrelated collection.
    for coll in bpy.data.collections:
        if coll.name in ('01_IDENTIFIED', '02_NOT_NEEDED', '03_NEEDS_REVIEW') or coll.get(OWNER_KEY):
            fail('existing_pipeline', 'Use the original source or resume the original cleanup task.')
    run = {'snapshot_version': 3, 'run_id': token(), 'owner_id': payload['owner_id'], 'start_request_id': payload['request_id'],
           'root_collection': root_name, 'source_file': bpy.data.filepath,
           'view_layer': bpy.context.view_layer.name, 'revision': 0, 'records': {},
           'stage_status': {s: 'pending' for s in payload['workflow']['stage_keys']}, 'proposals': {}, 'operations': [],
           'requests': {}, 'artifact': None, 'verified_revision': None, 'visual_review': None,
           'evidence': {}, 'source_scene_objects': sorted(o.name for o in bpy.context.scene.objects)}
    render_ids = render_eligible_ids()
    # Read visibility before assigning ID properties, which tag dependency updates.
    visible_ids = {o.as_pointer() for o in scope if o.visible_get()}
    for obj in scope:
        key = token()
        obj[OBJECT_KEY] = key
        run['records'][key] = {'name': obj.name, 'category': None, 'reason': 'Not classified',
                               'confidence': 'low', 'unit_factor': 1.0,
                               'initial_visible': obj.as_pointer() in visible_ids,
                               'initial_render_eligible': obj.as_pointer() in render_ids}
    run['baseline'] = capture(run, full=True)
    refresh(run, snapshot=run['baseline'])
    persist(run)
    return run


def record(obj, key, run, indexes=None):
    return {'object_id': key, 'name': obj.name, 'type': obj.type,
            'category': run['records'][key]['category'], 'dimensions': list(obj.dimensions),
            'polygons': len(obj.data.polygons) if obj.type == 'MESH' else 0,
            'parent': obj.parent.name if obj.parent else None,
            'scale': list(obj.scale),
            'duplicate_key': digest({'data':obj.data.as_pointer() if obj.data else None,
                'matrix':matrix(obj),'visible':obj.visible_get(),
                'render_eligible':obj.as_pointer() in indexes[2],
                'materials':[s.material.name if s.material else None for s in obj.material_slots]}) if indexes and len(indexes)>2 else None,
            'collections': (indexes[0][obj.as_pointer()] if indexes is not None else
                            [c.name for c in obj.users_collection]),
            'geometry_supported': not bool(obj.parent or
                (obj.as_pointer() in indexes[1] if indexes is not None else obj.children) or obj.modifiers or
                obj.constraints or obj.animation_data or (obj.type == 'MESH' and obj.data.shape_keys))}


def validate_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        fail('invalid_number', name + ' must be a finite number.')
    return value
