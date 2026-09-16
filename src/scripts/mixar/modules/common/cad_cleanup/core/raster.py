# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Native Eevee render jobs in the existing scene, with reversible setup."""
import time
import tempfile
from pathlib import Path
import bpy
from mathutils import Matrix, Vector

from ..constants import VIEWS
from . import state, reference

_job = None


def busy():
    return _job is not None


def progress():
    return {'status': 'running', 'mode': 'raster', 'retry_after_seconds': 10,
            'elapsed_seconds': round(time.monotonic()-_job['started'], 1),
            'note': 'Native render job is running. Retry cad_render with identical arguments to retrieve pixels and IDs; do not start another render.'}


def layer_tree(layer):
    yield layer
    for child in layer.children:
        yield from layer_tree(child)


def restore(job):
    scene = job['scene']
    scene.camera = job['camera']
    scene.world = job['world']
    for name, value in job['render_settings'].items(): setattr(scene.render, name, value)
    for name, value in job['image_settings'].items(): setattr(scene.render.image_settings, name, value)
    for name, value in job['eevee_settings'].items(): setattr(scene.eevee, name, value)
    for obj, hidden in job['objects']:
        if obj.hide_render != hidden: obj.hide_render = hidden
    for coll, hidden in job['collections']:
        if coll.hide_render != hidden: coll.hide_render = hidden
    for layer, excluded in job['layers']:
        if layer.exclude != excluded: layer.exclude = excluded
    for layer, enabled in job['view_layers']:
        if layer.use != enabled: layer.use = enabled
    if job.get('isolation_layer') is not None:
        scene.view_layers.remove(job['isolation_layer'])
    bpy.data.batch_remove(ids=job['created'])
    job['view_layer'].update()
    for obj, hidden in job['base_visibility']:
        if obj.hide_get(view_layer=job['view_layer']) != hidden:
            obj.hide_set(hidden, view_layer=job['view_layer'])


def finish():
    global _job
    if _job is None: return None
    if bpy.app.is_job_running('RENDER'): return .5
    job = _job
    run = job['run']
    result_error = None
    metadata = job['metadata']
    try:
        from mixar.modules.common.render_visibility.result import read_result
        capture = read_result(job['scene'])
        if not job['output'].is_file(): state.fail('render_cancelled', 'Raster job produced no image; retry when ready.')
        visible = []
        for entry in capture['objects']:
            key = job['by_uid'].get(entry['session_uid'])
            if key is None: state.fail('unsupported_instance', 'Captured identity is outside this scoped source.')
            visible.append(key)
        metadata['visible_count'] = len(set(visible))
        metadata['render_seconds'] = time.monotonic()-job['render_started']
    except Exception as exc:
        result_error = {'code': getattr(exc, 'code', 'render_failed'),
                        'message': str(exc) if isinstance(exc, state.CadError) else 'Native raster capture did not complete.'}
    try:
        with bpy.context.temp_override(scene=job['scene'], view_layer=job['view_layer']):
            restore_started = time.monotonic()
            restore(job)
            metadata['restore_seconds'] = time.monotonic()-restore_started
            if result_error is None:
                from .visual import cached_path
                metadata['selection_id'] = reference.selection(run, visible, job['evidence_id'], 'raster_visible')
                run['evidence'][job['evidence_id']] = metadata
                images = [m for m in run['evidence'].values() if m.get('image_file')]
                for old in images[:-8]:
                    path = cached_path(old)
                    if path: path.unlink(missing_ok=True)
                    old.pop('image_file', None)
                run['raster_job'] = {'status': 'complete', 'evidence_id': job['evidence_id']}
            else:
                job['output'].unlink(missing_ok=True)
                run['raster_job'] = {'status': 'failed', 'error': result_error}
            state.persist(run)
    finally:
        _job = None
    return None


