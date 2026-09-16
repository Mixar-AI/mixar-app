# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Semantic assignment constraints. Preservation alone is never classification."""
from collections import Counter
from difflib import get_close_matches

VERSION = 2
MAX_GROUP = 200


def leaves(profile):
    # Some populated paths also have children; actual reference membership wins.
    return {r['path'] for r in profile['collections'] if r['mesh_count'] > 0}


def alternatives(path, profile):
    valid = sorted(leaves(profile))
    matches = get_close_matches(path or '', valid, n=8, cutoff=.2)
    if 'SEAT' in (path or ''):
        matches = [p for p in valid if p.startswith('INT/') and 'SEAT' in p]
    return matches


def compatible(category, path):
    category = category or ''
    if path == 'EXT/UNDERBODY':
        return category.startswith(('_SYS_ENGINE_', '_SYS_COOLING_', '_SYS_SUSPENSION_',
            '_SYS_EXHAUST_', '_SYS_FUEL_', '_SYS_BRAKES_', '_SYS_BODY_STRUCT_', '_REVIEW_'))
    if category.startswith('_SYS_SEATS_'):
        return ('SEAT' in path or path.startswith('ACCESSORIES/NECK') or
                path == 'ALL_VARIANTS/NECK_LAMBAR_PASSENGER_SIDE')
    if category.startswith('_VIZ_LAMPS_'):
        return any(word in path for word in ('LAMP', 'LIGHT', 'FOG'))
    if category.startswith('_VIZ_ROOF_'):
        return 'ROOF' in path or path == 'COLORBODY'
    if category.startswith('_VIZ_BUMPER_'):
        return any(word in path for word in ('BUMPER', 'FRONT_COMMON', 'PARKING_SENSOR'))
    if category.startswith('_VIZ_RADIATOR_GRILL_'):
        return path in ('EXT/FRONT/FRONT_GRILL','EXT/FRONT/FRONT_COMMON')
    return True


def problems(run, ids, decision, profile):
    """Return bounded actionable issues without mutating state."""
    disposition = decision.get('disposition')
    if disposition == 'review': return []
    issues = []
    path = decision.get('path')
    if disposition == 'keep' and path not in leaves(profile):
        issues.append('Keep requires an assignable reference path. Alternatives: ' +
                      ', '.join(alternatives(path, profile)))
    from . import assemblies
    assembly = assemblies.valid(run, ids, decision) if decision.get('assembly_id') else False
    if decision.get('assembly_id') and not assembly:
        issues.append('Assembly receipt is stale, mismatched, or missing; inspect this exact assembly and path again.')
    if len(ids) > MAX_GROUP and not assembly:
        issues.append('Use inspect_assembly for a complete supported assembly; otherwise resolve at most 200 explicitly inspected objects per group.')
    from .rules import classify
    inferred=[classify(run['records'][k])['category'] for k in ids]
    # Current specific evidence supersedes stale diagnostic categories.
    cats = Counter(c if not c.startswith('_REVIEW_') else run['records'][k].get('category')
                   for k,c in zip(ids,inferred))
    if len(cats) > 1 and not assembly:
        issues.append('Mixed diagnostic categories need separate semantic groups.')
    if disposition == 'keep' and not assembly and any(not compatible(c, path or '') for c in cats):
        issues.append('Component category conflicts with the target path; inspect and correct component identity first.')
    if disposition == 'keep' and any(not c.startswith('_REVIEW_') and not compatible(c,path or '') for c in inferred):
        issues.append('Current component-name evidence conflicts with this target; old diagnostic labels do not override it.')
    inspected = run.get('reference_inspected', {})
    if not assembly and any(inspected.get(k) != run['revision'] for k in ids):
        issues.append('Inspect every candidate in this bounded group; a page sample does not review the whole selection.')
    evidence_ids = decision.get('evidence_ids') or []
    images = [run.get('evidence', {}).get(k, {}) for k in evidence_ids]
    images = [e for e in images if e.get('revision') == run['revision'] and
              e.get('fingerprint') == run['fingerprint'] and e.get('camera')]
    covered = set().union(*(set(e.get('render_ids', [])) for e in images)) if images else set()
    ambiguous = any(not c or c.startswith('_REVIEW_') for c in cats)
    if disposition == 'keep' and (assembly or ambiguous or path.startswith(('ALL_VARIANTS/', 'ACCESSORIES/'))):
        if not set(ids) <= covered:
            issues.append('Ambiguous components and variants/accessories require current scoped image evidence covering every candidate.')
    if disposition == 'keep':
        from . import wheel_policy
        issues.extend(wheel_policy.problems(run, ids, decision))
    if disposition == 'omit':
        if decision.get('evidence_kind') not in ('semantic_review', 'exact_duplicate'):
            issues.append('Omission requires semantic review or exact duplicate proof, never invisibility.')
        if decision.get('evidence_kind') == 'exact_duplicate':
            if any(c != '_DUP_COINCIDENT' for c in cats):
                issues.append('Exact duplicate omission requires the pipeline duplicate proof category.')
        elif not set(ids) <= covered:
            issues.append('Semantic omission requires current scoped image evidence plus inspected identities.')
    return issues


def accepted(run, row):
    from . import wheel_policy
    return (row.get('policy_version') == VERSION and row.get('scene_revision') == run['revision']
            and wheel_policy.accepted(run, row))
