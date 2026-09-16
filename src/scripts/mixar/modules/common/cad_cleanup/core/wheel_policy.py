# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Independent wheel completeness review plus immutable source variant evidence."""
import re
from . import state, rules, grounding

PATHS = {'ALL_VARIANTS/15_IN_ALLOY': (15, 'alloy'),
         'ALL_VARIANTS/14_IN_STEEL_ALLOY': (14, 'steel'),
         'ALL_VARIANTS/14_IN_WHEEL_CAP': (14, 'wheel_cap')}
VERSION = 1


def source_matches(run, key, path):
    """Never read current destination/assignment, diameter or agent rationale."""
    original = run['baseline']['objects'].get(key, {})
    expected_size, kind = PATHS[path]
    # A source parent assembly label can identify a named fragment's variant.
    # Preserve token boundaries: part number 15123 and J15 are not inch evidence.
    texts = [rules.parse_name(original.get(field) or '')['descriptor'] for field in ('name', 'parent')]
    text = ' '.join(texts)
    sizes = {int(m) for m in re.findall(r'\b(1[0-9]|2[0-9])\s*(?:INCH(?:ES)?|IN)\b', text)}
    if sizes != {expected_size}:
        return False
    has = lambda word: rules.has(text, word)
    if any(has(w) for w in ('TYRE', 'TIRE', 'PNEU', 'STEERING', 'WHEEL HOUSE', 'WHEELHOUSE')):
        return False
    if kind == 'alloy':
        return has('ALLOY') and not has('STEEL') and not has('WHEEL CAP')
    if kind == 'steel':
        return has('STEEL') and not has('WHEEL CAP')
    return has('WHEEL CAP')


def scope(run, payload):
    path = payload.get('path')
    selected = run.get('selections', {}).get(payload.get('selection_id'), {})
    ids = sorted(selected.get('object_ids', []))
    if path not in PATHS or selected.get('revision') != run['revision'] or not 1 <= len(ids) <= 2048:
        state.fail('invalid_wheel_scope', 'Use an exact wheel variant path and a current selection of 1..2048 members.')
    missing = [key for key in ids if not source_matches(run, key, path)]
    if missing:
        state.fail('wheel_variant_evidence_required',
                   'Original object/parent descriptors must explicitly identify inch size and construction for every member. '
                   'Generic Jante/rim names, outer diameter and previous assignments are not proof. '
                   'Leave unresolved. Missing source evidence IDs: '+', '.join(missing[:20]))
    key, evidence = grounding.evidence(run, payload)
    if not evidence.get('camera') or set(evidence.get('render_ids', [])) != set(ids):
        state.fail('wheel_image_scope', 'Use an image of exactly this complete candidate selection, not a broad covering image.')
    return path, ids, key, evidence


def signature(run, path, ids, key):
    return state.digest({'revision':run['revision'],'fingerprint':run['fingerprint'],
        'path':path,'ids':ids,'evidence_id':key,
        'sources':[run['baseline']['objects'][k] for k in ids]})


def image(run, payload):
    path, ids, key, evidence = scope(run, payload)
    stamp = signature(run,path,ids,key)
    for token, receipt in run.get('wheel_reviews', {}).items():
        if receipt.get('signature') == stamp:
            return {'wheel_review_cached':True,'wheel_review_id':token,
                    'accepted':receipt['accepted'],'assessment':receipt['assessment']}
    return {**grounding.image(run,{'evidence_id':key}), 'wheel_review_cached':False,
            'expected_kind':PATHS[path][1]}


def store_review(run, payload):
    path, ids, key, evidence = scope(run, payload)
    assessment = payload.get('assessment')
    if (not isinstance(assessment,dict) or type(assessment.get('complete')) is not bool
            or assessment.get('kind') not in ('alloy','steel','wheel_cap','incomplete','uncertain')
            or not isinstance(assessment.get('notes'),str) or not 20 <= len(assessment['notes']) <= 2000):
        state.fail('invalid_wheel_review','Independent visual review must return complete, kind and specific observations.')
    passed = assessment['complete'] and assessment['kind'] == PATHS[path][1]
    receipt = {'version':VERSION,'signature':signature(run,path,ids,key),
               'revision':run['revision'],'fingerprint':run['fingerprint'],
               'path':path,'members':ids,'evidence_id':key,'accepted':passed,'assessment':assessment}
    cache = run.setdefault('wheel_reviews',{})
    token = next((k for k,v in cache.items() if v.get('signature') == receipt['signature']),None)
    if token is None:
        if len(cache) >= 64:
            state.fail('wheel_review_limit','Wheel review cache is full; preserve checkpoint and resolve existing evidence before more reviews.')
        token = state.token()
        cache[token] = receipt
    # An identical image cannot gain a pass by repeatedly asking the reviewer.
    stored = cache[token]
    state.persist(run)
    return {'wheel_review_id':token,'accepted':stored['accepted'],'assessment':stored['assessment']}


def valid(run, decision, ids=None):
    path = decision.get('path')
    receipt = run.get('wheel_reviews',{}).get(decision.get('wheel_review_id'),{})
    members = receipt.get('members',[])
    evidence = run.get('evidence',{}).get(receipt.get('evidence_id'),{})
    return bool(receipt.get('version') == VERSION and receipt.get('accepted') is True
        and receipt.get('path') == path and receipt.get('revision') == run['revision']
        and receipt.get('fingerprint') == run['fingerprint'] and members
        and receipt.get('evidence_id') in decision.get('evidence_ids',[])
        and evidence.get('revision') == run['revision'] and evidence.get('fingerprint') == run['fingerprint']
        and evidence.get('camera') and set(evidence.get('render_ids',[])) == set(members)
        and (ids is None or sorted(ids) == members)
        and receipt.get('signature') == signature(run,path,members,receipt.get('evidence_id')))


def problems(run, ids, decision):
    if decision.get('path') in PATHS and not valid(run,decision,ids):
        return ['Wheel variant keep requires cad_review_wheel: explicit original size/construction plus an independent complete-wheel image review. Previous assignments and self-written reasons are not evidence.']
    return []


def accepted(run, row):
    return row.get('disposition') != 'keep' or row.get('path') not in PATHS or valid(run,row)


def requirements(run, ids, path):
    if path not in PATHS:
        return None
    missing=[k for k in ids if not source_matches(run,k,path)]
    return {'independent_review_required':True,'missing_source_count':len(missing),
            'missing_source_ids':missing[:20],
            'next':'Leave variant unresolved; original inch-size/construction evidence is missing.' if missing else
                   'Render the exact selection and call cad_review_wheel once. Reuse its cached receipt.'}
