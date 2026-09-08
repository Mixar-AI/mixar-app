# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Verification and copy-only delivery. Absolute paths never leave this module."""
import json
import os
import io
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

import bpy

from ..constants import OBJECT_KEY, STAGES
from .mutations import _render_eligible, remember, replay
from .state import capture, digest, fail, objects, persist, token, render_eligible_ids


def summary(run):
    counts = {}
    for row in run['records'].values():
        cat = row['category'] or 'unclassified'
        counts[cat] = counts.get(cat, 0) + 1
    artifact = run.get('artifact')
    public_artifact = {k: v for k, v in artifact.items() if k not in ('local_path', 'report_path')} if artifact else None
    saved = bool(artifact and artifact['revision'] == run['revision'] and
                 Path(artifact['local_path']).is_file())
    return {'run_id': run['run_id'], 'revision': run['revision'], 'scope_count': len(run['records']),
            'counts': counts, 'review_count': sum(v for k, v in counts.items() if k.startswith('_REVIEW_')),
            'reference': __import__(__package__ + '.reference', fromlist=['summary']).summary(run),
            'stage_status': run['stage_status'], 'artifact': public_artifact, 'saved': saved,
            'verified': run['verified_revision'] == run['revision'],
            'visual_review': run.get('visual_review'),
            'stage_checks': run.get('stage_checks', {}), 'raster_job': run.get('raster_job'),
            'progress':{k:v for k,v in run.get('progress_receipt',{}).items() if k!='local_directory'},
            'validation_scope': 'recorded revision; status does not audit live geometry',
            'latest_operation_id': next((op['operation_id'] for op in reversed(run['operations']) if not op['undone']), None)}


def verify(run, payload=None):
    payload = payload or {}
    stage = payload.get('stage')
    if stage is not None:
        if stage not in STAGES or run['stage_status'][stage] != 'reviewed':
            fail('stage_pending', 'Apply the stage before checking it.')
        targets = {key for op in run['operations'] if not op['undone'] and op['stage'] == stage
                   for key in op['before']}
        current = capture(run, audit_ids=targets)
        if digest(current) != run['fingerprint']:
            run['verified_revision'] = None
            run['artifact'] = None
            run['visual_review'] = None
            persist(run)
            fail('scene_changed', 'Checkpoint detected changed metadata or target geometry.')
        run.setdefault('stage_checks', {})[stage] = run['revision']
        persist(run)
        return {'stage': stage, 'stage_verified': True, 'verified': False,
                'revision': run['revision'], 'checked_objects': len(targets),
                'validation_scope': 'stage targets and shared mesh data; not final completeness'}
    pending = [s for s in STAGES if run['stage_status'][s] != 'reviewed']
    if pending:
        fail('stages_pending', 'Final verification is for delivery. Finish stages or request a stage checkpoint.')
    if run.get('reference_profile'):
        from . import reference
        if not reference.summary(run)['semantic_complete']:
            fail('semantic_coverage_incomplete','Resolve invalid assignments and collection coverage before the expensive final geometry audit.')
    current = capture(run, full=True)
    issues = []
    if digest(current) != run['fingerprint']: issues.append('Scene changed outside the recorded operations.')
    obs = objects(run)
    for key, obj in obs.items():
        row = run['records'][key]
        if row['category'] is None: issues.append('Unaccounted object: ' + obj.name)
        elif row['category'] not in current['objects'][key]['collections']:
            issues.append('Recorded category differs from actual membership: ' + obj.name)
    if current['scene_objects'] != run['source_scene_objects']:
        issues.append('Scene object names or object count changed.')
    # No automatic deletion is part of any stage. Recovery dependencies must survive.
    for snap in run['baseline']['objects'].values():
        if snap['type'] == 'MESH' and bpy.data.meshes.get(snap['data']) is None:
            issues.append('An original mesh datablock is missing.')
    run['verified_revision'] = run['revision'] if not issues else None
    persist(run)
    result = summary(run)
    render_ids = render_eligible_ids()
    result.update(verified=not issues, issues=issues[:100], issue_count=len(issues),
                  enabled_meshes=sum(o.type == 'MESH' and o.as_pointer() in render_ids for o in obs.values()),
                  viewport_visible_meshes=sum(o.type == 'MESH' and o.visible_get() for o in obs.values()))
    if issues: result.update(success=False, error={'code': 'verification_failed', 'message': 'Resolve verification issues before saving.'})
    return result


