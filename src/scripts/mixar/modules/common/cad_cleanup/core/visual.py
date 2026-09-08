# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Independent inspection render; source objects/settings are not modified."""
import base64
from pathlib import Path
import tempfile
import io
import re
from contextlib import redirect_stdout, redirect_stderr

import bpy
from mathutils import Matrix, Vector

from ..constants import VIEWS
from .state import fail, objects, persist, token


def cached_path(metadata):
    name = metadata.get('image_file', '')
    if not re.fullmatch(r'mixar-cad-view-[0-9a-f]{32}\.png', name): return None
    return Path(tempfile.gettempdir()) / 'mixar-cad-inspection' / name


def image_result(evidence, metadata, image, cached):
    return {'evidence_id': evidence, 'revision': metadata['revision'], 'view': metadata['view'],
            'image_base64': base64.b64encode(image).decode('ascii'), 'mime_type': 'image/png',
            'rendered_meshes': metadata['count'], 'cached': cached,
            'selection_id': metadata.get('selection_id'), 'visible_count': metadata.get('visible_count'),
            'render_seconds': metadata.get('render_seconds'),
            'setup_seconds': metadata.get('setup_seconds'), 'restore_seconds': metadata.get('restore_seconds'),
            'note': 'Solid inspection view: checks shape and placement, not final material transparency.'}


def render(run, payload):
    if payload.get('mode') == 'raster':
        from . import raster
        return raster.render(run, payload)
    view = payload.get('view', 'perspective')
    if view not in VIEWS: fail('invalid_view', 'Choose a supported inspection direction.')
    source = objects(run)
    mode = payload.get('mode', 'inspection')
    if mode not in ('inspection', 'raster'): fail('invalid_mode', 'Use inspection or raster.')
    delivery = payload.get('delivery', False)
    if type(delivery) is not bool: fail('invalid_mode', 'delivery must be boolean.')
    requested = payload.get('object_ids')
    selection_id = payload.get('selection_id')
    if selection_id:
        selected = run.get('selections', {}).get(selection_id)
        if requested is not None: fail('invalid_target', 'Use explicit IDs or a selection, not both.')
        if not selected or selected['revision'] != run['revision']:
            fail('stale_selection', 'Use a current selection.')
        requested = selected['object_ids']
    if requested is not None and (not isinstance(requested, list) or any(k not in source for k in requested)):
        fail('invalid_target', 'Render targets must be scoped object IDs.')
    if requested == []: fail('empty_render', 'An empty target list does not mean the whole assembly.')
    if delivery:
        if requested is not None: fail('invalid_target', 'Delivery view uses the complete kept set.')
        requested = [k for k, r in run.get('reference_assignments', {}).items() if r['disposition'] == 'keep']
        if not requested: fail('empty_render', 'Assign reference keep targets before rendering delivery.')
    targets = sorted(set(requested)) if requested else None
    for evidence, metadata in reversed(list(run['evidence'].items())):
        path = cached_path(metadata)
        if (metadata['revision'] == run['revision'] and metadata['view'] == view
                and metadata.get('fingerprint') == run['fingerprint']
                and metadata.get('mode', 'inspection') == mode
                and metadata.get('delivery', False) == delivery
                and (not delivery or metadata.get('assignment_revision') == run.get('assignment_revision'))
                and metadata.get('targets') == targets and path is not None and path.is_file()):
            return image_result(evidence, metadata, path.read_bytes(), True)
    chosen = [source[k] for k in requested] if requested else [
        obj for obj in source.values() if obj.type in ('MESH', 'CURVE', 'SURFACE', 'FONT', 'META') and obj.visible_get()]
    chosen = [o for o in chosen if (o.type == 'MESH' and o.data.polygons) or
              (mode == 'inspection' and o.type in ('CURVE', 'SURFACE', 'FONT', 'META'))]
    if not chosen: fail('empty_render', 'No mesh surfaces to inspect.')
    scene = bpy.data.scenes.new('CAD Inspection Temporary')
    copies = []
    light_data = []
    camera_data = None
    directory = Path(tempfile.gettempdir()) / 'mixar-cad-inspection'
    directory.mkdir(exist_ok=True)
    output = directory / ('mixar-cad-view-' + token() + '.png')
    retained = False
    try:
        points = []
        for obj in chosen:
            clone = obj.copy()
            # Evaluated object copy keeps parent dependency but resolves static world transform.
            clone.parent = None
            clone.matrix_world = obj.matrix_world.copy()
            clone.hide_render = clone.hide_viewport = False
            scene.collection.objects.link(clone)
            copies.append(clone)
            points.extend(obj.matrix_world @ Vector(c) for c in obj.bound_box)
        lo = Vector(tuple(min(p[i] for p in points) for i in range(3)))
        hi = Vector(tuple(max(p[i] for p in points) for i in range(3)))
        center = (lo + hi) / 2
        span = max((hi - lo).length, .01)
        camera_data = bpy.data.cameras.new('CAD Inspection Camera')
        camera = bpy.data.objects.new('CAD Inspection Camera', camera_data)
        scene.collection.objects.link(camera); copies.append(camera)
        camera.location = center + Vector(VIEWS[view]).normalized() * span * 2
        camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
        camera_data.type = 'ORTHO'; camera_data.ortho_scale = span * 1.1
        camera_data.clip_start = max(span / 10000, .00001); camera_data.clip_end = span * 10
        scene.camera = camera
        scene.render.engine = 'BLENDER_EEVEE' if mode == 'raster' else 'BLENDER_WORKBENCH'
        if mode == 'raster':
            if not hasattr(scene.render, 'visible_objects_json'):
                fail('raster_unavailable', 'This build lacks native visible-object capture.')
            scene.eevee.taa_render_samples = 8
            for axis in ((1, -1, 2), (-1, 1, 1)):
                lamp_data = bpy.data.lights.new('CAD Raster Light', 'SUN')
                light_data.append(lamp_data)
                lamp_data.energy = 2
                lamp_data.use_shadow = False
                lamp = bpy.data.objects.new('CAD Raster Light', lamp_data)
                scene.collection.objects.link(lamp)
                copies.append(lamp)
                lamp.rotation_euler = (-Vector(axis)).to_track_quat('-Z', 'Y').to_euler()
        scene.render.resolution_x = scene.render.resolution_y = 768
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = 'PNG'
        scene.render.filepath = str(output)
        scene.display.shading.light = 'STUDIO'
        scene.display.shading.color_type = 'MATERIAL'
        scene.display.shading.show_shadows = False
        scene.display.shading.show_cavity = True
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            kwargs = {'capture_visible_objects': True} if mode == 'raster' else {}
            status = bpy.ops.render.render(scene=scene.name, write_still=True, **kwargs)
        if status != {'FINISHED'} or not output.exists(): fail('render_failed', 'Inspection render did not complete.')
        evidence = token()
        reverse = {obj.as_pointer(): k for k, obj in source.items()}
        render_ids = [reverse[obj.as_pointer()] for obj in chosen]
        metadata = {'mode': mode, 'delivery': delivery,
                    'assignment_revision': run.get('assignment_revision', 0),
                    'render_ids': render_ids,
                    'camera': {'matrix': [list(r) for r in Matrix.LocRotScale(
                        camera.location, camera.rotation_euler.to_quaternion(), camera.scale)],
                               'corners': [list(p) for p in camera_data.view_frame(scene=scene)],
                               'clip_start': camera_data.clip_start, 'clip_end': camera_data.clip_end},
                    'revision': run['revision'], 'view': view, 'fingerprint': run['fingerprint'],
                    'targets': targets, 'image_file': output.name,
                    'count': len(chosen), 'scope': 'subset' if requested else 'visible_result'}
        if mode == 'raster':
            from mixar.modules.common.render_visibility.result import read_result
            from .reference import selection
            capture = read_result(scene)
            clone_ids = {clone.session_uid: object_id for clone, object_id in zip(copies, render_ids)}
            visible = []
            for entry in capture['objects']:
                if entry['session_uid'] not in clone_ids:
                    fail('unsupported_instance', 'Raster identity did not resolve to a scoped source mesh.')
                visible.append(clone_ids[entry['session_uid']])
            metadata['selection_id'] = selection(run, visible, evidence, 'raster_visible')
            metadata['visible_count'] = len(set(visible))
        if delivery: metadata['scope'] = 'reference_result'
        run['evidence'][evidence] = metadata
        # Keep bounded pixel evidence across reconnects. Old metadata remains for
        # review history; a missing image is regenerated, never claimed as fresh.
        image_entries = [m for m in run['evidence'].values() if m.get('image_file')]
        for old in image_entries[:-8]:
            path = cached_path(old)
            if path is not None: path.unlink(missing_ok=True)
            old.pop('image_file', None)
        persist(run)
        retained = True
        return image_result(evidence, metadata, output.read_bytes(), False)
    finally:
        # Each individual ID removal traverses Blender's relationships. Remove
        # only our temporary IDs in one batch; shared source meshes stay intact.
        temporary_ids = [*copies, *light_data, scene]
        if camera_data is not None: temporary_ids.append(camera_data)
        bpy.data.batch_remove(ids=temporary_ids)
        if not retained: output.unlink(missing_ok=True)


