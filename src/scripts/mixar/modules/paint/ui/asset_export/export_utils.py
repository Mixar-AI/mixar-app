# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared utilities for the format-specific export operators."""

from ...core.node.node_utils import get_active_mpaint_node


def export_poll(context):
    """Shared poll: baked channels, active MESH object, active material."""
    node = get_active_mpaint_node()
    if not node or not node.node_tree:
        return False
    if not node.node_tree.mp.use_baked:
        return False
    obj = context.active_object
    return obj and obj.type == "MESH" and obj.active_material


def settings_to_kwargs(settings, exclude=None):
    """Convert a PropertyGroup's properties to a kwargs dict.

    Skips internal Blender RNA properties and any names in *exclude*.
    """
    skip = {'rna_type', 'name'}
    if exclude:
        skip.update(exclude)
    kwargs = {}
    for prop in settings.bl_rna.properties:
        ident = prop.identifier
        if ident in skip:
            continue
        val = getattr(settings, ident)
        # EnumFlag properties return a set; convert to a plain set for the op
        if prop.is_enum_flag:
            val = set(val)
        kwargs[ident] = val
    return kwargs
