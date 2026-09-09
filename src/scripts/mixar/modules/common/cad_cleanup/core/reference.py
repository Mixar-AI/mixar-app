# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Local decision receipt storage. Taxonomy and semantic approval come from backend."""
from . import state, assignment_receipts as policy

def profile(run):
    value=run.get('workflow',{}).get('reference')
    if not value: state.fail('cad_transport_mismatch','Resume through the updated backend for its reference contract.')
    return value

def summary(run):
    if policy.current(run): return run['backend_summary']['summary']
    assigned=run.get('reference_assignments',{})
    counts={}
    for row in assigned.values():
        key=row.get('path') or row['disposition']; counts[key]=counts.get(key,0)+1
    required={k for k,r in run['baseline']['objects'].items() if r['type'] in ('MESH','CURVE','SURFACE','FONT','META')}
    return {'profile_id':run.get('reference_profile'),'counts':counts,'pending':len(required-assigned.keys()),
        'review':sum(r['disposition']=='review' for r in assigned.values()),
        'assignment_revision':run.get('assignment_revision',0),'policy_version':None,
        'invalid_assignments':sum(r['disposition']!='review' for r in assigned.values()),
        'coverage_unresolved':len(policy.leaves(profile(run))) if run.get('workflow') else 0,
        'next_paths':[],'semantic_complete':False,'reference_summary_required':True}

def coverage_rows(run):
    return run.get('backend_summary',{}).get('coverage',[]) if policy.current(run) else []

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
