# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""What the canvas menus can offer, and how they offer it.

Split out of `moodboard_menus.py` when that file crossed the 500-line rule.
Both the right-click context menu and the output-plus continuation menu ask the
same questions — is this capability live on the moodboard surface, what mesh is
selected, where was the noodle dropped — so the answers live here rather than
being imported from one menu module into the other.
"""

from mixar.modules.moodboard.core import node_layout  # noqa: F401  (re-export)


from mixar.modules.moodboard.core.capabilities import capability_available
from mixar.modules.moodboard.core.node_templates import template_available


MESH_CONTINUATIONS = (
    ('PBR_GEN', "PBR Generation", 'TEXTURE', "pbr_generation"),
    ('RETOPOLOGY', "Retopology", 'MOD_REMESH', "retopology"),
    ('MESH_SEGMENT', "Mesh Segmentation", 'MOD_EXPLODE', "mesh_segmentation"),
    ('AUTO_RIG', "Auto Rig", 'ARMATURE_DATA', "animate"),
)
# Local, so it has no capability. Offered only from a body it can rig parts
# to; never from ASSEMBLE itself, whose output would re-export body + parts.
ASSEMBLE_CONTINUATION = ('ASSEMBLE', "Assemble onto this body", 'BONE_DATA', None)


def _is_rigged_asset(asset) -> bool:
    preview = getattr(asset, "preview_object", None)
    try:
        return preview is not None and (
            preview.type == 'ARMATURE' or preview.find_armature() is not None
        )
    except Exception:
        return False


def mesh_continuations_for(scene, source_id: str) -> list:
    """The "Continue in 3D" entries a mesh source offers. Read-only (menu draws).

    The catalog-gated mesh features, plus Assemble when the source is a body
    Assemble can use: an Auto Rig result, a mesh that already has an armature,
    or a Generate-to-3D result while Auto Rig is unavailable (a static,
    unrigged assembly). An Assemble card offers nothing.
    """
    from mixar.modules.moodboard.core.node_graph import action_node_by_id, asset_node_by_id

    action = action_node_by_id(scene, source_id)
    if action is not None and action.action_type == 'ASSEMBLE':
        return []
    entries = [entry for entry in MESH_CONTINUATIONS if capability_available(entry[3])]
    if action is not None:
        body = action.action_type == 'AUTO_RIG' or (
            action.action_type == 'MODEL_3D' and not template_available('AUTO_RIG')
        )
    else:
        body = _is_rigged_asset(asset_node_by_id(scene, source_id))
    if body:
        entries.append(ASSEMBLE_CONTINUATION)
    return entries


def mesh_source_id(scene) -> str:
    """Node id of the active/selected node that currently holds a 3D mesh."""
    try:
        from mixar.modules.moodboard.core.node_graph import node_holds_mesh
    except Exception:
        return ""
    active = str(getattr(scene, "mixie_moodboard_active_node_id", "") or "")
    if active and node_holds_mesh(scene, active):
        return active
    for asset in getattr(scene, "mixie_moodboard_asset_nodes", ()):
        if asset.selected and node_holds_mesh(scene, asset.node_id):
            return asset.node_id
    for node in getattr(scene, "mixie_moodboard_action_nodes", ()):
        if node.selected and node_holds_mesh(scene, node.node_id):
            return node.node_id
    return ""


def connected_action(
    layout, action_type: str, text: str, icon: str, source="", drop=None,
    allow_empty=False,
):
    op = layout.operator(
        "mixie.moodboard_create_connected_action", text=text, icon=icon
    )
    op.action_type = action_type
    op.source_node_id = source
    if drop is not None:
        op.use_drop_position = True
        op.drop_x, op.drop_y = drop
    # Only the Shift+A Add menu sets this — a standalone node with no source.
    op.allow_empty = allow_empty
    return op


def draw_character_sheet_entry(layout, source_id: str = "", drop=None):
    """The Character Sheet to 3D workflow, built from *source_id* (or the selection)."""
    op = layout.operator(
        "mixie.moodboard_add_template", text="Character Sheet to 3D", icon='COMMUNITY'
    )
    op.template = 'CHARACTER_SHEET_3D'
    op.source_node_id = source_id
    if drop is not None:
        op.from_drop = True
        op.drop_x, op.drop_y = drop
    return op


def link_drop_anchor(scene):
    """Canvas point a dragged noodle was released at, or None.

    Read-only: this runs from a menu draw, so it must never write scene data.
    The C++ graph modal sets the flag just before opening this menu and clears
    it at every other entry point, so a stale anchor cannot leak into a node
    created from the output handle or the right-click menu.
    """
    if not getattr(scene, "mixie_moodboard_link_drop_active", False):
        return None
    return (
        float(getattr(scene, "mixie_moodboard_link_drop_x", 0.0)),
        float(getattr(scene, "mixie_moodboard_link_drop_y", 0.0)),
    )
