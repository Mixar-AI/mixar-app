# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Build a separate reference-organized scene; omitted source geometry stays in recovery."""
import json
import os
from pathlib import Path
import bpy

from . import state, reference, organized
from .mutations import replay, remember


def validate(run):
    status = reference.summary(run)
    if status['pending'] or status['review']:
        state.fail('reference_incomplete', 'Resolve all required-object dispositions before final reference delivery.')
    if not status['semantic_complete']:
        state.fail('semantic_coverage_incomplete', 'Re-review legacy/stale assignments and resolve every reference collection with visual coverage or evidence-backed absence.')
    if run['verified_revision'] != run['revision']:
        state.fail('verification_required', 'Verify the completed stages before saving.')
    review = run.get('reference_review') or {}
    if (review.get('revision') != run['revision'] or review.get('verdict') != 'pass'
            or review.get('assignment_revision') != run.get('assignment_revision')):
        state.fail('reference_review_required', 'Render delivery=true and review the current kept result.')
    reviewed = [r for r in run.get('reference_reviews', {}).values()
                if r.get('revision') == run['revision']
                and r.get('assignment_revision') == run.get('assignment_revision')
                and r.get('verdict') == 'pass']
    if len(reviewed) < 2:
        state.fail('reference_review_required', 'Review the retained result from at least two different directions.')
    assigned = run['reference_assignments']
    chosen = {k: o for k, o in state.objects(run).items() if assigned.get(k, {}).get('disposition') in ('keep', 'hidden_internal')}
    if not chosen: state.fail('empty_delivery', 'No retained objects are assigned.')
    # Flatten only demonstrably static evaluated transforms. Animated assemblies
    # and modifier dependency graphs require their own preservation exporter.
    organized.require_static(chosen.values())
    return chosen


def save(run, payload):
    signature, old = replay(run, payload, 'reference_save')
    if old:
        artifact = run.get('artifact') or {}
        if not Path(artifact.get('local_path', '')).is_file():
            state.fail('artifact_missing', 'Save a new artifact; previous file is missing.')
        return old
    chosen = validate(run)
    source = Path(run['source_file']) if run.get('source_file') else None
    if source is None: state.fail('source_required', 'Save the source project before reference delivery.')
    name = payload.get('filename') or source.stem + '_reference_' + state.token()[:8] + '.mixar'
    if (not isinstance(name, str) or any(c in name for c in '/\\:') or name.startswith('.')
            or Path(name).suffix.lower() not in ('.mixar', '.blend')):
        state.fail('invalid_filename', 'Use a project basename only.')
    output = source.parent / name
    report = output.with_suffix('.cad-report.json')
    if output.exists() or report.exists(): state.fail('output_exists', 'Existing files are never overwritten.')
    temporary = output.with_name('.cad-reference-' + state.token() + output.suffix)
    organized.sync(run, force=True)
    scene = organized.scene_for(run)
    wrote_report = False
    try:
        if len(scene.objects) != len(chosen): state.fail('delivery_mismatch', 'Generated object accounting failed.')
        artifact = {'artifact_id': state.token(), 'filename': output.name, 'report_filename': report.name,
                    'revision': run['revision'], 'assignment_revision': run['assignment_revision'],
                    'integrity_checked': True, 'local_path': str(output), 'report_path': str(report),
                    'profile_id': run['reference_profile'], 'retained_objects': len(chosen),
                    'hidden_internal_objects': sum(r['disposition'] == 'hidden_internal' for r in run['reference_assignments'].values())}
        artifact['semantic_policy_version']=reference.summary(run)['policy_version']
        artifact['semantic_complete']=True
        report_data = {'artifact': {k: v for k, v in artifact.items() if k not in ('local_path', 'report_path')},
                       'assignments': run['reference_assignments'], 'visual_review': run['reference_review'],
                       'limitations': ['Source preserved separately; static transforms flattened; meshes not joined.',
                                       'Reference counts are not mesh-count quotas; variants may overlap.']}
        scene['cad_reference_delivery'] = json.dumps(report_data)
        # Write only the generated scene and its data dependencies, not the full
        # source/recovery scene. No source object or shared mesh is deleted.
        bpy.data.libraries.write(str(temporary), {scene}, path_remap='ABSOLUTE', fake_user=True, compress=True)
        if not temporary.is_file() or not temporary.stat().st_size: state.fail('save_failed', 'No output project written.')
        with report.open('x', encoding='utf-8') as stream:
            wrote_report = True
            json.dump(report_data, stream, indent=2)
        os.link(temporary, output)
        run['artifact'] = artifact
        return remember(run, payload, signature, {'saved': True, 'verified': True,
                        'filename': output.name, 'report_filename': report.name, 'artifact_id': artifact['artifact_id']})
    except Exception:
        if wrote_report and not output.exists(): report.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)
