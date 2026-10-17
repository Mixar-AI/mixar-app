# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Isolate animated data IDs as well as objects; keep static geometry shared.

An active depsgraph flushes evaluated animated RNA values back to original IDs.
Sharing an animated light or shape-key mesh would therefore move the project's
values even when the preview used different objects and a different scene.
"""


def animated(data, visiting=None):
    if data is None:
        return False
    visiting = set() if visiting is None else visiting
    if data in visiting:
        return False
    visiting.add(data)
    if getattr(data, 'animation_data', None):
        return True
    if animated(getattr(data, 'shape_keys', None), visiting):
        return True
    if animated(getattr(data, 'node_tree', None), visiting):
        return True
    return any(animated(getattr(node, 'node_tree', None), visiting)
               for node in getattr(data, 'nodes', ()))


def isolate(data, session):
    if data is None or data in session.static_data:
        return data
    if data in session.data_copies:
        return session.data_copies[data]
    if not animated(data):
        session.static_data.add(data)
        return data
    copy = data.copy()
    session.data_copies[data] = copy
    session.data.append(copy)
    keys = getattr(copy, 'shape_keys', None)
    if keys is not None and keys != data.shape_keys:
        session.data_copies[data.shape_keys] = keys
        session.data.append(keys)
    original_tree = getattr(data, 'node_tree', None)
    tree = getattr(copy, 'node_tree', None)
    if tree and tree != original_tree:
        session.data_copies[original_tree] = tree
    # Embedded node trees are owned by their parent ID; Blender frees them.
    for node in getattr(tree or copy, 'nodes', ()):
        group = getattr(node, 'node_tree', None)
        if group is not None:
            node.node_tree = isolate(group, session)
    return copy


def isolate_object(original, copy, session):
    if original.data:
        copy.data = isolate(original.data, session)
    for index, slot in enumerate(original.material_slots):
        material = isolate(slot.material, session)
        if material != slot.material:
            # Never replace a material on a shared, static mesh datablock.
            copy.material_slots[index].link = 'OBJECT'
            copy.material_slots[index].material = material
    for modifier in copy.modifiers:
        if modifier.type == 'NODES':
            modifier.node_group = isolate(modifier.node_group, session)


def remap_drivers(data, copies):
    anim = getattr(data, 'animation_data', None)
    if anim is None:
        return
    for curve in anim.drivers:
        for variable in curve.driver.variables:
            for target in variable.targets:
                if target.id in copies:
                    target.id = copies[target.id]