def save(run, payload):
    if run.get('reference_profile'):
        from .reference_delivery import save as save_reference
        return save_reference(run, payload)
    request_sig, old = replay(run, payload, 'save')
    if old:
        if not summary(run)['saved']: fail('artifact_missing', 'Saved artifact is missing or stale; save a new revision.')
        return old
    pending = [s for s in STAGES if run['stage_status'][s] != 'reviewed']
    if pending: fail('stages_pending', 'Review all stages before delivery. Pending: ' + ', '.join(pending))
    if run['verified_revision'] != run['revision']: fail('verification_required', 'Run verify on the current revision.')
    visual = run.get('visual_review')
    if not visual or visual['revision'] != run['revision'] or visual['verdict'] != 'pass':
        fail('visual_review_required', 'Render and review the current result before saving.')
    source = Path(run['source_file']).resolve() if run['source_file'] else None
    directory = source.parent if source else Path(bpy.app.tempdir or os.path.expanduser('~')) / 'Mixar CAD Outputs'
    directory.mkdir(parents=True, exist_ok=True)
    extension = source.suffix if source and source.suffix.lower() in ('.mixar', '.blend') else '.blend'
    name = payload.get('filename') or ((source.stem if source else 'scene') + '_cad_processed_' + token()[:8] + extension)
    if not isinstance(name, str) or Path(name).name != name or any(c in name for c in '/\\:') or name.startswith('.'):
        fail('invalid_filename', 'Supply a filename only, without directories.')
    if Path(name).suffix.lower() not in ('.mixar', '.blend'):
        fail('invalid_filename', 'The processed project must use .mixar or .blend.')
    destination = (directory / name).resolve()
    report_path = destination.with_suffix('.cad-report.json')
    if destination == source or destination.exists() or report_path.exists():
        fail('output_exists', 'The source and existing output files are never overwritten.')
    temporary = directory / ('.cad-' + token() + extension)
    artifact = {'integrity_checked': True, 'artifact_id': token(), 'filename': name, 'report_filename': report_path.name,
                'revision': run['revision'], 'local_path': str(destination), 'report_path': str(report_path)}
    run['artifact'] = artifact
    result = summary(run)
    result.update(status='saved', saved=True, artifact_id=artifact['artifact_id'], filename=name,
                  report_filename=report_path.name, verified=True)
    # Include the receipt in the saved project so a reopened file can replay save.
    run['requests'][payload['request_id']] = {'signature': request_sig, 'result': result}
    persist(run)
    report_created = False
    try:
        report = dict(result)
        report['objects'] = [{'object_id': k, **v} for k, v in run['records'].items()]
        report['operations'] = [{k: op[k] for k in ('operation_id', 'revision', 'stage', 'undone')} for op in run['operations']]
        report['visual_evidence'] = run['visual_review']
        report['stage_notes'] = run.get('stage_notes', {})
        with report_path.open('x', encoding='utf-8') as stream:
            report_created = True
            json.dump(report, stream, indent=2)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            status = bpy.ops.wm.save_as_mainfile(filepath=str(temporary), copy=True, compress=False,
                                                check_existing=False, relative_remap=False)
        if status != {'FINISHED'} or not temporary.is_file() or temporary.stat().st_size == 0:
            fail('save_failed', 'The application did not produce a project file.')
        # Hard-link creation is atomic and refuses an existing destination on all platforms.
        os.link(temporary, destination)
        temporary.unlink()
    except Exception:
        run['artifact'] = None
        run['requests'].pop(payload['request_id'], None)
        persist(run)
        if temporary.exists(): temporary.unlink()
        if report_created and not destination.exists(): report_path.unlink(missing_ok=True)
        raise
    return result
