# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Complete assembly metadata checks with compact, reviewable receipts."""
from collections import Counter
import math
from . import inventory, reference, reference_policy as policy, rules, state

MAX_MEMBERS = 50000
RECEIPT_VERSION = 2


def role(row, path):
    """Conservative component families; synonyms are discovery, not new paths."""
    name = rules.normalize(row['name'])
    has = lambda phrase: rules.has(name, phrase)
    if path == 'EXT/WHEELS/TYRE':
        return 'tyre' if any(has(x) for x in ('TYRE', 'TIRE', 'PNEU')) and not has('WHEEL HOUSE') else None
    if path in ('ALL_VARIANTS/15_IN_ALLOY', 'ALL_VARIANTS/14_IN_STEEL_ALLOY'):
        if any(has(x) for x in ('TYRE', 'TIRE', 'PNEU', 'WHEEL HOUSE', 'WHEEL ARCH', 'WHEEL CAP', 'STEERING')):
            return None
        if (path.endswith('15_IN_ALLOY') and has('14')) or (path.endswith('14_IN_STEEL_ALLOY') and has('15')):
            return None
        return 'wheel assembly' if any(has(x) for x in ('JANTE', 'RIM', 'ALLOY', 'WHEEL')) else None
    if path == 'ALL_VARIANTS/14_IN_WHEEL_CAP':
        return 'wheel cap' if has('WHEEL CAP') else None
    if path == 'EXT/WHEELS/BREAK_DISK':
        return 'brake disc' if any(has(x) for x in ('BRAKE DISC', 'BRAKE DISK', 'BREAK DISK')) else None
    if path == 'EXT/FRONT/FRONT_GRILL':
        return 'front grille' if has('GRILL') and any(has(x) for x in ('FRONT', 'RADIATOR')) else None
    category = rules.classify(row)['category']
    if not category or category.startswith('_REVIEW_') or path in ('EXT/UNDERBODY', 'COLORBODY', 'INT_COLORS', 'SHADER'):
        return None
    if path.startswith(('ALL_VARIANTS/', 'ACCESSORIES/')):
        return None
    # Only explicit component/path correspondence qualifies for large groups.
    pairs = {'EXT/FRONT/FRONT_BUMPER': '_VIZ_BUMPER_',
             'INT/STEERING': '_SYS_STEERING_', 'EXT/DOORS/DOOR_ORVM': '_VIZ_MIRROR_',
             'EXT/ROOF': '_VIZ_ROOF_'}
    prefix = pairs.get(path)
    if path == 'EXT/FRONT/FRONT_BUMPER' and (not has('FRONT') or has('REAR')):
        return None
    return prefix if prefix and category.startswith(prefix) and policy.compatible(category, path) else None


def conflict_reason(row, path):
    category = rules.classify(row)['category']
    if category == '_REVIEW_CONFLICT':
        return 'Conflicting component names need individual review, not assembly approval'
    if not category.startswith('_REVIEW_') and not policy.compatible(category,path):
        return 'Current component category '+category+' conflicts with '+path
    return 'Unsupported assembly family or non-mesh/degenerate member'


def inspect(run, payload):
    path = payload.get('path')
    if path not in policy.leaves(reference.profile()):
        state.fail('invalid_path', 'Use the exact populated reference path; alternatives: ' + ', '.join(policy.alternatives(path, reference.profile())))
    selected = run.get('selections', {}).get(payload.get('selection_id'))
    if not selected or selected['revision'] != run['revision']:
        state.fail('stale_selection', 'Find a current assembly candidate group with inspect_batch.')
    ids = sorted(selected['object_ids'])
    if not ids or len(ids) > MAX_MEMBERS:
        state.fail('assembly_size', 'Use a nonempty assembly of at most 50000 members.')
    rows = inventory.index(run, payload.get('refresh_index', False))
    failures = []
    families = Counter()
    dimensions = []
    for key in ids:
        row = rows[key]
        family = role(row, path)
        inferred = rules.classify(row)['category']
        conflict = inferred == '_REVIEW_CONFLICT' or (not inferred.startswith('_REVIEW_') and not policy.compatible(inferred, path))
        dims = row.get('dimensions', [])
        valid = (row['type'] == 'MESH' and len(dims) == 3 and
                 all(math.isfinite(v) and v >= 0 for v in dims) and max(dims) > 0)
        if not family or not valid or conflict:
            failures.append(key)
        else:
            families[family] += 1
            dimensions.append(dims)
    if len(families) > 1:
        failures = ids
    token = None
    if not failures:
        receipt = {'version': RECEIPT_VERSION, 'revision': run['revision'], 'fingerprint': run['fingerprint'],
                   'path': path, 'members': ids, 'rows_digest': state.digest([rows[k] for k in ids])}
        receipts = run.setdefault('reference_assemblies', {})
        token = next((k for k, v in receipts.items() if v == receipt), None)
        if token is None:
            token = state.token()
            receipts[token] = receipt
        while len(receipts) > 64:
            del receipts[next(iter(receipts))]
    failed = set(failures)
    compatible_ids = [key for key in ids if key not in failed]
    compatible_selection = reference.selection(run, compatible_ids, None, 'assembly_candidates', persist=False) if compatible_ids else None
    exception_selection = reference.selection(run, failures, None, 'assembly_exceptions', persist=False) if failures else None
    state.persist(run)
    from . import wheel_policy
    return {'path': path, 'selection_id': payload['selection_id'], 'assembly_id': token,
            'wheel_requirements': wheel_policy.requirements(run,ids,path),
            'member_count': len(ids), 'checked_count': len(ids), 'families': dict(families),
            'exception_count': len(failures), 'exceptions': [dict(rows[k], conflict_reason=conflict_reason(rows[k],path)) for k in failures[:20]],
            'exception_selection_id': exception_selection,
            'compatible_selection_id': compatible_selection,
            'examples': [rows[k] for k in ids[:6]],
            'dimension_min': [min(d[i] for d in dimensions) for i in range(3)] if dimensions else [],
            'dimension_max': [max(d[i] for d in dimensions) for i in range(3)] if dimensions else [],
            'next': 'Render the complete selection and review assembly identity, completeness and variant before assigning with assembly_id.' if token else 'Inspect compatible_selection_id as a separate assembly and investigate exception_selection_id separately; neither group is automatically assigned or omitted.',
            'limitations': 'Metadata checked for every member; no mesh audit or automatic visual approval. Synonyms do not establish wheel size, variant, or complete wheel faces.'}


def valid(run, ids, decision):
    receipt = run.get('reference_assemblies', {}).get(decision.get('assembly_id'), {})
    if (receipt.get('version') != RECEIPT_VERSION or decision.get('disposition') != 'keep' or receipt.get('path') != decision.get('path') or
            receipt.get('revision') != run['revision'] or receipt.get('fingerprint') != run['fingerprint'] or
            receipt.get('members') != sorted(ids)):
        return False
    rows = inventory.index(run)
    return receipt.get('rows_digest') == state.digest([rows[k] for k in sorted(ids)])
