# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Reference taxonomy and explicit delivery dispositions; never delete source IDs."""
import json
from pathlib import Path

from . import state, reference_policy as policy
from .mutations import replay, remember


def profile():
    return json.loads((Path(__file__).parents[1] / 'reference_profile.json').read_text(encoding='utf-8'))


def summary(run):
    assigned = run.get('reference_assignments', {})
    counts = {}
    for row in assigned.values():
        key = row.get('path') or row['disposition']
        counts[key] = counts.get(key, 0) + 1
    required = {k for k, r in run['baseline']['objects'].items() if r['type'] in ('MESH', 'CURVE', 'SURFACE', 'FONT', 'META')}
    invalid = sum(not policy.accepted(run, r) for r in assigned.values() if r['disposition'] != 'review')
    coverage = coverage_rows(run)
    unresolved = [r['path'] for r in coverage if r['status'] not in ('verified', 'confirmed_absent')]
    return {'profile_id': run.get('reference_profile'), 'counts': counts,
            'pending': len(required - assigned.keys()),
            'review': sum(r['disposition'] == 'review' for r in assigned.values()),
            'assignment_revision': run.get('assignment_revision', 0),
            'policy_version': policy.VERSION, 'invalid_assignments': invalid,
            'coverage_unresolved': len(unresolved), 'next_paths': unresolved[:12],
            'semantic_complete': not invalid and not unresolved and not (required-assigned.keys()) and
                not any(r['disposition'] == 'review' for r in assigned.values())}


def catalog(run, payload):
    data = profile()
    data['collections'] = [{**r, 'assignable': r['path'] in policy.leaves(data)} for r in data['collections']]
    prefix = payload.get('prefix')
    if prefix: data['collections'] = [r for r in data['collections'] if r['path'] == prefix or r['path'].startswith(prefix+'/')]
    return {**data, 'assignment_status': summary(run),
            'policy': 'Exact reference spelling and hierarchy are mandatory, including BREAK_DISK. No invented synonym collections. Inspect whole supported assemblies with inspect_assembly; otherwise bounded candidates. Counts are not quotas.',
            'coverage': [r for r in coverage_rows(run) if not prefix or r['path'] == prefix or r['path'].startswith(prefix+'/')]}


def assign(run, payload):
    signature, old = replay(run, payload, 'reference_assign')
    if old: return {**old,**summary(run),'replayed':True}
    rows = payload.get('decisions')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        state.fail('invalid_decisions', 'Supply 1..100 bounded disposition groups.')
    data = profile()
    allowed = policy.leaves(data)
    pending = {}
    for row in rows:
        ids = row.get('object_ids')
        selection_id = row.get('selection_id')
        if selection_id:
            if ids: state.fail('invalid_target', 'Use IDs or a selection, not both.')
            evidence = run.get('selections', {}).get(selection_id)
            if not evidence or evidence['revision'] != run['revision']:
                state.fail('stale_selection', 'Recapture selection for the current scene revision.')
            ids = evidence['object_ids']
        if not isinstance(ids, list) or not ids or any(k not in run['records'] for k in ids):
            state.fail('invalid_target', 'Explicit scoped IDs or a current selection are required.')
        disposition = row.get('disposition')
        path = row.get('path')
        reason = row.get('reason')
        if disposition not in ('keep', 'omit', 'review') or not isinstance(reason, str) or not reason.strip():
            state.fail('invalid_decision', 'Each group needs keep/omit/review and evidence reasoning.')
        if (disposition == 'keep' and path not in allowed) or (disposition != 'keep' and path):
            state.fail('invalid_path', 'Use an assignable leaf; omit/review have no path. Alternatives: '+', '.join(policy.alternatives(path, data)))
        # Raster/ray evidence proves visible candidates, never semantic irrelevance.
        if disposition == 'omit' and row.get('evidence_kind') not in ('semantic_review', 'exact_duplicate'):
            state.fail('removal_evidence_required', 'Omission needs semantic review or a proved exact duplicate.')
        issues = policy.problems(run, ids, row, data)
        if issues:
            from .rules import classify
            conflicts=[k for k in ids if not classify(run['records'][k])['category'].startswith('_REVIEW_')
                       and not policy.compatible(classify(run['records'][k])['category'],path or '')]
            details={'conflict_count':len(conflicts),'conflicts':[
                {'object_id':k,'name':run['records'][k]['name'],
                 'category':classify(run['records'][k])['category']} for k in conflicts[:20]]}
            if conflicts:
                failed=set(conflicts)
                details['conflict_selection_id']=selection(run,conflicts,None,'assignment_conflicts',persist=False)
                compatible=[k for k in ids if k not in failed]
                details['compatible_selection_id']=selection(run,compatible,None,'assignment_candidates',persist=False) if compatible else None
                state.persist(run)
            state.fail('semantic_review_required',' '.join(issues),
                       {'issues':issues,**details,'next':'Do not retry unchanged. Inspect the returned partitions, change evidence or leave unresolved.'})
        for key in ids:
            if key in pending: state.fail('duplicate_decision', 'An object occurs in multiple disposition groups.')
            pending[key] = {'disposition': disposition, 'path': path, 'reason': reason[:2000],
                            'evidence_kind': row.get('evidence_kind'), 'scene_revision': run['revision'],
                            'evidence_ids': row.get('evidence_ids') or [], 'policy_version': policy.VERSION,
                            'assembly_id': row.get('assembly_id'), 'wheel_review_id': row.get('wheel_review_id')}
    if sum(r['disposition'] != 'review' and not r.get('assembly_id') for r in pending.values()) > 1000:
        state.fail('batch_too_large', 'Resolve at most 1000 objects per call in homogeneous groups.')
    if len(pending) > 50000:
        state.fail('batch_too_large', 'Use at most 50000 assembly members per call.')
    run.setdefault('reference_assignments', {}).update(pending)
    run['reference_profile'] = profile()['profile_id']
    run['assignment_revision'] = run.get('assignment_revision', 0) + 1
    run['artifact'] = None
    run['reference_review'] = None
    return remember(run, payload, signature, {'assigned': len(pending), **summary(run)})