def render(run, payload):
    global _job
    if _job is not None: return progress()
    if bpy.app.background:
        state.fail('gui_required', 'Native CAD raster capture uses an interactive Blender render job.')
    if bpy.app.is_job_running('RENDER'): state.fail('render_busy', 'Wait for the current render job.')
    if run.get('raster_job', {}).get('status') == 'failed':
        error = run.pop('raster_job')['error']
        state.persist(run)
        return {'success': False, 'error': error}
    from .visual import cached_path, image_result
    source = state.objects(run)
    view = payload.get('view', 'perspective')
    if view not in VIEWS: state.fail('invalid_view', 'Choose a supported inspection direction.')
    requested = payload.get('object_ids')
    if payload.get('selection_id'):
        selected = run.get('selections', {}).get(payload['selection_id'])
        if requested is not None: state.fail('invalid_target', 'Use IDs or a selection, not both.')
        if not selected or selected['revision'] != run['revision']: state.fail('stale_selection', 'Use a current selection.')
        requested = selected['object_ids']
    delivery = payload.get('delivery', False)
    if type(delivery) is not bool: state.fail('invalid_target', 'delivery must be boolean.')
    if delivery:
        if requested is not None: state.fail('invalid_target', 'Delivery uses the complete kept set.')
        requested = [k for k, r in run.get('reference_assignments', {}).items() if r['disposition'] == 'keep']
    if requested is not None and (not isinstance(requested, list) or not requested or any(k not in source for k in requested)):
        state.fail('invalid_target', 'Provide nonempty scoped object IDs.')
    targets = sorted(set(requested)) if requested is not None else None
    for key, metadata in reversed(list(run['evidence'].items())):
        path = cached_path(metadata)
        if (metadata.get('mode') == 'raster' and metadata['revision'] == run['revision']
                and metadata.get('fingerprint') == run['fingerprint'] and metadata['view'] == view
                and metadata.get('targets') == targets and metadata.get('delivery', False) == delivery
                and (not delivery or metadata.get('assignment_revision') == run.get('assignment_revision'))
                and path and path.is_file()):
            return image_result(key, metadata, path.read_bytes(), True)
    eligible = state.render_eligible_ids()
    chosen = {k: source[k] for k in targets} if targets is not None else {
        k: o for k, o in source.items() if o.as_pointer() in eligible}
    chosen = {k: o for k, o in chosen.items() if o.type == 'MESH' and o.data.polygons}
    if not chosen: state.fail('empty_render', 'No mesh surfaces to capture.')
    scene = bpy.context.scene
    if not hasattr(scene.render, 'visible_objects_json'): state.fail('raster_unavailable', 'Native visibility capture is missing.')
    directory = Path(tempfile.gettempdir())/'mixar-cad-inspection'
    directory.mkdir(exist_ok=True)
    output = directory/('mixar-cad-view-'+state.token()+'.png')
    render_fields = ('engine','resolution_x','resolution_y','resolution_percentage','filepath',
                     'film_transparent','use_compositing','use_sequencer','use_border',
                     'use_multiview','use_motion_blur','use_lock_interface')
    job = {'run': run, 'scene': scene, 'view_layer': bpy.context.view_layer,
           'camera': scene.camera, 'world': scene.world, 'created': [],
           'render_settings': {k: getattr(scene.render,k) for k in render_fields},
           'image_settings': {k: getattr(scene.render.image_settings,k) for k in ('file_format','color_mode')},
           'eevee_settings': {k: getattr(scene.eevee,k) for k in ('taa_render_samples','use_raytracing')},
           'objects': [(o,o.hide_render) for o in scene.objects],
           'base_visibility': [(o,o.hide_get()) for o in bpy.context.view_layer.objects],
           'collections': [(c,c.hide_render) for c in bpy.data.collections],
           'layers': [(l,l.exclude) for l in layer_tree(bpy.context.view_layer.layer_collection)],
           'view_layers': [(l,l.use) for l in scene.view_layers],
           'output': output, 'evidence_id':state.token(),
           'by_uid': {o.session_uid:k for k,o in chosen.items()}, 'started':time.monotonic()}
    try:
        # Keep original object/mesh IDs. A subset gets a temporary collection and
        # view layer, so we never hide and restore 20,000 unrelated mesh objects.
        wanted = {o.as_pointer() for o in chosen.values()}
        render_layer = job['view_layer']
        setup_collection = scene.collection
        if targets is not None or run.get('root_collection'):
            setup_collection = bpy.data.collections.new('CAD Raster Subset')
            job['created'].append(setup_collection)
            scene.collection.children.link(setup_collection)
            for obj in chosen.values():
                setup_collection.objects.link(obj)
                if obj.hide_render: obj.hide_render = False
            render_layer = scene.view_layers.new('CAD Raster Subset')
            job['isolation_layer'] = render_layer
            for child in render_layer.layer_collection.children:
                if child.collection != setup_collection: child.exclude = True
            # Objects directly in the scene root cannot be collection-excluded.
            for obj in scene.collection.objects:
                if obj.type not in ('EMPTY','CAMERA','ARMATURE') and obj.as_pointer() not in wanted and not obj.hide_render:
                    obj.hide_render = True
        for layer in scene.view_layers:
            enabled = layer == render_layer
            if layer.use != enabled: layer.use = enabled
        points = [o.matrix_world @ Vector(c) for o in chosen.values() for c in o.bound_box]
        lo = Vector(tuple(min(p[i] for p in points) for i in range(3)))
        hi = Vector(tuple(max(p[i] for p in points) for i in range(3)))
        center = (lo+hi)/2
        span = max((hi-lo).length,.01)
        data = bpy.data.cameras.new('CAD Raster Camera')
        camera = bpy.data.objects.new('CAD Raster Camera',data)
        job['created'].extend([camera,data])
        setup_collection.objects.link(camera)
        camera.location = center+Vector(VIEWS[view]).normalized()*span*2
        camera.rotation_euler = (center-camera.location).to_track_quat('-Z','Y').to_euler()
        data.type='ORTHO'; data.ortho_scale=span*1.1
        data.clip_start=max(span/10000,.00001); data.clip_end=span*10
        scene.camera=camera
        for axis in ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)):
            lamp_data=bpy.data.lights.new('CAD Raster Light','SUN')
            lamp=bpy.data.objects.new('CAD Raster Light',lamp_data)
            job['created'].extend([lamp,lamp_data])
            setup_collection.objects.link(lamp)
            lamp_data.energy=.8; lamp_data.use_shadow=False
            lamp.rotation_euler=(-Vector(axis)).to_track_quat('-Z','Y').to_euler()
        world=bpy.data.worlds.new('CAD Raster World'); job['created'].append(world)
        world.use_nodes=True
        world.node_tree.nodes['Background'].inputs[0].default_value=(.08,.08,.08,1)
        scene.world=world
        scene.render.engine='BLENDER_EEVEE'
        scene.render.resolution_x=scene.render.resolution_y=768
        scene.render.resolution_percentage=100
        scene.render.filepath=str(output)
        scene.render.image_settings.file_format='PNG'; scene.render.image_settings.color_mode='RGBA'
        for name in ('film_transparent','use_compositing','use_sequencer','use_border','use_multiview','use_motion_blur'):
            setattr(scene.render,name,False)
        scene.render.use_lock_interface=True
        scene.eevee.taa_render_samples=8; scene.eevee.use_raytracing=False
        render_layer.update()
        job['metadata']={'mode':'raster','delivery':delivery,'assignment_revision':run.get('assignment_revision',0),
            'revision':run['revision'],'view':view,'fingerprint':run['fingerprint'],'targets':targets,
            'render_ids':list(chosen),'image_file':output.name,'count':len(chosen),
            'scope':'reference_result' if delivery else ('subset' if targets else 'visible_result'),
            'camera':{'matrix':[list(r) for r in Matrix.LocRotScale(camera.location,
                        camera.rotation_euler.to_quaternion(),camera.scale)],
                      'corners':[list(p) for p in data.view_frame(scene=scene)],
                      'clip_start':data.clip_start,'clip_end':data.clip_end}}
        job['render_started'] = time.monotonic()
        job['metadata']['setup_seconds'] = job['render_started']-job['started']
        status=bpy.ops.render.render('INVOKE_DEFAULT',layer=render_layer.name,write_still=True,capture_visible_objects=True)
        if status != {'RUNNING_MODAL'}: state.fail('render_failed','Native render job did not start.')
        _job=job
        bpy.app.timers.register(finish,first_interval=.5)
        return progress()
    except Exception:
        restore(job)
        raise
