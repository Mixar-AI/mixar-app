# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic area-weighted sampling in world space, independent of Blender."""

import math
import numpy as np


def sample_surface(vertices, triangles, *, count, seed=0, slope=(0, 90),
                   min_distance=0.0, weights=None):
    vertices = np.asarray(vertices, dtype=np.float64)
    triangles = np.asarray(triangles, dtype=np.int64)
    if not len(triangles):
        raise ValueError('Scatter surface has no triangles')
    corners = vertices[triangles]
    cross = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    lengths = np.linalg.norm(cross, axis=1)
    normals = cross / np.maximum(lengths[:, None], 1e-20)
    angles = np.degrees(np.arccos(np.clip(normals[:, 2], -1, 1)))
    area = lengths * .5
    area *= (angles >= slope[0]) & (angles <= slope[1])
    corner_weights = None
    if weights is not None:
        weights = np.asarray(weights, dtype=np.float64)
        corner_weights = np.clip(weights[triangles], 0, 1)
        area *= corner_weights.mean(axis=1)
    total = float(area.sum())
    if total <= 1e-12 or not math.isfinite(total):
        raise ValueError('No surface area matches the slope/density mask')
    rng = np.random.default_rng(seed)
    accepted, directions, grid = [], [], {}
    cell = float(min_distance)
    # A hard attempt budget makes impossible spacing terminate honestly.
    for _ in range(20):
        remaining = count - len(accepted)
        if remaining <= 0:
            break
        indices = rng.choice(len(area), size=max(remaining * 2, 16), p=area / total)
        if corner_weights is None:
            uv = rng.random((len(indices), 2))
            flip = uv.sum(axis=1) > 1
            uv[flip] = 1 - uv[flip]
            bary = np.column_stack((1-uv.sum(axis=1), uv))
        else:
            # Exact linear vertex-weight density: a mixture of Dirichlet(2,1,1)
            # distributions. Face averages alone would scatter uniformly across
            # partially masked triangles and ignore the painted boundary.
            w = corner_weights[indices]
            cdf = np.cumsum(w / w.sum(axis=1, keepdims=True), axis=1)
            corner = (rng.random(len(indices))[:, None] > cdf).sum(axis=1)
            alpha = np.ones((len(indices), 3))
            alpha[np.arange(len(indices)), np.minimum(corner, 2)] = 2
            bary = rng.gamma(alpha)
            bary /= bary.sum(axis=1, keepdims=True)
        picked = corners[indices]
        pts = np.sum(picked * bary[:, :, None], axis=1)
        for point, index in zip(pts, indices):
            if cell > 0:
                key = tuple(np.floor(point / cell).astype(int))
                nearby = (j for x in (-1, 0, 1) for y in (-1, 0, 1) for z in (-1, 0, 1)
                          for j in grid.get((key[0]+x, key[1]+y, key[2]+z), ()))
                if any(np.linalg.norm(point-accepted[j]) < cell for j in nearby):
                    continue
                grid.setdefault(key, []).append(len(accepted))
            accepted.append(point)
            directions.append(normals[index])
            if len(accepted) == count:
                break
    return np.asarray(accepted), np.asarray(directions)


def validate_layers(layers):
    if not isinstance(layers, list) or not 1 <= len(layers) <= 16:
        raise ValueError('Provide between 1 and 16 asset layers')
    result, ids, total = [], set(), 0
    for i, raw in enumerate(layers):
        if not isinstance(raw, dict):
            raise ValueError('Each layer must be an object')
        layer = dict(raw)
        lid = str(layer.get('id') or f'layer_{i+1}')
        if lid in ids:
            raise ValueError('Layer IDs must be unique')
        ids.add(lid)
        if not layer.get('asset_id') or not layer.get('revision'):
            raise ValueError('Every layer needs asset_id and revision from search')
        count = layer.get('count', 100)
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 10000:
            raise ValueError('Layer count must be an integer from 1 to 10000')
        scale = layer.get('scale', [1.0, 1.0])
        slope = layer.get('slope', [0.0, 90.0])
        if not isinstance(scale, (list, tuple)) or len(scale) != 2:
            raise ValueError('Scale must be [minimum, maximum]')
        if not isinstance(slope, (list, tuple)) or len(slope) != 2:
            raise ValueError('Slope must be [minimum, maximum] in degrees')
        scale, slope = [float(x) for x in scale], [float(x) for x in slope]
        distance = float(layer.get('min_distance', 0))
        if not all(math.isfinite(x) for x in scale+slope+[distance]):
            raise ValueError('Scatter parameters must be finite')
        if not 0 < scale[0] <= scale[1] <= 100 or not 0 <= slope[0] <= slope[1] <= 90 or distance < 0:
            raise ValueError('Invalid scale, slope, or minimum distance')
        result.append({**layer, 'id': lid, 'count': count, 'scale': scale,
                       'slope': slope, 'min_distance': distance})
        total += count
    if total > 50000:
        raise ValueError('A scatter may contain at most 50000 instances')
    return result