def selection(run, ids, evidence_id, kind, persist=True):
    ids = sorted(set(ids))
    for key, old in run.get('selections', {}).items():
        if old['revision'] == run['revision'] and old.get('kind') == kind and old.get('evidence_id') == evidence_id and old['object_ids'] == ids:
            return key
    key = state.token()
    run.setdefault('selections', {})[key] = {'object_ids': ids,
        'revision': run['revision'], 'evidence_id': evidence_id, 'kind': kind}
    # Bound persisted selection growth, without silently evicting a pending operation.
    while len(run['selections']) > 256:
        del run['selections'][next(iter(run['selections']))]
    if persist: state.persist(run)
    return key


def coverage_rows(run):
    assignments = run.get('reference_assignments', {})
    by_path = {}
    for key, row in assignments.items():
        if row['disposition'] == 'keep': by_path.setdefault(row['path'], []).append(key)
    rows = []
    for path in sorted(policy.leaves(profile())):
        keys = by_path.get(path, [])
        receipt = run.get('reference_coverage', {}).get(path, {})
        current = (receipt.get('revision') == run['revision'] and receipt.get('members') == sorted(keys)
                   and all(policy.accepted(run, assignments[k]) for k in keys))
        status = receipt.get('status') if current else ('partial' if keys else 'unresolved')
        rows.append({'path': path, 'assigned': len(keys), 'status': status,
                     'notes': receipt.get('notes', '') if current else ''})
    return rows


def review_coverage(run, payload):
    rows = payload.get('reviews')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 30:
        state.fail('invalid_reviews', 'Review 1..30 collection paths per major batch.')
    pending = {}
    for row in rows:
        path = row.get('path'); status = row.get('status'); notes = row.get('notes')
        if path not in policy.leaves(profile()) or status not in ('verified','partial','unresolved','confirmed_absent') or not isinstance(notes,str) or len(notes.strip()) < 20:
            state.fail('invalid_review', 'Use an assignable path, coverage status and specific observations (20+ characters).')
        keys = sorted(k for k,r in run.get('reference_assignments',{}).items() if r.get('path') == path and r['disposition']=='keep')
        images = [run['evidence'].get(k,{}) for k in row.get('evidence_ids',[])]
        images = [r for r in images if r.get('revision')==run['revision'] and r.get('fingerprint')==run['fingerprint'] and r.get('camera')]
        covered = set().union(*(set(r.get('render_ids',[])) for r in images)) if images else set()
        if status == 'verified' and (not keys or not set(keys)<=covered or any(not policy.accepted(run,run['reference_assignments'][k]) for k in keys)):
            state.fail('coverage_evidence_required', 'Verified coverage needs valid assignments and current images covering the complete collection.')
        if status == 'confirmed_absent':
            searches = [run.get('reference_searches',{}).get(k,{}) for k in row.get('search_ids',[])]
            searches = [s for s in searches if s.get('revision')==run['revision'] and s.get('full_scope') and s.get('query') and s.get('total')==0]
            if keys or not images or len({s['query'] for s in searches})<2:
                state.fail('absence_evidence_required', 'Absence needs no assigned objects, two distinct current whole-inventory zero-result searches, and image/context evidence. Occlusion alone is insufficient.')
        pending[path] = {'status':status,'notes':notes[:2000],'revision':run['revision'],'members':keys,
                         'evidence_ids':row.get('evidence_ids',[]),'search_ids':row.get('search_ids',[])}
    run.setdefault('reference_coverage',{}).update(pending)
    run['artifact']=None
    state.persist(run)
    return {'reviewed_paths':len(pending),**summary(run)}