def review(run, payload):
    evidence = run['evidence'].get(payload.get('evidence_id'))
    if not evidence or evidence['revision'] != run['revision']:
        fail('stale_evidence', 'Render the current scene revision first.')
    verdict = payload.get('verdict')
    if verdict not in ('pass', 'fail') or not isinstance(payload.get('notes'), str) or not payload['notes'].strip():
        fail('invalid_review', 'Review requires a pass/fail verdict and concrete visual observations.')
    if evidence['scope'] == 'reference_result':
        if evidence.get('assignment_revision') != run.get('assignment_revision'):
            fail('stale_evidence', 'Render the current delivery assignments first.')
        run['reference_review'] = {'evidence_id': payload['evidence_id'], 'revision': run['revision'],
            'assignment_revision': run['assignment_revision'], 'verdict': verdict, 'notes': payload['notes'][:4000]}
        run.setdefault('reference_reviews', {})[evidence['view']] = run['reference_review']
        persist(run)
        return {'reviewed': True, **run['reference_review']}
    if evidence['scope'] != 'visible_result':
        fail('partial_evidence', 'Inspect the whole visible result before final delivery, not only a subset.')
    run['visual_review'] = {'evidence_id': payload['evidence_id'], 'revision': run['revision'],
                            'verdict': verdict, 'notes': payload['notes'][:4000]}
    persist(run)
    return {'reviewed': True, **run['visual_review']}
