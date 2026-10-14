# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Small, read-only selection resolver for Zen's floating object controls."""
from ..constants import BASIC_WORKSPACE_NAME


def selected_object(context):
    """A deselected active ID must never keep the strip visible."""
    workspace = getattr(context, "workspace", None)
    obj = getattr(context, "object", None)
    if (workspace is None or workspace.name != BASIC_WORKSPACE_NAME
            or context.mode != "OBJECT" or obj is None
            or obj.type not in {"MESH", "LIGHT"}):
        return None
    if not obj.select_get(view_layer=context.view_layer):
        return None
    return obj


def selected_modifier(obj):
    return obj.modifiers.active


def editable_mesh(context, object_name=None):
    obj = selected_object(context)
    if (obj is None or obj.type != "MESH" or not obj.is_editable
            or (object_name is not None and obj.name != object_name)):
        return None
    return obj

