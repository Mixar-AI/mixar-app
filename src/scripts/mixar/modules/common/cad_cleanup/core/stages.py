# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Read-only stage analysis and agent-authored bounded proposals."""
import math

from ..constants import CATEGORIES, MAX_DECISIONS, MAX_PAGE, STAGES
from . import rules
from .state import fail, objects, persist, record, token, validate_number, relations, render_eligible_ids


def decision_groups(decisions):
    """Bounded representative evidence; full decisions remain pageable locally."""
    groups = {}
    for item in decisions:
        category = item['category']
        group = groups.setdefault(category, {'category': category, 'count': 0, 'examples': []})
        group['count'] += 1
        if len(group['examples']) < 3: group['examples'].append(item)
    return list(groups.values())


def proposal(run, stage, decisions, rationale):
    if stage not in STAGES: fail('invalid_stage', 'Unknown cleanup stage.')
    ids = set()
    for item in decisions:
        key = item['object_id']
        if key not in run['records'] or key in ids:
            fail('invalid_target', 'Each decision must reference one unique scoped object.')
        ids.add(key)
        if item['category'] not in CATEGORIES: fail('invalid_category', 'Category is outside the cleanup taxonomy.')
        if not isinstance(item.get('reason'), str) or not item['reason'].strip():
            fail('missing_reason', 'Every decision requires a reason.')
        if item.get('unit_factor') is not None:
            factor = validate_number(item['unit_factor'], 'unit_factor')
            if stage != '2' or not 1e-6 <= factor <= 1000:
                fail('invalid_units', 'Unit factors must be explicit stage-2 proposals in [1e-6, 1000].')
        if item.get('bake_scale') and stage != '4':
            fail('invalid_scale', 'Scale baking belongs to stage 4.')
        if item.get('presentation_hidden') is not None:
            if (stage != '10' or type(item['presentation_hidden']) is not bool
                    or not item['category'].startswith(('_SYS_', '_VIZ_'))):
                fail('invalid_visibility', 'Stage-10 presentation visibility applies only to identified parts.')
    key = token()
    run['proposals'][key] = {'stage': stage, 'revision': run['revision'], 'fingerprint': run['fingerprint'],
                             'decisions': decisions, 'rationale': rationale, 'applied': False}
    # Keep at most 24 unapplied previews; applied data live in the operation journal.
    for old in list(run['proposals'])[:-24]: del run['proposals'][old]
    persist(run)
    return {'proposal_id': key, 'stage': stage, 'revision': run['revision'],
            'total': len(decisions), 'groups': decision_groups(decisions),
            'decisions': decisions[:MAX_PAGE], 'live_geometry_checked': False,
            'next_cursor': MAX_PAGE if len(decisions) > MAX_PAGE else None, 'rationale': rationale}


def analyze(run, stage):
    if stage not in STAGES: fail('invalid_stage', 'Unknown cleanup stage.')
    obs = objects(run)
    indexes = relations()
    render_ids = render_eligible_ids() if stage == '3' else set()
    rows = {key: record(obj, key, run, indexes) for key, obj in obs.items()}
    results = []
    seen = {}
    notes = []
    for key, row in rows.items():
        obj = obs[key]; current = row['category']; item = None
        untouched = current is None
        if stage == '1' and untouched:
            if obj.type == 'EMPTY':
                item = rules.decision('_TRIAGE_NONGEOMETRY', 'Assembly transform retained as a dependency')
            elif obj.type != 'MESH' or not obj.data.polygons:
                item = rules.decision('_REVIEW_UNSUPPORTED', 'Non-mesh or generated geometry requires inspection', confidence='low')
            elif row['geometry_supported'] is False:
                notes.append({'object_id': key, 'reason': 'Geometry edits disabled for dependency-bearing object'})
        elif stage == '2' and obj.type == 'MESH':
            # Distance from origin is NOT a unit detector. Only report outliers.
            largest = max(row['dimensions'])
            if largest > 30 or (largest > 0 and largest < .00001):
                notes.append({'object_id': key, 'reason': 'Scale outlier: inspect units before proposing a factor'})
        elif stage == '3' and obj.type == 'MESH' and row['geometry_supported']:
            # Shared datablock identity is stronger than any lossy geometry hash.
            # Distinct datablocks are deliberately not merged or purged.
            sig = (obj.data.as_pointer(), obj.visible_get(), obj.as_pointer() in render_ids,
                   tuple(v for r in obj.matrix_world for v in r),
                   tuple(s.material.as_pointer() if s.material else 0 for s in obj.material_slots))
            if sig in seen and current != '_DUP_COINCIDENT':
                item = rules.decision('_DUP_COINCIDENT', 'Same mesh datablock, materials and exact world transform', [seen[sig]])
            else: seen[sig] = key
        elif stage == '4' and obj.type == 'MESH' and row['geometry_supported']:
            if any(abs(float(v) - 1) > 1e-6 for v in obj.scale):
                if min(obj.scale) > 0:
                    item = rules.decision(current or '_REVIEW_UNCLASSIFIED', 'Bake supported positive object scale on a copied mesh')
                    item['bake_scale'] = True
                else: notes.append({'object_id': key, 'reason': 'Negative/zero scale preserved; explicit review required'})
        elif stage in ('5', '5b') and (untouched or current == '_REVIEW_UNCLASSIFIED'):
            # Construction names are evidence only; never override meaningful protected parts.
            if not row['protected']:
                item = rules.cull_evidence(row, secondary=stage == '5b')
        elif stage == '6' and (untouched or current == '_REVIEW_UNCLASSIFIED'):
            parsed = rules.parse_name(row['name'])
            if not parsed['protected'] and (not parsed['descriptor'] or parsed['descriptor'] in ('NULL', 'NO VALUE')):
                item = rules.decision('_REVIEW_ANONYMOUS', 'Missing description is not proof of disposable geometry', confidence='low')
        elif stage in ('7', '8') and obj.type == 'MESH' and (untouched or current == '_REVIEW_UNCLASSIFIED'):
            suggested = rules.classify(row)
            if stage == '8' or suggested['category'].startswith('_VIZ_'): item = suggested
        elif stage == '8b' and obj.type == 'MESH' and max(row['dimensions']) < .05:
            notes.append({'object_id': key, 'reason': 'Small part preserved; size cannot establish hardware or visibility'})
        elif stage == '9' and untouched:
            item = rules.decision('_REVIEW_UNCLASSIFIED', 'Every scoped object must have an outcome', confidence='low')
        if item:
            item['object_id'] = key
            results.append(item)
    output = proposal(run, stage, results, 'Stage ' + stage + ' evidence-based preview; review exceptions before applying.')
    run['proposals'][output['proposal_id']]['notes'] = notes
    persist(run)
    output.update(notes=notes[:MAX_PAGE], note_count=len(notes),
                  policy='Visibility is preserved; only explicitly confirmed culls/coincident copies are excluded.')
    return output


def propose(run, payload):
    decisions = payload.get('decisions')
    if not isinstance(decisions, list) or len(decisions) > MAX_DECISIONS:
        fail('invalid_decisions', 'Supply at most 1000 explicit decisions per proposal.')
    return proposal(run, str(payload.get('stage')), decisions, payload.get('rationale', 'Agent-reviewed proposal'))
