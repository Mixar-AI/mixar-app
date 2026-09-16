# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Versioned asset loading. Preserve collection assemblies and authored materials."""

import hashlib
import math

import bpy
from mathutils import Vector

from .catalog.service import resolve


def load_source(asset_id, revision):
    item = resolve(asset_id, revision)
    with open(item['path'], 'rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    if actual != revision:
        raise ValueError('Asset file changed since indexing; Refresh Libraries and search again')
    key = asset_id + ':' + revision
    for coll in bpy.data.collections:
        if coll.get('mixar_asset_source') == key:
            return coll
    with bpy.data.libraries.load(item['path'], link=False, assets_only=True) as (src, dst):
        names = src.collections if item['kind'] == 'COLLECTION' else src.objects
        if item['name'] not in names:
            raise ValueError('Asset is no longer marked in this file; Refresh Libraries')
        if item['kind'] == 'COLLECTION':
            dst.collections = [item['name']]
        else:
            dst.objects = [item['name']]
    wrapper = bpy.data.collections.new('Library Source ' + item['name'])
    wrapper['mixar_asset_source'] = key
    if item['kind'] == 'COLLECTION':
        wrapper.children.link(dst.collections[0])
    else:
        wrapper.objects.link(dst.objects[0])
    # Collections remain unlinked from scenes; GN references the whole assembly.
    return wrapper


def bounds(source):
    points = []
    def visit(ob, transform, depth=0):
        if depth > 12:
            raise ValueError('Collection instance nesting exceeds 12 levels')
        matrix = transform @ ob.matrix_world
        if ob.type in {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}:
            points.extend(matrix @ Vector(p) for p in ob.bound_box)
        elif ob.instance_type == 'COLLECTION' and ob.instance_collection:
            from mathutils import Matrix
            nested = matrix @ Matrix.Translation(-ob.instance_collection.instance_offset)
            for child in ob.instance_collection.all_objects:
                visit(child, nested, depth+1)
    from mathutils import Matrix
    for ob in source.all_objects:
        visit(ob, Matrix.Identity(4))
    if not points:
        raise ValueError('Asset contains no measurable geometry')
    minimum = Vector(tuple(min(p[k] for p in points) for k in range(3)))
    maximum = Vector(tuple(max(p[k] for p in points) for k in range(3)))
    return minimum, maximum


def append_asset(scene, asset_id, revision, location=(0, 0, 0)):
    if (not isinstance(location, (list, tuple)) or len(location) != 3 or
            any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in location)):
        raise ValueError('location must contain three finite coordinates')
    before = set(bpy.data.user_map())
    try:
        source = load_source(asset_id, revision)
        obj = bpy.data.objects.new('Library Asset', None)
        obj.instance_type = 'COLLECTION'
        obj.instance_collection = source
        obj.location = location
        obj['mixar_library_asset'] = True
        obj['mixar_catalog_asset_id'] = asset_id
        obj['mixar_catalog_revision'] = revision
        scene.collection.objects.link(obj)
    except Exception:
        bpy.data.batch_remove(set(bpy.data.user_map()) - before)
        raise
    return {'success': True, 'object': obj.name, 'asset_id': asset_id, 'revision': revision}
