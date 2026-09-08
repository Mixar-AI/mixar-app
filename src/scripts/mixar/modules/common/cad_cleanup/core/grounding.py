# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Map bounded image regions to mesh candidates in the exact recorded view."""
from collections import Counter
import math
import bpy
from mathutils import Matrix, Vector

from . import state, reference
from .visual import cached_path, image_result


def evidence(run, payload):
    key = payload.get('evidence_id')
    metadata = run['evidence'].get(key)
    if (not metadata or metadata['revision'] != run['revision']
            or metadata.get('fingerprint') != run['fingerprint']):
        state.fail('stale_evidence', 'Use an image from the current scene revision.')
    return key, metadata


def image(run, payload):
    key, metadata = evidence(run, payload)
    target=(payload.get('target') or '').strip().casefold()
    cached=metadata.get('localizations',{}).get(target)
    if target and cached is not None:
        return {'evidence_id':key,'target':payload['target'],'localization_cached':True,**cached}
    path = cached_path(metadata)
    if path is None or not path.is_file(): state.fail('image_expired', 'Render this view again.')
    return image_result(key, metadata, path.read_bytes(), True)


def store_localization(run,payload):
    key,metadata=evidence(run,payload)
    target=payload.get('target')
    result=payload.get('localization')
    if not isinstance(target,str) or not 1<=len(target.strip())<=500 or not isinstance(result,dict):
        state.fail('invalid_localization','Use a bounded target and localization result.')
    boxes=result.get('boxes')
    if boxes!=[]: points_for_regions(boxes)
    stored={'boxes':boxes,'notes':str(result.get('notes',''))[:2000]}
    cache=metadata.setdefault('localizations',{})
    cache[target.strip().casefold()]=stored
    while len(cache)>16: del cache[next(iter(cache))]
    state.persist(run)
    return {'evidence_id':key,'target':target,**stored}


def points_for_regions(regions):
    if not isinstance(regions, list) or not 1 <= len(regions) <= 8:
        state.fail('invalid_regions', 'Use 1..8 normalized boxes [ymin,xmin,ymax,xmax].')
    points = []
    for box in regions:
        if (not isinstance(box, list) or len(box) != 4 or
                any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1000 for v in box)):
            state.fail('invalid_regions', 'Coordinates must be finite numbers in 0..1000.')
        y0, x0, y1, x1 = box
        if x1 <= x0 or y1 <= y0: state.fail('invalid_regions', 'Boxes need positive area.')
        # At most 512 stratified rays. Keep all observed IDs; hit share is not
        # object completeness, confidence, or a semantic membership threshold.
        for y in range(8):
            for x in range(8):
                points.append(((x0 + (x+.5)*(x1-x0)/8)/1000,
                               (y0 + (y+.5)*(y1-y0)/8)/1000))
    return points


def ray_select(run, payload):
    key, metadata = evidence(run, payload)
    points = points_for_regions(payload.get('boxes'))
    frame = metadata.get('camera')
    if not frame: state.fail('camera_unavailable', 'Capture a new image with recorded camera geometry.')
    cache_key = state.digest(payload.get('boxes'))
    cached = metadata.get('ray_queries', {}).get(cache_key)
    if cached and cached.get('selection_id') in run.get('selections', {}):
        return {**cached, 'cached': True}
    from . import scoped_rays
    tally, samples, limited = scoped_rays.cast(run, metadata, points)
    source = state.objects(run)
    selected = reference.selection(run, list(tally), key, 'ray_candidates', persist=False)
    result = {'selection_id': selected, 'evidence_id': key, 'sample_count': samples,
            'requested_samples': len(points), 'budget_limited': limited,
            'misses': samples-sum(tally.values()), 'candidate_count': len(tally),
            'traversal_limit_rays': 0, 'method': 'captured_meshes_only',
            'candidates': [{'object_id': k, 'name': source[k].name, 'hits': count}
                           for k, count in tally.most_common()],
            'limitations': 'Candidates only. A time-limited result is partial. Thin, transparent and hidden parts may be missed; absence never proves omission. The budget is checked between native calls.'}
    if not limited:
        cache = metadata.setdefault('ray_queries', {})
        cache[cache_key] = result
        while len(cache)>8: del cache[next(iter(cache))]
    state.persist(run)
    return result
