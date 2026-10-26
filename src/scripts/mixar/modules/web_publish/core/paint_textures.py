# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Prepare paint channel images before the shared export material swap.

Bakes are retained as reusable caches. The artist's material assignments,
live/baked display choice, active nodes and selection are restored, including
when a bake operator returns CANCELLED instead of raising.
"""

from contextlib import contextmanager
import json

import bpy


def _used_channels(node):
    from mixar.modules.paint.core.layer.check_layers import is_any_layer_using_channel

    return [ch for ch in node.node_tree.mp.channels
            if is_any_layer_using_channel(ch, node)]


def _missing_images(node, channels):
    return [ch.name for ch in channels
            if not (node.node_tree.nodes.get(ch.baked)
                    and node.node_tree.nodes.get(ch.baked).image)]


@contextmanager
def prepared_paint_textures(meshes):
    from .direct_paint_images import staged_direct_paint_images

    with staged_direct_paint_images(meshes), _prepared_paint_bakes(meshes):
        yield


@contextmanager
def _prepared_paint_bakes(meshes):
    from mixar.modules.space_mixie_chat.core.export_preflight import active_mixar_nodes

    jobs = []
    seen = set()
    for obj in meshes:
        for index, material in enumerate(getattr(obj.data, "materials", ())):
            nodes = active_mixar_nodes(material)
            if not nodes:
                continue
            if len(nodes) != 1:
                raise RuntimeError(f"{material.name}: publishing multiple active paint stacks is not supported")
            node = nodes[0]
            channels = _used_channels(node)
            if not channels:
                raise RuntimeError(f"{material.name}: no paint channels can be baked for publishing")
            tree = node.node_tree
            # A live stack may have stale caches from an earlier bake. Refresh
            # it even if every channel already has a baked image node.
            if tree.mp.use_baked and not _missing_images(node, channels):
                continue
            if not len(obj.data.uv_layers):
                raise RuntimeError(f"{material.name}: add a UV map before publishing paint textures")
            key = material.as_pointer()
            if key not in seen:
                seen.add(key)
                jobs.append((obj, index, material, node, channels))

    if not jobs:
        yield
        return
    if bpy.app.is_job_running('RENDER'):
        raise RuntimeError("Wait for the current render before publishing paint textures")

    context = bpy.context
    active = context.view_layer.objects.active
    selected = list(context.selected_objects)
    mode = active.mode if active else 'OBJECT'
    slots = [(obj, obj.active_material_index) for obj in meshes]
    nodes = [(material, material.node_tree.nodes.active) for _, _, material, _, _ in jobs]
    displays = [(node.node_tree.mp, node.node_tree.mp.use_baked) for _, _, _, node, _ in jobs]
    target_names = json.dumps([obj.name for obj in meshes])
    try:
        if active and mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        for obj, index, material, node, channels in jobs:
            context.view_layer.objects.active = obj
            obj.active_material_index = index
            material.node_tree.nodes.active = node
            obj.select_set(True)
            try:
                result = bpy.ops.wm.m_bake_channels(
                    'EXEC_DEFAULT', only_active_channel=False,
                    export_target_names=target_names,
                )
                if 'FINISHED' not in result:
                    raise RuntimeError(f"{material.name}: paint texture bake did not finish; publication stopped")
                missing = _missing_images(node, channels)
                if missing:
                    raise RuntimeError(f"{material.name}: missing baked paint textures: {', '.join(missing)}")
            finally:
                obj.select_set(False)
        yield
    finally:
        for mp, use_baked in reversed(displays):
            mp.use_baked = use_baked
        for material, node in nodes:
            material.node_tree.nodes.active = node
        for obj, index in slots:
            obj.active_material_index = index
        bpy.ops.object.select_all(action='DESELECT')
        for obj in selected:
            obj.select_set(True)
        context.view_layer.objects.active = active
        if active and mode != 'OBJECT':
            bpy.ops.object.mode_set(mode=mode)
