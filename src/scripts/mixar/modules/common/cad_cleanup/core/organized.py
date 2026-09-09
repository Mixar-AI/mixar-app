# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Materialize reference decisions without changing the source or its evidence.

The organized scene shares geometry, but owns its objects and collections. Only
major checkpoints synchronize it. Diagnostic groups remain in the recovery scene.
"""
from collections import Counter
import bpy
from . import state, reference, assignment_receipts
from ..constants import OBJECT_KEY

OWNER = 'cad_organized_run'
SOURCE = 'cad_organized_source'
PATH = 'cad_reference_path'
REQUIRED = ('MESH', 'CURVE', 'SURFACE', 'FONT', 'META')


def destination(run, key, allowed):
    row = run.get('reference_assignments', {}).get(key, {})
    config=run['workflow']['organization']
    if not row or row.get('disposition') == 'review' or not assignment_receipts.accepted(run, row):
        return config['review_path']
    if row['disposition'] == 'keep':
        return row['path'] if row.get('path') in allowed else config['review_path']
    if row['disposition'] == 'hidden_internal':
        return config['hidden_path']
    return None  # Affirmative omissions remain recoverable in the source.


def require_static(objects):
    for obj in objects:
        chain = obj
        while chain:
            if chain.animation_data or chain.constraints:
                state.fail('unsupported_dependency', 'Animated/constrained parts require dependency-preserving export.')
            chain = chain.parent
        if (obj.modifiers or obj.instance_type != 'NONE' or
                (obj.type == 'MESH' and obj.data.shape_keys)):
            state.fail('unsupported_dependency', 'Instanced/modified/shape-key parts require dependency-preserving export.')


def sync(run, force=False):
    """Refresh changed memberships; no mesh buffer reads or semantic re-review."""
    scenes = [s for s in bpy.data.scenes if s.get(OWNER) == run['run_id']]
    if len(scenes) > 1:
        state.fail('organized_collision', 'Multiple organized scenes claim this run.')
    scene = scenes[0] if scenes else None
    previous = run.get('organized', {})
    stamp = [run['revision'], run.get('assignment_revision', 0)]
    if scene and not force and previous.get('stamp') == stamp:
        return previous
    source = state.objects(run)
    allowed = assignment_receipts.leaves(reference.profile(run))
    routes = {k: destination(run, k, allowed) for k, o in source.items() if o.type in REQUIRED}
    wanted = {k: path for k, path in routes.items() if path is not None}
    # A checkpoint is metadata-only. Final verification/save audits mesh buffers.
    changed = {k for k in wanted if previous.get('routes', {}).get(k) != wanted[k]}
    if previous.get('stamp', [None])[0] != run['revision'] or force:
        changed = set(wanted)
    state.check_targets(run, changed)
    require_static(source[k] for k in wanted)
    paths = set()
    for path in wanted.values():
        parts = path.split('/')
        paths.update('/'.join(parts[:i]) for i in range(1, len(parts) + 1))
    collections = {}
    for path in paths:
        coll = bpy.data.collections.get(path.rsplit('/', 1)[-1])
        if coll and (coll.get(OWNER) != run['run_id'] or coll.get(PATH) != path):
            state.fail('reference_collision', 'A required collection name belongs to unrelated source data: ' + path)
        if coll:
            collections[path] = coll
    existing = {o.get(SOURCE): o for o in scene.objects} if scene else {}
    if scene and (len(existing) != len(scene.objects) or None in existing or
                  any(o.get(OWNER) != run['run_id'] for o in scene.objects)):
        state.fail('organized_collision', 'Organized scene contains foreign objects; preserve those edits separately.')
    created = []
    replacements = {}
    linked = []
    try:
        if scene is None:
            scene = bpy.data.scenes.new('CAD Organized')
            scene[OWNER] = run['run_id']
            created.append(scene)
        for path in sorted(paths, key=lambda p: (p.count('/'), p)):
            if path not in collections:
                coll = bpy.data.collections.new(path.rsplit('/', 1)[-1])
                created.append(coll)
                coll[OWNER] = run['run_id']; coll[PATH] = path
                collections[path] = coll
            coll = collections[path]
            parent = collections[path.rpartition('/')[0]] if '/' in path else scene.collection
            if coll.name not in parent.children:
                parent.children.link(coll); linked.append((parent, coll))
        # Build replacements before touching previous copies, so failures roll back.
        for key, path in wanted.items():
            if key not in changed and key in existing:
                continue
            obj = source[key]
            clone = obj.copy(); created.append(clone)
            if OBJECT_KEY in clone: del clone[OBJECT_KEY]
            clone.parent = None; clone.matrix_world = obj.matrix_world.copy()
            clone.hide_viewport = clone.hide_render = False
            clone[OWNER] = run['run_id']; clone[SOURCE] = key
            clone['cad_source_name'] = obj.name
            clone['cad_decision_reason'] = run.get('reference_assignments', {}).get(key, {}).get('reason', 'Unresolved')
            clone[PATH] = path
            collections[path].objects.link(clone)
            replacements[key] = clone
    except Exception:
        for parent, coll in reversed(linked): parent.children.unlink(coll)
        bpy.data.batch_remove(ids=created)
        raise
    retired = [o for k, o in existing.items() if k not in wanted or k in replacements]
    if retired: bpy.data.batch_remove(ids=retired)
    # Only this run's empty collection shells may be pruned.
    for coll in sorted([c for c in bpy.data.collections if c.get(OWNER) == run['run_id']],
                       key=lambda c: c.get(PATH, '').count('/'), reverse=True):
        if coll.get(PATH) not in paths and not coll.objects and not coll.children:
            bpy.data.collections.remove(coll)
    for path, coll in collections.items():
        coll.hide_render = coll.hide_viewport = path == run['workflow']['organization']['hidden_path']
    receipt = {'scene': scene.name, 'stamp': stamp, 'routes': routes,
               'counts': dict(Counter(wanted.values())), 'objects': len(wanted),
               'omitted': sum(p is None for p in routes.values()),
               'updated_objects': len(replacements), 'source_preserved': True}
    run['organized'] = receipt
    state.persist(run)
    return receipt


def public(run):
    receipt = run.get('organized', {})
    return {**{k: v for k, v in receipt.items() if k not in ('routes',)},
            'current': receipt.get('stamp') == [run['revision'], run.get('assignment_revision', 0)]}


def scene_for(run):
    return next(s for s in bpy.data.scenes if s.get(OWNER) == run['run_id'])
