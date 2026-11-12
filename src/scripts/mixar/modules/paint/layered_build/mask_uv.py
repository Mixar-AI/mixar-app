# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""A geometry mask is one map, independent of material texture repetition."""
import numpy as np

_UV_KEY = 'mixar_mask_bake_uv'


def normalized_mask_uvs(coords):
    """Return a single-tile copy for repeating/UDIM UVs; None if already valid.

    Preserve the layout and aspect ratio. Padding keeps border samples inside
    tile 1001 instead of letting automatic UDIM detection allocate more tiles.
    """
    coords = np.asarray(coords, dtype=np.float32).reshape(-1, 2)
    if not len(coords) or not np.isfinite(coords).all():
        raise ValueError('A baked material mask requires finite UV coordinates.')
    low, high = coords.min(axis=0), coords.max(axis=0)
    if (low >= 0).all() and (high <= 1).all():
        return None
    span = float((high - low).max())
    if span <= 0:
        raise ValueError('Unwrap the mesh before baking a material mask.')
    return (coords - low) * (0.998 / span) + 0.001


def mask_bake_uv(obj, uv_name):
    """Retain the original shading UV and make/reuse a separate mask UV."""
    mesh = obj.data
    source = mesh.uv_layers.get(uv_name) if uv_name else mesh.uv_layers.active
    if source is None:
        raise ValueError('Unwrap the mesh before baking a material mask.')
    original = np.empty(len(source.data) * 2, dtype=np.float32)
    source.data.foreach_get('uv', original)
    normalized = normalized_mask_uvs(original)
    if normalized is None:
        return source.name
    active = mesh.uv_layers.active_index
    render_uv = next((uv.name for uv in mesh.uv_layers if uv.active_render), None)
    target = mesh.uv_layers.get(mesh.get(_UV_KEY, ''))
    if target is None or target == source:
        target = mesh.uv_layers.new(name='Mixar Mask UV', do_init=False)
        if target is None:
            raise ValueError('Free a UV map slot before baking a material mask.')
        mesh[_UV_KEY] = target.name
    try:
        target.data.foreach_set('uv', normalized.ravel())
    finally:
        mesh.uv_layers.active_index = active
        if render_uv:
            mesh.uv_layers[render_uv].active_render = True
    return target.name
